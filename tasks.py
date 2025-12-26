"""
Celery tasks for async transcription processing.

Tasks:
- transcribe_audio_task: Main transcription task
- convert_video_task: Video to audio conversion
- dlq_handler_task: Dead letter queue handler
- repair_and_retry_task: Audio repair and retry
"""

import logging
import os
import subprocess
import time
from datetime import datetime
from typing import Optional

from celery import Task

from celery_app import celery_app
from config import config
from database import get_db_session
from models import TranscriptionJob, TranscriptionResult, ErrorLog
from model_pool import acquire_model

logger = logging.getLogger(__name__)


class TranscriptionTask(Task):
    """
    Base task class with custom error handling.

    Provides common functionality for all transcription tasks.
    """

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails."""
        logger.error(
            f"Task {task_id} failed: {exc}",
            extra={'task_id': task_id, 'exception': str(exc)},
            exc_info=einfo
        )

    def on_success(self, retval, task_id, args, kwargs):
        """Called when task succeeds."""
        logger.info(
            f"Task {task_id} succeeded",
            extra={'task_id': task_id, 'result': retval}
        )


@celery_app.task(
    base=TranscriptionTask,
    bind=True,
    max_retries=5,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,  # Exponential backoff
    retry_backoff_max=600,  # Max 10 minutes
    retry_jitter=True  # Add randomness to prevent thundering herd
)
def transcribe_audio_task(self, file_path: str, model_size: str, language: Optional[str], job_id: str):
    """
    Transcribe audio file to text.

    This is the main transcription task that:
    1. Loads the Whisper model
    2. Transcribes the audio
    3. Saves the result to database
    4. Handles errors with retry logic

    Args:
        file_path: Path to audio file
        model_size: Whisper model size (tiny, base, small, medium, large)
        language: Language code or None for auto-detect
        job_id: UUID of the TranscriptionJob record

    Returns:
        dict: Status and result information

    Raises:
        Retry: If transcription fails with recoverable error
    """
    logger.info(f"Starting transcription task for job {job_id}")

    with get_db_session() as db:
        # Get job record
        job = db.query(TranscriptionJob).filter_by(id=job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found in database")
            raise ValueError(f"Job {job_id} not found")

        try:
            # Update job status
            job.status = "processing"
            job.started_at = datetime.utcnow()
            job.worker_id = self.request.id
            job.current_step = "Acquiring Whisper model from pool"
            job.progress_percent = 10.0
            db.commit()

            # Acquire model from pool (with automatic loading if needed)
            logger.info(f"Acquiring Whisper model from pool: {model_size}")
            start_time = time.time()

            with acquire_model(model_size) as model:
                acquire_time = time.time() - start_time
                logger.info(f"Model acquired in {acquire_time:.2f}s")

                # Update progress
                job.current_step = "Transcribing audio"
                job.progress_percent = 30.0
                db.commit()

                # Transcribe
                logger.info(f"Transcribing file: {file_path}")
                transcribe_start = time.time()

                result = model.transcribe(
                    file_path,
                    verbose=False,
                    language=language if language and language != "auto" else None,
                    fp16=config.fp16
                )

                transcribe_time = time.time() - transcribe_start
                logger.info(f"Transcription completed in {transcribe_time:.2f}s")
            # Model automatically released back to pool here

            # Update progress
            job.current_step = "Saving results"
            job.progress_percent = 90.0
            db.commit()

            # Determine output file path
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            output_file = os.path.join(config.output_folder, f"{base_name}.txt")

            # Create output directory if needed
            os.makedirs(config.output_folder, exist_ok=True)

            # Write transcription to file with metadata
            with open(output_file, "w", encoding="utf-8") as f:
                # Write metadata header
                f.write(f"# Transcription Metadata\n")
                f.write(f"# File: {job.original_filename}\n")
                f.write(f"# Size: {job.file_size_bytes / (1024 * 1024):.1f}MB\n")
                f.write(f"# Model: {model_size}\n")
                f.write(f"# Transcribed: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
                f.write(f"# Duration: {result.get('duration', 'unknown')} seconds\n")
                f.write(f"# Language: {result.get('language', language or 'auto')}\n\n")

                # Write transcription text
                f.write(result["text"])

            logger.info(f"Transcription saved to: {output_file}")

            # Save result to database
            transcription_result = TranscriptionResult(
                job_id=job_id,
                transcription_text=result["text"],
                detected_language=result.get("language", language),
                duration_seconds=result.get("duration"),
                segments=result.get("segments", []),
                output_file_path=output_file
            )
            db.add(transcription_result)

            # Mark job as completed
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            job.progress_percent = 100.0
            job.current_step = "Done"
            db.commit()

            logger.info(f"Job {job_id} completed successfully")

            return {
                "status": "completed",
                "job_id": str(job_id),
                "transcription_length": len(result["text"]),
                "language": result.get("language"),
                "duration": transcribe_time
            }

        except RuntimeError as e:
            error_msg = str(e)
            logger.error(f"RuntimeError during transcription: {error_msg}")

            # Handle specific error types
            if "cannot reshape tensor" in error_msg or "0 elements" in error_msg:
                # Corrupt audio file - attempt repair
                logger.warning(f"Corrupt audio detected for job {job_id}, will attempt repair")

                job.current_step = "Audio file appears corrupt, attempting repair"
                job.retry_count += 1
                db.commit()

                if job.retry_count < job.max_retries:
                    # Schedule repair and retry
                    repair_and_retry_task.apply_async(
                        kwargs={'job_id': str(job_id), 'file_path': file_path},
                        countdown=30  # Wait 30 seconds
                    )
                    raise self.retry(exc=e, countdown=60)
                else:
                    # Max retries exceeded
                    job.status = "failed"
                    job.error_type = "CorruptAudioFile"
                    job.error_message = error_msg
                    job.completed_at = datetime.utcnow()
                    db.commit()
                    raise

            else:
                # Other RuntimeError - retry with backoff
                job.retry_count += 1
                db.commit()

                if job.retry_count < job.max_retries:
                    raise self.retry(exc=e)
                else:
                    job.status = "failed"
                    job.error_type = "RuntimeError"
                    job.error_message = error_msg
                    job.completed_at = datetime.utcnow()
                    db.commit()
                    raise

        except MemoryError as e:
            logger.error(f"MemoryError during transcription: {e}")

            job.retry_count += 1
            db.commit()

            # Try to fall back to smaller model
            size_hierarchy = ["tiny", "base", "small", "medium", "large"]
            try:
                current_idx = size_hierarchy.index(model_size)
                if current_idx > 0 and job.retry_count < job.max_retries:
                    smaller_size = size_hierarchy[current_idx - 1]
                    logger.info(f"Falling back from {model_size} to {smaller_size}")

                    job.status = "retry"
                    job.error_message = f"OOM with {model_size}, retrying with {smaller_size}"
                    job.model_size = smaller_size
                    db.commit()

                    # Retry with smaller model
                    raise self.retry(
                        exc=e,
                        countdown=60,
                        args=[file_path, smaller_size, language, job_id]
                    )
            except (ValueError, IndexError):
                pass

            # No fallback available or max retries exceeded
            job.status = "failed"
            job.error_type = "MemoryError"
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            db.commit()
            raise

        except Exception as e:
            logger.error(f"Unexpected error during transcription: {e}", exc_info=True)

            job.status = "failed"
            job.error_type = type(e).__name__
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            db.commit()
            raise


@celery_app.task(base=TranscriptionTask, bind=True, max_retries=3)
def convert_video_task(self, input_path: str, job_id: str):
    """
    Convert video file to MP3 audio.

    Args:
        input_path: Path to video file
        job_id: UUID of the TranscriptionJob record

    Returns:
        str: Path to converted MP3 file
    """
    logger.info(f"Converting video to audio: {input_path}")

    with get_db_session() as db:
        job = db.query(TranscriptionJob).filter_by(id=job_id).first()

        try:
            job.current_step = "Converting video to audio"
            job.progress_percent = 20.0
            db.commit()

            # Determine output path
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            output_path = os.path.join(config.work_folder, f"{base_name}.mp3")

            # Check if already converted
            if os.path.exists(output_path):
                logger.info(f"Converted file already exists: {output_path}")
                return output_path

            # Convert with ffmpeg
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",  # Overwrite output
                    "-i", input_path,
                    "-acodec", "libmp3lame",
                    "-ar", "16000",  # Sample rate
                    "-ac", "1",  # Mono
                    "-ab", "64k",  # Bit rate
                    output_path
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=600  # 10 minute timeout
            )

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Video converted successfully: {output_path}")
                return output_path
            else:
                raise RuntimeError("Conversion produced empty file")

        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg conversion failed: {e.stderr.decode()}")
            job.error_message = f"Video conversion failed: {e.stderr.decode()}"
            db.commit()
            raise

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg conversion timed out")
            job.error_message = "Video conversion timed out (>10 minutes)"
            db.commit()
            raise


@celery_app.task(base=TranscriptionTask)
def dlq_handler_task(task_id: str, exception: str, traceback: str, args: list, kwargs: dict):
    """
    Handle tasks that end up in the Dead Letter Queue.

    Logs detailed error information and attempts automatic recovery for known issues.

    Args:
        task_id: Failed Celery task ID
        exception: Exception message
        traceback: Full traceback string
        args: Original task arguments
        kwargs: Original task keyword arguments
    """
    logger.error(
        f"DLQ Handler processing failed task",
        extra={
            'task_id': task_id,
            'exception': exception,
            'args': args,
            'kwargs': kwargs
        }
    )

    # Extract job_id if present
    job_id = kwargs.get('job_id')
    if not job_id:
        logger.warning("No job_id in DLQ task, cannot update database")
        return

    with get_db_session() as db:
        job = db.query(TranscriptionJob).filter_by(id=job_id).first()
        if not job:
            logger.warning(f"Job {job_id} not found in database")
            return

        # Classify error type
        error_category = classify_error(exception)

        # Create error log
        error_log = ErrorLog(
            job_id=job_id,
            error_type=error_category,
            error_message=exception,
            stack_trace=traceback,
            context={
                'task_id': task_id,
                'args': args,
                'kwargs': kwargs,
                'worker_id': job.worker_id
            }
        )
        db.add(error_log)

        # Update job if not already marked as failed
        if job.status != "failed":
            job.status = "failed"
            job.error_type = error_category
            job.error_message = exception[:500]  # Truncate long messages
            job.completed_at = datetime.utcnow()

        db.commit()

        logger.info(f"DLQ processed for job {job_id}, error type: {error_category}")


@celery_app.task(base=TranscriptionTask, bind=True)
def repair_and_retry_task(self, job_id: str, file_path: str):
    """
    Attempt to repair corrupted audio file and retry transcription.

    Args:
        job_id: UUID of the TranscriptionJob record
        file_path: Path to corrupted audio file
    """
    logger.info(f"Attempting to repair audio for job {job_id}")

    with get_db_session() as db:
        job = db.query(TranscriptionJob).filter_by(id=job_id).first()

        try:
            # Generate repaired file path
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            repaired_file = os.path.join(config.work_folder, f"{base_name}_repaired.mp3")

            if os.path.exists(repaired_file):
                logger.info(f"Repaired file already exists: {repaired_file}")
            else:
                # Repair with ffmpeg
                logger.info(f"Repairing audio file: {file_path}")

                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i", file_path,
                        "-acodec", "libmp3lame",
                        "-ar", "16000",
                        "-ac", "1",
                        "-ab", "64k",
                        repaired_file
                    ],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60
                )

                if not os.path.exists(repaired_file) or os.path.getsize(repaired_file) == 0:
                    raise RuntimeError("Repair produced empty file")

            logger.info(f"Audio repaired successfully: {repaired_file}")

            # Schedule transcription with repaired file
            transcribe_audio_task.apply_async(
                args=[repaired_file, job.model_size, None, str(job_id)],
                queue='transcription.retry',
                countdown=10
            )

            job.current_step = "Retrying with repaired audio"
            db.commit()

        except Exception as e:
            logger.error(f"Audio repair failed: {e}")
            job.error_message = f"Audio repair failed: {str(e)}"
            db.commit()
            raise


def classify_error(exception_str: str) -> str:
    """
    Classify error into categories for appropriate handling.

    Args:
        exception_str: Exception message

    Returns:
        Error category string
    """
    exception_lower = exception_str.lower()

    if "out of memory" in exception_lower or "oom" in exception_lower:
        return "OutOfMemory"
    elif "cannot reshape tensor" in exception_lower or "0 elements" in exception_lower:
        return "CorruptAudioFile"
    elif "timeout" in exception_lower or "connection" in exception_lower:
        return "TransientNetworkError"
    elif "file not found" in exception_lower or "no such file" in exception_lower:
        return "FileNotFound"
    elif "permission denied" in exception_lower:
        return "PermissionError"
    else:
        return "UnknownError"
