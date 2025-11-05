import os
import re
import time
import whisper
import logging
import subprocess
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

# Configuration
VIDEO_FOLDER = os.getenv("TRANSCRIBE_VIDEO_FOLDER", os.path.expanduser("~/Movies"))
AUDIO_FOLDER = os.getenv("TRANSCRIBE_AUDIO_FOLDER", "./work")
WORK_FOLDER = os.getenv("TRANSCRIBE_WORK_FOLDER", "./work")
OUTPUT_FOLDER = os.getenv("TRANSCRIBE_OUTPUT_FOLDER", "./transcribed")
MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "large")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "30"))

# Supported file formats
SUPPORTED_AUDIO_FORMATS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")
SUPPORTED_VIDEO_FORMATS = (".mov", ".mp4", ".m4v", ".mkv")

logger.info(f"Initializing transcription service with model: {MODEL_SIZE}")
logger.info(f"Video folder: {VIDEO_FOLDER}, Audio folder: {AUDIO_FOLDER}, Output folder: {OUTPUT_FOLDER}")

# Load Whisper model
try:
    model = whisper.load_model(MODEL_SIZE)
    logger.info(f"Successfully loaded Whisper model: {MODEL_SIZE}")
except Exception as e:
    logger.error(f"Failed to load Whisper model '{MODEL_SIZE}': {e}")
    raise

def get_file_info(file_path):
    try:
        size_mb = os.path.getsize(file_path) / (1024*1024)
        return f"{size_mb:.1f}MB"
    except Exception:
        return "unknown size"

def create_error_file(output_file, input_file, error_msg):
    """Create an error file with details about the failed transcription."""
    error_file = output_file.replace('.txt', '_error.txt')
    try:
        with open(error_file, 'w', encoding='utf-8') as f:
            f.write(f"# Transcription Failed\n")
            f.write(f"# File: {os.path.basename(input_file)}\n")
            f.write(f"# Error: {error_msg}\n")
            f.write(f"# Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"\nPlease check the audio file for corruption or try converting it manually.\n")
        logger.info(f"Created error file: {error_file}")
    except Exception as e:
        logger.error(f"Failed to create error file: {e}")

def repair_audio_file(input_file):
    """Attempt to repair audio file using ffmpeg."""
    try:
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        repaired_file = os.path.join(WORK_FOLDER, base_name + "_repaired.mp3")
        
        if os.path.exists(repaired_file):
            logger.debug(f"Repaired file already exists: {repaired_file}")
            return repaired_file
        
        logger.info(f"Attempting to repair audio file: {input_file}")
        
        # Use ffmpeg to re-encode the audio file
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_file, "-acodec", "libmp3lame", 
             "-ar", "16000", "-ac", "1", "-ab", "64k", repaired_file],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60
        )
        
        if os.path.exists(repaired_file) and os.path.getsize(repaired_file) > 0:
            logger.info(f"Successfully repaired audio file: {repaired_file}")
            return repaired_file
        else:
            logger.error(f"Failed to repair audio file: output is empty")
            return None
            
    except subprocess.TimeoutExpired:
        logger.error(f"Repair timeout for file: {input_file}")
        return None
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to repair audio file: {e.stderr.decode() if e.stderr else str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error repairing audio file: {e}")
        return None

def convert_to_mp3(input_file, output_file):
    """Convert video file to mp3 audio using ffmpeg, blocking until done."""
    if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
        logger.debug(f"Skipping conversion; already exists: {output_file}")
        return True

    try:
        logger.info(f"Converting '{input_file}' → '{output_file}'")
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_file, "-q:a", "0", "-map", "a", output_file],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Ensure MP3 file is valid
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            logger.info(f"Conversion completed successfully: {output_file}")
            return True
        else:
            logger.error(f"Conversion failed; output empty: {output_file}")
            return False
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to convert '{input_file}': {e.stderr.decode()}")
        return False

