"""
Centralized configuration for transcription services.

All configuration is managed through environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

import torch


@dataclass
class TranscriptionConfig:
    """Configuration for transcription services."""

    # Model settings
    model_size: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL_SIZE", "large-v3"))
    fp16: bool = os.getenv("WHISPER_FP16", "false").lower() == "true"
    device: str = field(default_factory=lambda: os.getenv("WHISPER_DEVICE", "auto"))
    compute_type: str = os.getenv("WHISPER_COMPUTE_TYPE", "auto")
    batch_size: int = int(os.getenv("WHISPERX_BATCH_SIZE", "0"))  # 0 = auto-select

    # Diarization settings
    enable_diarization: bool = os.getenv("WHISPER_DIARIZATION", "false").lower() == "true"
    hf_token: str = os.getenv("HF_TOKEN", "")
    min_speakers: Optional[int] = field(
        default_factory=lambda: int(v) if (v := os.getenv("DIARIZATION_MIN_SPEAKERS")) else None
    )
    max_speakers: Optional[int] = field(
        default_factory=lambda: int(v) if (v := os.getenv("DIARIZATION_MAX_SPEAKERS")) else None
    )

    # Speaker recognition settings
    speaker_profiles_path: str = os.getenv("SPEAKER_PROFILES_PATH", "./speaker_profiles.json")
    speaker_recognition_threshold: float = float(os.getenv("SPEAKER_RECOGNITION_THRESHOLD", "0.55"))
    enable_speaker_recognition: bool = os.getenv("SPEAKER_RECOGNITION", "false").lower() == "true"

    # Paths
    video_folder: str = os.getenv("TRANSCRIBE_VIDEO_FOLDER", os.path.expanduser("~/Movies"))
    audio_folder: str = os.getenv("TRANSCRIBE_AUDIO_FOLDER", "./work")
    work_folder: str = os.getenv("TRANSCRIBE_WORK_FOLDER", "./work")
    output_folder: str = os.getenv("TRANSCRIBE_OUTPUT_FOLDER", "./transcribed")

    # Processing settings
    scan_interval: int = int(os.getenv("SCAN_INTERVAL", "30"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    stability_window: int = int(os.getenv("FILE_STABILITY_WINDOW", "60"))  # seconds of no changes before processing

    # File filtering
    skip_files_before_date: str = os.getenv("SKIP_FILES_BEFORE_DATE", "2025-12-01")

    # Auto-rename transcripts with content summary
    auto_rename: bool = os.getenv("TRANSCRIBE_AUTO_RENAME", "true").lower() == "true"

    # Prioritize recent files (newest first) when processing
    prioritize_recent: bool = os.getenv("PRIORITIZE_RECENT", "true").lower() == "true"

    # API settings
    max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "500"))

    # Async processing settings
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    celery_broker_url: str = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    celery_result_backend: str = os.getenv("CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    database_url: str = os.getenv("DATABASE_URL", "postgresql://transcription:transcription@localhost/transcription")

    # Worker settings
    celery_worker_concurrency: int = int(os.getenv("CELERY_CONCURRENCY", "4"))
    celery_task_timeout: int = int(os.getenv("CELERY_TASK_TIMEOUT", "3600"))  # 1 hour default

    # Model pool settings
    model_pool_size: int = int(os.getenv("MODEL_POOL_SIZE", "2"))
    model_pool_max_size: int = int(os.getenv("MODEL_POOL_MAX_SIZE", "4"))

    # Security settings
    force_https: bool = os.getenv("FORCE_HTTPS", "false").lower() == "true"
    trusted_hosts: str = os.getenv("TRUSTED_HOSTS", "")  # Comma-separated list

    # Supported formats
    supported_audio_formats: Tuple[str, ...] = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")
    supported_video_formats: Tuple[str, ...] = (".mov", ".mp4", ".m4v", ".mkv")

    def __post_init__(self):
        """Validate configuration after initialization."""
        valid_models = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]
        if self.model_size not in valid_models:
            raise ValueError(
                f"Invalid model size: {self.model_size}. "
                f"Must be one of: {', '.join(valid_models)}"
            )

        if self.enable_diarization and not self.hf_token:
            raise ValueError(
                "Diarization requires a HuggingFace token. "
                "Set the HF_TOKEN environment variable with a token that has "
                "accepted the pyannote/speaker-diarization-3.1 user agreement at "
                "https://huggingface.co/pyannote/speaker-diarization-3.1"
            )

        if self.enable_speaker_recognition and not self.enable_diarization:
            raise ValueError(
                "Speaker recognition requires diarization to be enabled. "
                "Set WHISPER_DIARIZATION=true along with SPEAKER_RECOGNITION=true"
            )

        if not 0 <= self.speaker_recognition_threshold <= 1:
            raise ValueError(
                f"Speaker recognition threshold must be between 0 and 1, "
                f"got {self.speaker_recognition_threshold}"
            )

        # Validate date format
        try:
            datetime.strptime(self.skip_files_before_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                f"Invalid date format: {self.skip_files_before_date}. "
                f"Must be YYYY-MM-DD"
            )

    @property
    def cutoff_datetime(self) -> datetime:
        """Get the cutoff datetime for file filtering."""
        year, month, day = self.skip_files_before_date.split("-")
        return datetime(int(year), int(month), int(day))

    @property
    def max_upload_size_bytes(self) -> int:
        """Get max upload size in bytes."""
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def compute_device(self) -> str:
        """Get the resolved compute device (mps, cuda, or cpu)."""
        if self.device != "auto":
            return self.device
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    @property
    def whisperx_device(self) -> str:
        """Get the compute device for WhisperX (no MPS support — CTranslate2 limitation)."""
        device = self.compute_device
        if device == "mps":
            return "cpu"
        return device

    @property
    def resolved_compute_type(self) -> str:
        """Map config to CTranslate2 compute_type string."""
        if self.compute_type != "auto":
            return self.compute_type
        device = self.whisperx_device
        if device == "cuda":
            return "float16" if self.fp16 else "int8_float16"
        return "int8"

    @property
    def resolved_batch_size(self) -> int:
        """Get batch size, auto-selecting based on device if not explicitly set."""
        if self.batch_size > 0:
            return self.batch_size
        return 16 if self.whisperx_device == "cuda" else 4


# Global configuration instance
config = TranscriptionConfig()
