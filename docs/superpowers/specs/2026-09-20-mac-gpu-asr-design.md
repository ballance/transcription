# Phase 3: GPU ASR on Apple Silicon (mlx-whisper)

**Date:** 2026-09-20
**Status:** Approved design

## Problem

The transcription (ASR) stage runs on CPU even on Apple Silicon. WhisperX uses the
CTranslate2 backend, which has no Metal/MPS support, so `config.whisperx_device`
deliberately forces the ASR stage to CPU (`config.py:149-154`). Alignment and
diarization already run on the GPU via MPS. The ASR stage is the slowest part of
the pipeline and the remaining CPU bottleneck.

## Goal

Move the ASR stage onto the Apple GPU by introducing a Metal-capable ASR engine
(`mlx-whisper`), while keeping the existing `whisperx.align` → diarize →
speaker-recognition pipeline unchanged. Off-Mac (CUDA/CPU) behavior must not
regress.

## Approach

Add a selectable ASR backend. Only Stage 1 (transcribe) changes; the rest of the
pipeline consumes whisperx-shaped segments and never knows which engine produced
them.

### Config (`config.py`)

- New field `asr_backend: str` from env `ASR_BACKEND`, default `"auto"`.
  Valid values: `auto`, `mlx`, `whisperx`.
- Resolution: `auto` → `mlx` when MPS is available, else `whisperx`.
  CUDA and CPU boxes resolve to `whisperx` — unchanged.
- Validate `asr_backend` in `__post_init__` alongside the existing checks.

### Dependency

- `mlx-whisper` is Apple-Silicon-only. Add to `requirements.txt` with a platform
  marker (e.g. `mlx-whisper; sys_platform == 'darwin' and platform_machine == 'arm64'`).
- Import it lazily inside the mlx code path, never at module top level, so
  non-Mac installs are unaffected.

### Integration (`whisperx_pipeline.py`)

- New helper `_mlx_transcribe(audio, language) -> dict` returning
  `{"segments": [...], "language": str}` where each segment has `start`, `end`,
  `text` keys — the exact shape `whisperx.align()` already consumes.
- `transcribe()` and `transcribe_multilingual()` dispatch Stage 1 on
  `config.asr_backend`:
  - `whisperx` → existing `model.transcribe(...)` (unchanged).
  - `mlx` → `_mlx_transcribe(...)`.
- Both functions already hold the `whisperx.load_audio()` numpy array. Pass that
  same array to mlx (no second decode) and to `whisperx.align()`.
- Model mapping: a small dict from `config.model_size` to the MLX HF repo
  (e.g. `large-v3` → `mlx-community/whisper-large-v3-mlx`). Exact repo names
  verified during implementation, not assumed.
- `batch_size` applies only to the whisperx backend (mlx chunks internally).
  Document this; do not silently ignore it.

### Fallback (graceful degradation)

If the mlx import or transcription fails, log a warning and fall back to the
existing WhisperX CPU path, consistent with the pipeline's existing
degrade-gracefully pattern (`_with_mps_fallback`, alignment/diarization
try/except).

## Testing

- One runnable self-check: a sample mlx-style result dict adapts to the
  `whisperx.align` input contract (correct segment keys survive the adapter).
- Manual end-to-end on a short clip: confirm segments, alignment, and diarization
  still produce correct timestamped/speaker-labeled output via the mlx backend.

## Out of scope (YAGNI)

- whisper.cpp / GGUF backend.
- Streaming transcription.
- Changing the align/diarize device selection.
- Any change to the Celery / queue / worker path.

## Verify-during-implementation (do not assume)

- Exact `mlx-community/*` repo names per model size.
- That `mlx_whisper.transcribe` accepts a numpy array (not only a file path);
  if path-only, pass the audio path and let mlx decode.
