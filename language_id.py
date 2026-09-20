"""
Voice activity detection + spoken language identification for code-switched audio.

Pipeline: silero VAD → speechbrain VoxLingua107 lang-id → coalesce adjacent same-lang regions.
Used by `transcribe_multilingual` to slice audio into single-language regions before
running Whisper with the correct language forced for each region.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import torch

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# ISO 639-3 → 639-1. VoxLingua107 emits 3-letter codes (e.g. "eng: English"); Whisper expects 2-letter.
# Covers the languages Whisper supports that overlap with VoxLingua107.
_ISO3_TO_ISO1 = {
    "eng": "en", "spa": "es", "fra": "fr", "deu": "de", "por": "pt",
    "ita": "it", "jpn": "ja", "kor": "ko", "zho": "zh", "rus": "ru",
    "ara": "ar", "hin": "hi", "nld": "nl", "pol": "pl", "tur": "tr",
    "swe": "sv", "ces": "cs", "fin": "fi", "nor": "no", "dan": "da",
    "ell": "el", "ukr": "uk", "vie": "vi", "tha": "th", "ind": "id",
    "ron": "ro", "hun": "hu", "heb": "he", "cat": "ca", "bul": "bg",
    "slk": "sk", "hrv": "hr", "srp": "sr", "lit": "lt", "lav": "lv",
    "est": "et", "slv": "sl", "msa": "ms", "fil": "tl", "swa": "sw",
    "afr": "af", "isl": "is", "fas": "fa", "urd": "ur", "ben": "bn",
    "tam": "ta", "tel": "te", "mar": "mr", "guj": "gu", "kan": "kn",
    "mal": "ml", "pan": "pa", "nep": "ne", "sin": "si", "khm": "km",
    "lao": "lo", "mya": "my", "amh": "am", "yor": "yo", "hau": "ha",
    "som": "so", "epo": "eo", "lat": "la", "wel": "cy", "gle": "ga",
    "mkd": "mk", "bos": "bs", "aze": "az", "kat": "ka", "hye": "hy",
    "kaz": "kk", "tat": "tt", "uzb": "uz", "mon": "mn", "bel": "be",
}


@dataclass
class LangSegment:
    """A speech region tagged with its detected language (ISO 639-1)."""

    start: float
    end: float
    language: str


_vad_model = None
_lang_id_model = None
_lang_id_index_to_iso1: dict[int, str] | None = None


def _load_vad():
    global _vad_model
    if _vad_model is None:
        from silero_vad import load_silero_vad
        logger.info("Loading silero VAD model")
        _vad_model = load_silero_vad()
    return _vad_model


def _normalize_lang_label(label: str) -> str:
    """Convert a VoxLingua107 label like 'eng: English' to ISO 639-1 ('en')."""
    head = label.split(":", 1)[0].strip().lower()
    return _ISO3_TO_ISO1.get(head, head)


def _load_lang_id():
    global _lang_id_model, _lang_id_index_to_iso1
    if _lang_id_model is None:
        from speechbrain.inference.classifiers import EncoderClassifier
        logger.info("Loading speechbrain lang-id model (VoxLingua107)")
        _lang_id_model = EncoderClassifier.from_hparams(
            source="speechbrain/lang-id-voxlingua107-ecapa",
            savedir="./models/lang-id",
            run_opts={"device": "cpu"},
        )
        ind2lab = _lang_id_model.hparams.label_encoder.ind2lab
        _lang_id_index_to_iso1 = {idx: _normalize_lang_label(lab) for idx, lab in ind2lab.items()}
    return _lang_id_model


def vad_segments(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> list[tuple[float, float]]:
    """Run silero VAD; returns speech regions as (start_sec, end_sec) tuples."""
    from silero_vad import get_speech_timestamps
    model = _load_vad()
    audio_tensor = torch.from_numpy(audio.astype(np.float32))
    timestamps = get_speech_timestamps(audio_tensor, model, sampling_rate=sample_rate)
    return [(t["start"] / sample_rate, t["end"] / sample_rate) for t in timestamps]


def label_languages(
    audio: np.ndarray,
    segments: list[tuple[float, float]],
    allowed_languages: list[str],
    sample_rate: int = SAMPLE_RATE,
    min_duration: float = 1.0,
) -> list[LangSegment]:
    """Tag each VAD segment with the most likely language from `allowed_languages`."""
    classifier = _load_lang_id()
    allowed_set = {lang.lower() for lang in allowed_languages}
    allowed_indices = [idx for idx, iso in _lang_id_index_to_iso1.items() if iso in allowed_set]
    if not allowed_indices:
        raise ValueError(
            f"None of {allowed_languages} are in the lang-id model vocabulary"
        )

    labeled: list[LangSegment] = []
    for start, end in segments:
        duration = end - start
        if duration < min_duration:
            labeled.append(LangSegment(start, end, ""))
            continue
        chunk = audio[int(start * sample_rate):int(end * sample_rate)]
        if chunk.size == 0:
            labeled.append(LangSegment(start, end, ""))
            continue
        wav = torch.from_numpy(chunk.astype(np.float32)).unsqueeze(0)
        with torch.no_grad():
            out_prob, _, _, _ = classifier.classify_batch(wav)
        probs = out_prob[0]
        best_idx = max(allowed_indices, key=lambda i: probs[i].item())
        labeled.append(LangSegment(start, end, _lang_id_index_to_iso1[best_idx]))

    _backfill(labeled, default=allowed_languages[0])
    return labeled


def _backfill(segs: list[LangSegment], default: str) -> None:
    """Fill empty `language` fields using the nearest labeled neighbor."""
    n = len(segs)
    for i, s in enumerate(segs):
        if s.language:
            continue
        for j in list(range(i + 1, n)) + list(range(i - 1, -1, -1)):
            if segs[j].language:
                s.language = segs[j].language
                break
        if not s.language:
            s.language = default


def coalesce(segs: list[LangSegment], max_gap: float = 2.0) -> list[LangSegment]:
    """Merge adjacent same-language segments separated by no more than `max_gap` seconds."""
    if not segs:
        return []
    out = [LangSegment(segs[0].start, segs[0].end, segs[0].language)]
    for s in segs[1:]:
        last = out[-1]
        if s.language == last.language and (s.start - last.end) <= max_gap:
            last.end = s.end
        else:
            out.append(LangSegment(s.start, s.end, s.language))
    return out


def segment_by_language(
    audio: np.ndarray,
    allowed_languages: list[str],
    sample_rate: int = SAMPLE_RATE,
) -> list[LangSegment]:
    """End-to-end: VAD → lang-id → coalesce. Returns absolute-time language regions."""
    segs = vad_segments(audio, sample_rate)
    if not segs:
        return [LangSegment(0.0, len(audio) / sample_rate, allowed_languages[0])]
    labeled = label_languages(audio, segs, allowed_languages, sample_rate)
    return coalesce(labeled)
