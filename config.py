"""
Centralized configuration for transcription services.

All configuration is managed through environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Tuple


@dataclass
class TranscriptionConfig:
    """Configuration for transcription services."""

    # Model settings
    model_size: str = os.getenv("WHISPER_MODEL_SIZE", "large")
    fp16: bool = os.getenv("WHISPER_FP16", "false").lower() == "true"

    # Paths
    video_folder: str = os.getenv("TRANSCRIBE_VIDEO_FOLDER", os.path.expanduser("~/Movies"))
    audio_folder: str = os.getenv("TRANSCRIBE_AUDIO_FOLDER", "./work")
    work_folder: str = os.getenv("TRANSCRIBE_WORK_FOLDER", "./work")
    output_folder: str = os.getenv("TRANSCRIBE_OUTPUT_FOLDER", "./transcribed")

    # Processing settings
    scan_interval: int = int(os.getenv("SCAN_INTERVAL", "30"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))

    # File filtering
    skip_files_before_date: str = os.getenv("SKIP_FILES_BEFORE_DATE", "2025-12-01")

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

    # Supported formats
    supported_audio_formats: Tuple[str, ...] = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")
    supported_video_formats: Tuple[str, ...] = (".mov", ".mp4", ".m4v", ".mkv")

    def __post_init__(self):
        """Validate configuration after initialization."""
        valid_models = ["tiny", "base", "small", "medium", "large"]
        if self.model_size not in valid_models:
            raise ValueError(
                f"Invalid model size: {self.model_size}. "
                f"Must be one of: {', '.join(valid_models)}"
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


# Global configuration instance
config = TranscriptionConfig()
