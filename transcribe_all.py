import os
import time
import whisper
import logging
from datetime import datetime
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('transcription.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration with environment variable support
INPUT_FOLDER = os.getenv("TRANSCRIBE_INPUT_FOLDER", "./work")
OUTPUT_FOLDER = os.getenv("TRANSCRIBE_OUTPUT_FOLDER", "./transcribed")
MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "large")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "30"))
SUPPORTED_FORMATS = (".m4v", ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")

logger.info(f"Initializing transcription service with model: {MODEL_SIZE}")
logger.info(f"Input folder: {INPUT_FOLDER}, Output folder: {OUTPUT_FOLDER}")

# Load the pre-trained Whisper model
try:
    model = whisper.load_model(MODEL_SIZE)
    logger.info(f"Successfully loaded Whisper model: {MODEL_SIZE}")
except Exception as e:
    logger.error(f"Failed to load Whisper model '{MODEL_SIZE}': {e}")
    raise

def get_file_info(file_path):
    """Get file size and basic info for logging."""
    try:
        file_size = os.path.getsize(file_path)
        size_mb = file_size / (1024 * 1024)
        return f"{size_mb:.1f}MB"
    except Exception:
        return "unknown size"

def transcribe_file(input_file):
    """Transcribe a single audio file if it has not yet been processed."""
    start_time = datetime.now()
    
    # Get the base file name without extension.
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    # Define the output file path with the same naming convention but .txt extension.
    output_file = os.path.join(OUTPUT_FOLDER, base_name + ".txt")
    
    # Check if transcription already exists.
    if os.path.exists(output_file):
        logger.debug(f"Skipping '{input_file}'; transcription already exists.")
        return
    
    # Validate file exists and is readable
    if not os.path.isfile(input_file):
        logger.error(f"File not found or not readable: {input_file}")
        return
    
    file_info = get_file_info(input_file)
    logger.info(f"Starting transcription of '{os.path.basename(input_file)}' ({file_info})")
    
    try:
        # Transcribe the audio file.
        result = model.transcribe(
            input_file, 
            verbose=False,  # Reduced verbosity for cleaner logs
            language="en"
        )
        
        # Create metadata header for the output file
        metadata = f"# Transcription Metadata\n"
        metadata += f"# File: {os.path.basename(input_file)}\n"
        metadata += f"# Size: {file_info}\n"
        metadata += f"# Model: {MODEL_SIZE}\n"
        metadata += f"# Transcribed: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        metadata += f"# Duration: {result.get('duration', 'unknown')} seconds\n"
        metadata += f"# Language: {result.get('language', 'en')}\n\n"
        
        # Save the transcribed text with metadata.
        with open(output_file, "w", encoding="utf-8") as txt:
            txt.write(metadata)
            txt.write(result["text"])
        
        duration = datetime.now() - start_time
        logger.info(f"Completed '{os.path.basename(input_file)}' in {duration.total_seconds():.1f}s -> '{os.path.basename(output_file)}'")
        
    except Exception as e:
        logger.error(f"Failed to transcribe '{input_file}': {e}")
        # Clean up any partial output file
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
                logger.debug(f"Cleaned up partial output file: {output_file}")
            except Exception as cleanup_error:
                logger.warning(f"Could not clean up partial file {output_file}: {cleanup_error}")

def scan_folder():
    """Scan the input folder for new files and transcribe them."""
    try:
        if not os.path.exists(INPUT_FOLDER):
            logger.error(f"Input folder does not exist: {INPUT_FOLDER}")
            return
        
        # List all files in the input folder.
        files = os.listdir(INPUT_FOLDER)
        audio_files = [f for f in files if f.lower().endswith(SUPPORTED_FORMATS)]
        
        if audio_files:
            logger.debug(f"Found {len(audio_files)} audio files to check")
        
        for file_name in audio_files:
            input_file = os.path.join(INPUT_FOLDER, file_name)
            transcribe_file(input_file)
            
    except PermissionError:
        logger.error(f"Permission denied accessing folder: {INPUT_FOLDER}")
    except Exception as e:
        logger.error(f"Error scanning folder {INPUT_FOLDER}: {e}")

if __name__ == "__main__":
    # Ensure output folder exists.
    try:
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        logger.info(f"Output folder ready: {OUTPUT_FOLDER}")
    except Exception as e:
        logger.error(f"Could not create output folder {OUTPUT_FOLDER}: {e}")
        exit(1)
    
    logger.info(f"Starting folder scan (interval: {SCAN_INTERVAL}s). Press Ctrl+C to stop.")
    logger.info(f"Supported formats: {', '.join(SUPPORTED_FORMATS)}")
    
    try:
        # Continuously scan for new files.
        while True:
            scan_folder()
            time.sleep(SCAN_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Transcription service stopped by user.")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
        raise
