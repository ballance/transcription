"""
Database models for transcription job tracking.

This module defines the SQLAlchemy ORM models for:
- TranscriptionJob: Job metadata, status, and progress tracking
- TranscriptionResult: Completed transcription output
- ErrorLog: Error tracking and dead letter queue
"""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Column, String, Integer, BigInteger, Float, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class TranscriptionJob(Base):
    """
    Tracks transcription jobs through their lifecycle.

    Status flow: pending → processing → completed/failed/cancelled
    """
    __tablename__ = 'transcription_jobs'

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Job status and priority
    status = Column(String(50), nullable=False, default='pending', index=True)
    # Status values: pending, processing, completed, failed, cancelled, retry
    priority = Column(Integer, default=0)

    # Model configuration
    model_size = Column(String(20), nullable=False)  # tiny, base, small, medium, large
    language = Column(String(10))  # ISO language code or None for auto-detect

    # File information
    original_filename = Column(String(500), nullable=False)
    file_path = Column(Text, nullable=False)
    file_size_bytes = Column(BigInteger)

    # Processing metadata
    worker_id = Column(String(100))  # Celery worker ID
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)

    # Timing information
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # Error tracking
    error_message = Column(Text)
    error_type = Column(String(100))

    # Progress tracking
    progress_percent = Column(Float, default=0.0)
    current_step = Column(String(200))

    # Relationships
    result = relationship("TranscriptionResult", back_populates="job", uselist=False, cascade="all, delete-orphan")
    errors = relationship("ErrorLog", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<TranscriptionJob(id={self.id}, status={self.status}, filename={self.original_filename})>"

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate job duration if started and completed."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class TranscriptionResult(Base):
    """
    Stores the output of completed transcription jobs.

    Includes the transcribed text, metadata, and optional segments with timestamps.
    """
    __tablename__ = 'transcription_results'

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign key to job
    job_id = Column(UUID(as_uuid=True), ForeignKey('transcription_jobs.id'), nullable=False, unique=True, index=True)

    # Transcription output
    transcription_text = Column(Text, nullable=False)
    detected_language = Column(String(10))
    duration_seconds = Column(Float)
    confidence_score = Column(Float)

    # Detailed segment data (JSON with timestamps, speakers, etc.)
    segments = Column(JSONB)  # PostgreSQL JSONB for efficient querying

    # Output file location
    output_file_path = Column(Text)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    job = relationship("TranscriptionJob", back_populates="result")

    def __repr__(self):
        return f"<TranscriptionResult(id={self.id}, job_id={self.job_id}, language={self.detected_language})>"

    @property
    def word_count(self) -> int:
        """Calculate word count of transcription."""
        return len(self.transcription_text.split()) if self.transcription_text else 0


class ErrorLog(Base):
    """
    Dead letter queue for failed jobs.

    Tracks detailed error information for debugging and potential recovery.
    """
    __tablename__ = 'error_logs'

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign key to job
    job_id = Column(UUID(as_uuid=True), ForeignKey('transcription_jobs.id'), nullable=False, index=True)

    # Error details
    error_type = Column(String(100), nullable=False)
    # Error types: OutOfMemory, CorruptAudioFile, TransientNetworkError, FileNotFound, UnknownError
    error_message = Column(Text, nullable=False)
    stack_trace = Column(Text)

    # Additional context for debugging
    context = Column(JSONB)  # Worker info, file details, retry attempts, etc.

    # Timestamp and resolution
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    resolved = Column(Boolean, default=False, index=True)
    resolved_at = Column(DateTime)
    resolved_by = Column(String(100))  # User or system that resolved the error
    resolution_notes = Column(Text)

    # Relationships
    job = relationship("TranscriptionJob", back_populates="errors")

    def __repr__(self):
        return f"<ErrorLog(id={self.id}, type={self.error_type}, resolved={self.resolved})>"


# Create indexes for common queries
# These will be generated in Alembic migrations
"""
CREATE INDEX idx_jobs_status ON transcription_jobs(status);
CREATE INDEX idx_jobs_created ON transcription_jobs(created_at);
CREATE INDEX idx_errors_unresolved ON error_logs(resolved) WHERE NOT resolved;
CREATE INDEX idx_results_job ON transcription_results(job_id);
"""
