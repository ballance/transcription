"""
WhisperX transcription pipeline with word-level timestamps and optional speaker diarization.

Three-stage pipeline: transcribe → align → diarize (optional).
Alignment and diarization failures degrade gracefully — the transcription still succeeds
with segment-level timestamps only.
"""

import logging
import re

import functools
import torch

# PyTorch 2.6+ defaults to weights_only=True in torch.load, but pyannote
# model checkpoints contain omegaconf/typing objects that aren't allowlisted.
# Patch torch.load to default to weights_only=False for these trusted models.
_original_torch_load = torch.load

@functools.wraps(_original_torch_load)
def _patched_torch_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)

torch.load = _patched_torch_load

import whisperx
from whisperx.diarize import DiarizationPipeline

from config import config
from speaker_profiles import load_profiles, match_speakers

logger = logging.getLogger(__name__)

# Module-level model caches (loaded lazily, reused across calls)
_whisperx_model = None
_align_model_cache: dict[str, tuple] = {}  # language → (model, metadata)
_diarize_pipeline = None


def load_transcription_model():
    """Load and cache the WhisperX transcription model."""
    global _whisperx_model

    if _whisperx_model is not None:
        return _whisperx_model

    device = config.whisperx_device
    compute_type = config.resolved_compute_type

    logger.info(
        f"Loading WhisperX model: {config.model_size} on {device} "
        f"(compute_type={compute_type}, batch_size={config.resolved_batch_size})"
    )

    _whisperx_model = whisperx.load_model(
        config.model_size,
        device=device,
        compute_type=compute_type,
    )

    logger.info(f"Successfully loaded WhisperX model: {config.model_size} on {device}")
    return _whisperx_model


def _load_align_model(language_code: str):
    """Load and cache the alignment model for the given language."""
    if language_code in _align_model_cache:
        return _align_model_cache[language_code]

    device = config.whisperx_device
    logger.info(f"Loading alignment model for language: {language_code}")

    model, metadata = whisperx.load_align_model(
        language_code=language_code,
        device=device,
    )
    _align_model_cache[language_code] = (model, metadata)
    return model, metadata


def _load_diarize_pipeline():
    """Load and cache the diarization pipeline."""
    global _diarize_pipeline

    if _diarize_pipeline is not None:
        return _diarize_pipeline

    logger.info("Loading diarization pipeline")
    _diarize_pipeline = DiarizationPipeline(
        use_auth_token=config.hf_token,
        device=config.whisperx_device,
    )
    return _diarize_pipeline


