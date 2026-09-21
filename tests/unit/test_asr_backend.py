"""
Unit tests for the pluggable ASR backend (Phase 3: Apple GPU via mlx-whisper).

Covers the model_size → MLX repo mapping, the mlx → whisperx-shaped result
adapter, backend dispatch, and graceful fallback to WhisperX on mlx failure.
"""
import sys
from unittest.mock import MagicMock, patch

import whisperx_pipeline as wp


class TestMlxRepo:
    def test_known_size_maps_to_mlx_repo(self):
        with patch.object(wp.config, "model_size", "large-v3"), \
             patch.object(wp.config, "mlx_whisper_repo", ""):
            assert wp._mlx_repo() == "mlx-community/whisper-large-v3-mlx"

    def test_unknown_size_uses_conventional_name(self):
        with patch.object(wp.config, "model_size", "weird-v9"), \
             patch.object(wp.config, "mlx_whisper_repo", ""):
            assert wp._mlx_repo() == "mlx-community/whisper-weird-v9-mlx"

    def test_explicit_override_wins(self):
        with patch.object(wp.config, "model_size", "large-v3"), \
             patch.object(wp.config, "mlx_whisper_repo", "me/custom-mlx"):
            assert wp._mlx_repo() == "me/custom-mlx"


class TestMlxTranscribe:
    def test_returns_whisperx_shaped_result(self):
        """mlx output must expose start/end/text segments for whisperx.align."""
        fake = MagicMock()
        fake.transcribe.return_value = {
            "text": "hi there",
            "language": "en",
            "segments": [{"start": 0.0, "end": 1.0, "text": "hi there", "avg_logprob": -0.1}],
        }
        with patch.dict(sys.modules, {"mlx_whisper": fake}), \
             patch.object(wp.config, "model_size", "large-v3"), \
             patch.object(wp.config, "mlx_whisper_repo", ""):
            out = wp._mlx_transcribe([0.0, 0.1, 0.2], "en")

        assert out["language"] == "en"
        seg = out["segments"][0]
        assert {"start", "end", "text"} <= seg.keys()
        # mlx received the audio array and the resolved repo
        _, kwargs = fake.transcribe.call_args
        assert kwargs["path_or_hf_repo"] == "mlx-community/whisper-large-v3-mlx"
        assert kwargs["language"] == "en"

    def test_auto_language_passed_as_none(self):
        fake = MagicMock()
        fake.transcribe.return_value = {"language": "es", "segments": []}
        with patch.dict(sys.modules, {"mlx_whisper": fake}), \
             patch.object(wp.config, "mlx_whisper_repo", "r"):
            wp._mlx_transcribe([0.0], "auto")
        assert fake.transcribe.call_args.kwargs["language"] is None


class TestRunAsrDispatch:
    def test_mlx_backend_used_when_resolved(self):
        with patch.object(type(wp.config), "resolved_asr_backend", "mlx"), \
             patch.object(wp, "_mlx_transcribe", return_value={"language": "en", "segments": [{"text": "x"}]}) as mlx, \
             patch.object(wp, "load_transcription_model") as load:
            lang, segs = wp._run_asr([0.0], "en")
        assert (lang, segs) == ("en", [{"text": "x"}])
        mlx.assert_called_once()
        load.assert_not_called()  # whisperx model never loaded on the mlx path

    def test_falls_back_to_whisperx_on_mlx_failure(self):
        model = MagicMock()
        model.transcribe.return_value = {"language": "en", "segments": [{"text": "fallback"}]}
        with patch.object(type(wp.config), "resolved_asr_backend", "mlx"), \
             patch.object(wp, "_mlx_transcribe", side_effect=RuntimeError("no metal")), \
             patch.object(wp, "load_transcription_model", return_value=model):
            lang, segs = wp._run_asr([0.0], "en")
        assert segs == [{"text": "fallback"}]
        model.transcribe.assert_called_once()

    def test_whisperx_backend_skips_mlx(self):
        model = MagicMock()
        model.transcribe.return_value = {"language": "en", "segments": []}
        with patch.object(type(wp.config), "resolved_asr_backend", "whisperx"), \
             patch.object(wp, "_mlx_transcribe") as mlx, \
             patch.object(wp, "load_transcription_model", return_value=model):
            wp._run_asr([0.0], "en")
        mlx.assert_not_called()
