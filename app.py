from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Query
import os
import tempfile
import logging
from uuid import uuid4
from datetime import datetime
from sqlalchemy.orm import Session

from config import config
from database import get_db, check_db_connection
from models import TranscriptionJob, TranscriptionResult, ErrorLog
from tasks import transcribe_audio_task
from model_pool import get_pool_stats

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize the FastAPI app
logger.info("Initializing FastAPI application")
app = FastAPI(
    title="Transcription Service API",
    description="Async audio/video transcription service powered by OpenAI Whisper",
    version="2.0.0"
)
logger.info("FastAPI app initialized")

# Check database connection on startup
@app.on_event("startup")
async def startup_event():
    """Check database connectivity on startup."""
    if check_db_connection():
        logger.info("Database connection verified")
    else:
        logger.error("Database connection failed - some features may not work") 

@app.get("/")
async def root():
    """Root endpoint for basic connectivity check"""
    return {"status": "healthy", "service": "owl-web"}

@app.get("/health")
async def health_check():
    """Basic health check endpoint"""
    db_ok = check_db_connection()
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "service": "transcription-api",
        "version": "2.0.0"
    }

@app.post("/transcribe/", status_code=202)
async def transcribe_audio(
    file: UploadFile = File(...),
    model_size: str = Query(None, description="Model size override (tiny, base, small, medium, large)"),
    language: str = Query(None, description="Language code (e.g., 'en', 'es') or 'auto' for detection"),
    db: Session = Depends(get_db)
):
    """
    Submit an audio/video file for async transcription.

    Returns immediately with a job_id. Use GET /transcribe/{job_id} to check status.

    Args:
        file: Audio or video file to transcribe
        model_size: Override default model size
        language: Language code or 'auto'

    Returns:
        202 Accepted with job_id
    """
    try:
        # Read file contents
        file_content = await file.read()
        file_size = len(file_content)
        logger.info(f"Received upload: {file.filename} ({file_size} bytes)")

        # Validate file size
        if file_size > config.max_upload_size_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {config.max_upload_size_mb}MB"
            )

        # Validate content type
        if not (file.content_type and
                (file.content_type.startswith("audio/") or
                 file.content_type.startswith("video/") or
                 file.content_type == "application/octet-stream")):
            raise HTTPException(
                status_code=400,
                detail="Uploaded file must be an audio or video file"
            )

        # Generate job ID
        job_id = uuid4()

        # Save file to persistent location
        upload_dir = os.path.join(config.work_folder, "uploads", str(job_id))
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, file.filename)

        with open(file_path, "wb") as f:
            f.write(file_content)

        logger.info(f"File saved to: {file_path}")

        # Create job record
        job = TranscriptionJob(
            id=job_id,
            status="pending",
            original_filename=file.filename,
            file_path=file_path,
            file_size_bytes=file_size,
            model_size=model_size or config.model_size,
            language=language,
            priority=9  # High priority for API requests
        )
        db.add(job)
        db.commit()

        # Submit to Celery queue
        transcribe_audio_task.apply_async(
            args=[file_path, job.model_size, language, str(job_id)],
            queue='transcription.high',
            priority=9
        )

        logger.info(f"Job {job_id} submitted to queue")

        return {
            "job_id": str(job_id),
            "status": "pending",
            "message": "Transcription job submitted successfully. Use GET /transcribe/{job_id} to check status."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting transcription job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@app.get("/transcribe/{job_id}")
async def get_transcription_status(job_id: str, db: Session = Depends(get_db)):
    """
    Get status and result of a transcription job.

    Args:
        job_id: UUID of the transcription job

    Returns:
        Job status and transcription result if completed
    """
    job = db.query(TranscriptionJob).filter_by(id=job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response = {
        "job_id": str(job.id),
        "status": job.status,
        "progress": job.progress_percent,
        "current_step": job.current_step,
        "created_at": job.created_at.isoformat(),
        "model_size": job.model_size
    }

    if job.started_at:
        response["started_at"] = job.started_at.isoformat()

    if job.status == "completed":
        result = db.query(TranscriptionResult).filter_by(job_id=job_id).first()
        if result:
            response["transcription"] = result.transcription_text
            response["language"] = result.detected_language
            response["duration"] = result.duration_seconds
            response["word_count"] = result.word_count
            response["completed_at"] = job.completed_at.isoformat()

    elif job.status == "failed":
        response["error_type"] = job.error_type
        response["error_message"] = job.error_message
        response["completed_at"] = job.completed_at.isoformat() if job.completed_at else None

    return response


@app.delete("/transcribe/{job_id}")
async def cancel_transcription(job_id: str, db: Session = Depends(get_db)):
    """
    Cancel a pending or running transcription job.

    Args:
        job_id: UUID of the transcription job

    Returns:
        Cancellation confirmation
    """
    job = db.query(TranscriptionJob).filter_by(id=job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ["completed", "failed", "cancelled"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status: {job.status}"
        )

    # Revoke Celery task if it has a worker_id
    if job.worker_id:
        from celery_app import celery_app
        celery_app.control.revoke(job.worker_id, terminate=True)

    # Update job status
    job.status = "cancelled"
    job.completed_at = datetime.utcnow()
    db.commit()

    return {
        "job_id": str(job_id),
        "status": "cancelled",
        "message": "Job cancelled successfully"
    }


@app.get("/jobs/")
async def list_jobs(
    status: str = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    List transcription jobs with optional filtering.

    Args:
        status: Filter by job status (pending, processing, completed, failed)
        limit: Maximum number of jobs to return (1-100)

    Returns:
        List of jobs
    """
    query = db.query(TranscriptionJob)

    if status:
        query = query.filter_by(status=status)

    jobs = query.order_by(TranscriptionJob.created_at.desc()).limit(limit).all()

    return {
        "total": len(jobs),
        "jobs": [
            {
                "job_id": str(job.id),
                "filename": job.original_filename,
                "status": job.status,
                "progress": job.progress_percent,
                "model_size": job.model_size,
                "created_at": job.created_at.isoformat(),
            }
            for job in jobs
        ]
    }


@app.get("/admin/health")
async def admin_health_check(db: Session = Depends(get_db)):
    """
    Comprehensive health check with system metrics.

    Returns:
        Detailed health information including queue depths, error rates, pool stats
    """
    from datetime import timedelta

    # Database health
    db_ok = check_db_connection()

    # Recent error rate (last hour)
    recent_cutoff = datetime.utcnow() - timedelta(hours=1)
    recent_errors = db.query(ErrorLog).filter(
        ErrorLog.created_at >= recent_cutoff,
        ErrorLog.resolved == False
    ).count()

    total_recent = db.query(TranscriptionJob).filter(
        TranscriptionJob.created_at >= recent_cutoff
    ).count()

    error_rate = (recent_errors / total_recent) if total_recent > 0 else 0

    # Model pool stats
    pool_stats = get_pool_stats()

    # Queue depths (active jobs)
    pending_jobs = db.query(TranscriptionJob).filter_by(status="pending").count()
    processing_jobs = db.query(TranscriptionJob).filter_by(status="processing").count()

    return {
        "status": "healthy" if db_ok and error_rate < 0.1 else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "queues": {
            "pending": pending_jobs,
            "processing": processing_jobs
        },
        "model_pool": pool_stats,
        "error_rate_1h": f"{error_rate:.2%}",
        "unresolved_errors": recent_errors
    }


@app.get("/admin/errors")
async def get_recent_errors(
    limit: int = Query(50, ge=1, le=100),
    resolved: bool = Query(False),
    db: Session = Depends(get_db)
):
    """
    Get recent errors from Dead Letter Queue.

    Args:
        limit: Maximum errors to return
        resolved: Include resolved errors

    Returns:
        List of error logs
    """
    query = db.query(ErrorLog)

    if not resolved:
        query = query.filter_by(resolved=False)

    errors = query.order_by(ErrorLog.created_at.desc()).limit(limit).all()

    return {
        "total": len(errors),
        "errors": [
            {
                "id": str(error.id),
                "job_id": str(error.job_id),
                "type": error.error_type,
                "message": error.error_message,
                "created_at": error.created_at.isoformat(),
                "resolved": error.resolved
            }
            for error in errors
        ]
    }