def transcribe(audio_path: str, language: str = "en") -> dict:
    """
    Run the full WhisperX pipeline: transcribe → align → diarize.

    Returns a dict with:
        - "segments": list of segment dicts (start, end, text, and optionally speaker)
        - "language": detected language code
        - "diarization_applied": bool
    """
    model = load_transcription_model()
    device = config.whisperx_device

    # Stage 1: Transcribe
    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(
        audio,
        batch_size=config.resolved_batch_size,
        language=language if language != "auto" else None,
    )

    detected_language = result.get("language", language)
    segments = result.get("segments", [])

    # Stage 2: Align (for word-level timestamps)
    try:
        align_model, align_metadata = _load_align_model(detected_language)
        result = whisperx.align(
            segments,
            align_model,
            align_metadata,
            audio,
            device=device,
        )
        segments = result.get("segments", segments)
        logger.info(f"Alignment succeeded for {len(segments)} segments")
    except Exception as e:
        logger.warning(f"Alignment failed (continuing with segment-level timestamps): {e}")

    # Stage 3: Diarize (optional)
    diarization_applied = False
    recognized_speakers = {}
    if config.enable_diarization and config.hf_token:
        try:
            diarize_pipeline = _load_diarize_pipeline()
            diarize_kwargs = {}
            if config.min_speakers is not None:
                diarize_kwargs["min_speakers"] = config.min_speakers
            if config.max_speakers is not None:
                diarize_kwargs["max_speakers"] = config.max_speakers

            # Request embeddings when speaker recognition is enabled
            if config.enable_speaker_recognition:
                diarize_kwargs["return_embeddings"] = True

            diarize_result = diarize_pipeline(audio_path, **diarize_kwargs)

            # Handle return_embeddings=True returning a tuple
            speaker_embeddings = {}
            if isinstance(diarize_result, tuple) and len(diarize_result) == 2:
                diarize_segments, speaker_embeddings = diarize_result
            else:
                diarize_segments = diarize_result

            result = whisperx.assign_word_speakers(diarize_segments, {"segments": segments})
            segments = result.get("segments", segments)
            diarization_applied = True
            logger.info(f"Diarization succeeded for {len(segments)} segments")

            # Speaker recognition: match embeddings to enrolled profiles
            if config.enable_speaker_recognition and speaker_embeddings:
                try:
                    profiles = load_profiles(config.speaker_profiles_path)
                    if profiles:
                        recognized_speakers = match_speakers(
                            speaker_embeddings,
                            profiles,
                            config.speaker_recognition_threshold,
                        )
                        if recognized_speakers:
                            logger.info(
                                f"Recognized {len(recognized_speakers)} speaker(s): "
                                f"{', '.join(recognized_speakers.values())}"
                            )
                            # Replace SPEAKER_XX labels with recognized names
                            for seg in segments:
                                speaker = seg.get("speaker", "")
                                if speaker in recognized_speakers:
                                    seg["speaker"] = recognized_speakers[speaker]
                                # Also replace in word-level data
                                for word in seg.get("words", []):
                                    ws = word.get("speaker", "")
                                    if ws in recognized_speakers:
                                        word["speaker"] = recognized_speakers[ws]
                        else:
                            logger.info("No speakers matched enrolled profiles")
                    else:
                        logger.info(
                            f"No speaker profiles found at {config.speaker_profiles_path}"
                        )
                except Exception as e:
                    logger.warning(f"Speaker recognition failed (continuing with SPEAKER_XX labels): {e}")

        except Exception as e:
            logger.warning(f"Diarization failed (continuing without speaker labels): {e}")

    return {
        "segments": segments,
        "language": detected_language,
        "diarization_applied": diarization_applied,
        "recognized_speakers": recognized_speakers,
    }


def _format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_segments_as_text(segments: list[dict], diarization_applied: bool) -> str:
    """
    Format segments into timestamped text output.

    With diarization:
        [00:00:00 - 00:00:12] SPEAKER_00: Hello world.

    Without diarization:
        [00:00:00 - 00:00:12] Hello world.
    """
    lines = []
    for seg in segments:
        start = _format_time(seg.get("start", 0))
        end = _format_time(seg.get("end", 0))
        text = seg.get("text", "").strip()
        if not text:
            continue

        if diarization_applied and "speaker" in seg:
            lines.append(f"[{start} - {end}] {seg['speaker']}: {text}")
        else:
            lines.append(f"[{start} - {end}] {text}")

    return "\n\n".join(lines)


def strip_formatting_for_summary(text: str) -> str:
    """Strip timestamp prefixes and speaker labels to get plain text for summary extraction."""
    # Remove lines starting with # (metadata)
    lines = [line for line in text.split("\n") if not line.startswith("#")]
    text = "\n".join(lines)

    # Remove [HH:MM:SS - HH:MM:SS] prefixes and optional speaker labels
    # (handles both SPEAKER_XX and recognized names like "Alice:")
    text = re.sub(r"\[\d{2}:\d{2}:\d{2}\s*-\s*\d{2}:\d{2}:\d{2}\]\s*", "", text)
    text = re.sub(r"SPEAKER_\d+:\s*", "", text)
    text = re.sub(r"^[A-Z][A-Za-z ]+:\s*", "", text, flags=re.MULTILINE)

    return text.strip()