def transcribe_file(input_file, retry_count=0, max_retries=3):
    """Transcribe audio file using Whisper with retry logic."""
    start_time = datetime.now()
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_file = os.path.join(OUTPUT_FOLDER, base_name + ".txt")

    if os.path.exists(output_file):
        logger.debug(f"Skipping transcription; already exists: {output_file}")
        return

    if not os.path.isfile(input_file) or os.path.getsize(input_file) == 0:
        logger.error(f"File missing or empty: {input_file}")
        return

    file_info = get_file_info(input_file)
    
    if retry_count == 0:
        logger.info(f"Starting transcription of '{os.path.basename(input_file)}' ({file_info})")
    else:
        logger.info(f"Retrying transcription of '{os.path.basename(input_file)}' (attempt {retry_count + 1}/{max_retries + 1})")

    try:
        # Try with different parameters if retrying
        if retry_count > 0:
            # Use smaller chunk size and different decoding options for problematic files
            result = model.transcribe(
                input_file, 
                verbose=False, 
                language="en",
                fp16=False,  # Explicitly disable FP16
                condition_on_previous_text=False,  # Reduce memory usage
                temperature=0.0  # Use greedy decoding
            )
        else:
            result = model.transcribe(input_file, verbose=False, language="en", fp16=False)
            
        metadata = (
            f"# Transcription Metadata\n"
            f"# File: {os.path.basename(input_file)}\n"
            f"# Size: {file_info}\n"
            f"# Model: {MODEL_SIZE}\n"
            f"# Transcribed: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"# Duration: {result.get('duration', 'unknown')} seconds\n"
            f"# Language: {result.get('language', 'en')}\n\n"
        )
        with open(output_file, "w", encoding="utf-8") as txt:
            txt.write(metadata)
            txt.write(result["text"])

        duration = datetime.now() - start_time
        logger.info(f"Completed '{os.path.basename(input_file)}' in {duration.total_seconds():.1f}s → '{os.path.basename(output_file)}'")
        
    except RuntimeError as e:
        error_msg = str(e)
        if "cannot reshape tensor" in error_msg or "0 elements" in error_msg:
            logger.warning(f"Tensor reshape error for '{input_file}': {e}")
            
            if retry_count < max_retries:
                # Wait with exponential backoff before retrying
                wait_time = 2 ** (retry_count + 1)
                logger.info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
                
                # Try to validate/repair the audio file before retry
                if retry_count == max_retries - 1:
                    logger.info(f"Final attempt: trying to repair audio file first...")
                    repaired_file = repair_audio_file(input_file)
                    if repaired_file and repaired_file != input_file:
                        transcribe_file(repaired_file, retry_count + 1, max_retries)
                        return
                
                transcribe_file(input_file, retry_count + 1, max_retries)
            else:
                logger.error(f"Failed to transcribe '{input_file}' after {max_retries} retries: {e}")
                create_error_file(output_file, input_file, error_msg)
        else:
            logger.error(f"Failed to transcribe '{input_file}': {e}")
            if retry_count < max_retries:
                time.sleep(2 ** (retry_count + 1))
                transcribe_file(input_file, retry_count + 1, max_retries)
            else:
                create_error_file(output_file, input_file, str(e))
                
    except Exception as e:
        logger.error(f"Failed to transcribe '{input_file}': {e}")
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
                logger.debug(f"Removed partial output: {output_file}")
            except Exception as cleanup_error:
                logger.warning(f"Could not remove partial file {output_file}: {cleanup_error}")
        
        if retry_count < max_retries:
            time.sleep(2 ** (retry_count + 1))
            transcribe_file(input_file, retry_count + 1, max_retries)
        else:
            create_error_file(output_file, input_file, str(e))

def process_file(file_path):
    """Convert video to audio if needed, then transcribe synchronously."""
    
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    
    # Check if this file has already been processed (transcription exists)
    transcription_file = os.path.join(OUTPUT_FOLDER, base_name + ".txt")
    if os.path.exists(transcription_file):
        logger.debug(f"Skipping already processed file: {file_path}")
        return
    
    # Check if file was created before November 1, 2025
    try:
        file_creation_time = os.path.getctime(file_path)
        creation_date = datetime.fromtimestamp(file_creation_time)
        cutoff_date = datetime(2025, 11, 1)

        if creation_date < cutoff_date:
            logger.debug(f"Skipping file created before November 1, 2025: {file_path} (created: {creation_date.strftime('%Y-%m-%d')})")
            return
    except Exception as e:
        logger.warning(f"Could not check creation date for {file_path}: {e}")

    if file_path.lower().endswith(SUPPORTED_VIDEO_FORMATS):
        mp3_file = os.path.join(WORK_FOLDER, base_name + ".mp3")
        # Blocking conversion first
        if convert_to_mp3(file_path, mp3_file):
            transcribe_file(mp3_file)
    elif file_path.lower().endswith(SUPPORTED_AUDIO_FORMATS):
        if os.path.getsize(file_path) > 0:
            transcribe_file(file_path)

def scan_folder():
    """Scan video and audio folders and process files."""
    try:
        # Scan video folder for video files
        if os.path.exists(VIDEO_FOLDER):
            for file_name in os.listdir(VIDEO_FOLDER):
                if file_name.lower().endswith(SUPPORTED_VIDEO_FORMATS):
                    file_path = os.path.join(VIDEO_FOLDER, file_name)
                    process_file(file_path)
        else:
            logger.warning(f"Video folder does not exist: {VIDEO_FOLDER}")

        # Scan audio folder for audio files
        if os.path.exists(AUDIO_FOLDER):
            for file_name in os.listdir(AUDIO_FOLDER):
                if file_name.lower().endswith(SUPPORTED_AUDIO_FORMATS):
                    file_path = os.path.join(AUDIO_FOLDER, file_name)
                    process_file(file_path)
        else:
            logger.warning(f"Audio folder does not exist: {AUDIO_FOLDER}")

    except PermissionError as e:
        logger.error(f"Permission denied accessing folder: {e}")
    except Exception as e:
        logger.error(f"Error scanning folders: {e}")

if __name__ == "__main__":
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    os.makedirs(WORK_FOLDER, exist_ok=True)
    logger.info(f"Starting folder scan (interval: {SCAN_INTERVAL}s)")

    try:
        while True:
            scan_folder()
            time.sleep(SCAN_INTERVAL)
    except KeyboardInterrupt:
        logger.info("Transcription service stopped by user.")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
        raise