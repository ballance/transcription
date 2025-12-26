from fastapi import FastAPI, UploadFile, File, HTTPException
import whisper
import os
import tempfile
import logging
from config import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize the FastAPI app
logger.info("Initializing FastAPI application")
app = FastAPI()
logger.info("FastAPI app initialized")

# Load the Whisper model using configuration
logger.info(f"Loading Whisper model: {config.model_size}")
model = whisper.load_model(config.model_size)
logger.info(f"Whisper model loaded: {config.model_size}") 

@app.get("/")
async def root():
    """Root endpoint for basic connectivity check"""
    return {"status": "healthy", "service": "owl-web"}

@app.get("/health")
async def health_check():
    """Health check endpoint for ECS/ALB"""
    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "service": "owl-web"
    }

@app.post("/transcribe/")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Endpoint to transcribe an audio file to text.
    Accepts an uploaded audio file and returns the transcription.
    """
    temp_file = None

    try:
        # Read file contents to get its size
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
            logger.warning(f"Invalid content type: {file.content_type}")
            raise HTTPException(
                status_code=400,
                detail="Uploaded file must be an audio or video file"
            )

        # Create secure temporary file
        with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
            temp_file = tmp.name
            tmp.write(file_content)

        logger.info(f"Saved to temp file: {temp_file}")

        # Transcribe the audio file
        logger.info(f"Starting transcription with model: {config.model_size}")
        result = model.transcribe(temp_file, verbose=False)

        logger.info("Transcription completed successfully")

        # Return the transcription text
        return {
            "transcription": result["text"],
            "language": result.get("language", "unknown"),
            "model": config.model_size
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during transcription: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing the file: {str(e)}"
        )
    finally:
        # Always clean up the temporary file
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
                logger.debug(f"Cleaned up temp file: {temp_file}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to clean up temp file: {cleanup_error}")