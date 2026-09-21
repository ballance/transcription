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

import progress as prog

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
from speaker_profiles import load_all_profiles, match_speakers

logger = logging.getLogger(__name__)

# Module-level model caches (loaded lazily, reused across calls)
_whisperx_model = None
_align_model_cache: dict[str, tuple] = {}  # language → (model, metadata)
_diarize_pipeline = None

# PyTorch stages (align/diarize) can use the Apple GPU via MPS, unlike WhisperX's
# CTranslate2 backend. Start on the resolved device; on an MPS op failure, latch to
# CPU for the rest of the process (MPS has occasional gaps in older torch builds).
_torch_device_override = None  # str | None: latched to "cpu" after an MPS failure


def _torch_device() -> str:
    """Device for the PyTorch align/diarize stages (mps/cuda/cpu, or latched CPU fallback)."""
    return _torch_device_override or config.compute_device


def _with_mps_fallback(stage: str, fn):
    """Run fn(); if it fails on MPS, latch to CPU (clearing caches) and retry once."""
    global _torch_device_override, _align_model_cache, _diarize_pipeline
    try:
        return fn()
    except Exception as e:
        if _torch_device() != "mps":
            raise
        logger.warning(f"{stage} failed on MPS ({e}); latching to CPU and retrying")
        _torch_device_override = "cpu"
        _align_model_cache = {}
        _diarize_pipeline = None
        return fn()


# model_size → mlx-community HF repo for the mlx-whisper backend. Unmapped sizes
# fall back to the conventional name; MLX_WHISPER_REPO overrides entirely (hedges
# against repo names that differ from this convention).
_MLX_REPO_MAP = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "distil-large-v3": "mlx-community/distil-whisper-large-v3",
}


def _mlx_repo() -> str:
    """Resolve the MLX model repo for the configured model size."""
    if config.mlx_whisper_repo:
        return config.mlx_whisper_repo
    return _MLX_REPO_MAP.get(
        config.model_size, f"mlx-community/whisper-{config.model_size}-mlx"
    )


def _mlx_transcribe(audio, language: str) -> dict:
    """Transcribe on the Apple GPU via mlx-whisper.

    Returns a whisperx-shaped dict: {"segments": [...], "language": str}, where
    each segment carries start/end/text — the contract whisperx.align consumes.
    """
    import mlx_whisper  # lazy: Apple-Silicon-only dependency

    repo = _mlx_repo()
    logger.info(f"Transcribing with mlx-whisper on Apple GPU (repo={repo})")
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=repo,
        language=None if language == "auto" else language,
    )
    return {
        "segments": result.get("segments", []),
        "language": result.get("language", language),
    }


def _run_asr(audio, language: str) -> tuple[str, list[dict]]:
    """Stage 1 ASR with backend dispatch. Returns (detected_language, segments).

    Uses mlx-whisper (Apple GPU) when configured; on any mlx failure, falls back
    to the WhisperX (CTranslate2, CPU/CUDA) backend. batch_size applies only to
    the WhisperX path — mlx chunks internally.
    """
    if config.resolved_asr_backend == "mlx":
        try:
            asr = _mlx_transcribe(audio, language)
            return asr["language"], asr["segments"]
        except Exception as e:
            logger.warning(f"mlx-whisper ASR failed ({e}); falling back to WhisperX")

    model = load_transcription_model()
    result = model.transcribe(
        audio,
        batch_size=config.resolved_batch_size,
        language=None if language == "auto" else language,
    )
    return result.get("language", language), result.get("segments", [])


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

    device = _torch_device()
    logger.info(f"Loading alignment model for language: {language_code} on {device}")

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

    device = _torch_device()
    logger.info(f"Loading diarization pipeline on {device}")
    _diarize_pipeline = DiarizationPipeline(
        use_auth_token=config.hf_token,
        device=device,
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
    # Stage 1: Transcribe
    prog.set_stage("loading")
    audio = whisperx.load_audio(audio_path)

    prog.set_stage("transcribing")
    detected_language, segments = _run_asr(audio, language)

    # Stage 2: Align (for word-level timestamps)
    prog.set_stage("aligning")

    def _align():
        align_model, align_metadata = _load_align_model(detected_language)
        return whisperx.align(
            segments,
            align_model,
            align_metadata,
            audio,
            device=_torch_device(),
        )

    try:
        result = _with_mps_fallback("Alignment", _align)
        segments = result.get("segments", segments)
        logger.info(f"Alignment succeeded for {len(segments)} segments")
    except Exception as e:
        logger.warning(f"Alignment failed (continuing with segment-level timestamps): {e}")

    # Stage 3: Diarize (optional)
    diarization_applied = False
    recognized_speakers = {}
    if config.enable_diarization and config.hf_token:
        prog.set_stage("diarizing")
        try:
            diarize_kwargs = {}
            if config.min_speakers is not None:
                diarize_kwargs["min_speakers"] = config.min_speakers
            if config.max_speakers is not None:
                diarize_kwargs["max_speakers"] = config.max_speakers

            # Request embeddings when speaker recognition is enabled
            if config.enable_speaker_recognition:
                diarize_kwargs["return_embeddings"] = True

            diarize_result = _with_mps_fallback(
                "Diarization",
                lambda: _load_diarize_pipeline()(audio_path, **diarize_kwargs),
            )

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
                    profiles = load_all_profiles(
                        config.speaker_profiles_path,
                        config.speaker_profiles_local_path,
                    )
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

    prog.set_stage("saving")
    return {
        "segments": segments,
        "language": detected_language,
        "diarization_applied": diarization_applied,
        "recognized_speakers": recognized_speakers,
    }


def transcribe_multilingual(audio_path: str, languages: list[str]) -> dict:
    """
    Transcribe code-switched audio.

    VAD-segments the file, identifies the language of each region (restricted to
    `languages`), then runs Whisper + alignment per region with the correct
    language forced. Diarization (when enabled) runs once over the full audio
    and is assigned to the stitched timeline.
    """
    from language_id import segment_by_language

    if not languages:
        raise ValueError("languages must be a non-empty list (e.g. ['en', 'es'])")

    sample_rate = 16000

    prog.set_stage("loading")
    audio = whisperx.load_audio(audio_path)

    prog.set_stage("language_id")
    regions = segment_by_language(audio, languages)
    logger.info(
        f"Identified {len(regions)} language region(s): "
        + ", ".join(f"{r.language}({r.end - r.start:.1f}s)" for r in regions)
    )

    prog.set_stage("transcribing")
    all_segments: list[dict] = []
    languages_seen: set[str] = set()
    for region in regions:
        start_idx = int(region.start * sample_rate)
        end_idx = int(region.end * sample_rate)
        sub_audio = audio[start_idx:end_idx]
        if len(sub_audio) == 0:
            continue

        try:
            _, sub_segments = _run_asr(sub_audio, region.language)
        except Exception as e:
            logger.warning(
                f"Transcription failed for region {region.start:.1f}-{region.end:.1f}s "
                f"(lang={region.language}): {e}"
            )
            continue

        try:
            def _align_region(region=region, sub_segments=sub_segments, sub_audio=sub_audio):
                align_model, align_meta = _load_align_model(region.language)
                return whisperx.align(
                    sub_segments, align_model, align_meta, sub_audio, device=_torch_device(),
                )

            aligned = _with_mps_fallback("Alignment", _align_region)
            sub_segments = aligned.get("segments", sub_segments)
        except Exception as e:
            logger.warning(
                f"Alignment failed for region {region.start:.1f}-{region.end:.1f}s "
                f"(lang={region.language}): {e}"
            )

        for seg in sub_segments:
            if "start" in seg:
                seg["start"] += region.start
            if "end" in seg:
                seg["end"] += region.start
            seg["language"] = region.language
            for word in seg.get("words", []):
                if "start" in word:
                    word["start"] += region.start
                if "end" in word:
                    word["end"] += region.start

        all_segments.extend(sub_segments)
        languages_seen.add(region.language)

    all_segments.sort(key=lambda s: s.get("start", 0.0))

    diarization_applied = False
    recognized_speakers: dict = {}
    if config.enable_diarization and config.hf_token:
        prog.set_stage("diarizing")
        try:
            diarize_kwargs = {}
            if config.min_speakers is not None:
                diarize_kwargs["min_speakers"] = config.min_speakers
            if config.max_speakers is not None:
                diarize_kwargs["max_speakers"] = config.max_speakers
            if config.enable_speaker_recognition:
                diarize_kwargs["return_embeddings"] = True

            diarize_result = _with_mps_fallback(
                "Diarization",
                lambda: _load_diarize_pipeline()(audio_path, **diarize_kwargs),
            )

            speaker_embeddings = {}
            if isinstance(diarize_result, tuple) and len(diarize_result) == 2:
                diarize_segments, speaker_embeddings = diarize_result
            else:
                diarize_segments = diarize_result

            assign_result = whisperx.assign_word_speakers(
                diarize_segments, {"segments": all_segments}
            )
            all_segments = assign_result.get("segments", all_segments)
            diarization_applied = True
            logger.info(f"Diarization succeeded for {len(all_segments)} segments")

            if config.enable_speaker_recognition and speaker_embeddings:
                try:
                    profiles = load_all_profiles(
                        config.speaker_profiles_path,
                        config.speaker_profiles_local_path,
                    )
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
                            for seg in all_segments:
                                spk = seg.get("speaker", "")
                                if spk in recognized_speakers:
                                    seg["speaker"] = recognized_speakers[spk]
                                for word in seg.get("words", []):
                                    ws = word.get("speaker", "")
                                    if ws in recognized_speakers:
                                        word["speaker"] = recognized_speakers[ws]
                except Exception as e:
                    logger.warning(
                        f"Speaker recognition failed (continuing with SPEAKER_XX labels): {e}"
                    )
        except Exception as e:
            logger.warning(f"Diarization failed (continuing without speaker labels): {e}")

    prog.set_stage("saving")
    return {
        "segments": all_segments,
        "language": "multi:" + ",".join(sorted(languages_seen)) if languages_seen else "multi",
        "diarization_applied": diarization_applied,
        "recognized_speakers": recognized_speakers,
        "multilingual": True,
    }


def _format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_segments_as_text(
    segments: list[dict],
    diarization_applied: bool,
    show_language: bool = False,
) -> str:
    """
    Format segments into timestamped text output.

    With diarization:
        [00:00:00 - 00:00:12] SPEAKER_00: Hello world.

    Without diarization:
        [00:00:00 - 00:00:12] Hello world.

    With show_language=True (multilingual mode), a [lang] tag is inserted:
        [00:00:00 - 00:00:12] [es] SPEAKER_00: Hola mundo.
    """
    lines = []
    for seg in segments:
        start = _format_time(seg.get("start", 0))
        end = _format_time(seg.get("end", 0))
        text = seg.get("text", "").strip()
        if not text:
            continue

        prefix = f"[{start} - {end}]"
        if show_language and seg.get("language"):
            prefix += f" [{seg['language']}]"
        if diarization_applied and "speaker" in seg:
            lines.append(f"{prefix} {seg['speaker']}: {text}")
        else:
            lines.append(f"{prefix} {text}")

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
