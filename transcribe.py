#!/usr/bin/env python3
"""
Single-file audio transcription script using OpenAI Whisper.
For batch processing with file watching, use transcribe_all.py instead.
"""

import os
import sys
import argparse
import whisper
import logging
from datetime import datetime
from pathlib import Path
from config import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_file_info(file_path):
    """Get file size and basic info for logging."""
    try:
        file_size = os.path.getsize(file_path)
        size_mb = file_size / (1024 * 1024)
        return f"{size_mb:.1f}MB"
    except Exception:
        return "unknown size"

def transcribe_file(input_file, output_file=None, model_size=None, language="en", verbose=False):
    """
    Transcribe a single audio file using Whisper.

    Args:
        input_file: Path to the input audio file
        output_file: Path to the output text file (optional)
        model_size: Whisper model size (tiny, base, small, medium, large)
        language: Language code for transcription
        verbose: Enable verbose output during transcription
    """
    start_time = datetime.now()

    # Use default model size if not specified
    if model_size is None:
        model_size = config.model_size

    # Validate input file
    if not os.path.isfile(input_file):
        logger.error(f"Input file not found: {input_file}")
        return False

    # Check file extension
    file_ext = Path(input_file).suffix.lower()
    supported_formats = config.supported_audio_formats + config.supported_video_formats
    if file_ext not in supported_formats:
        logger.warning(f"File extension '{file_ext}' may not be supported. Supported formats: {', '.join(supported_formats)}")

    # Generate output filename if not provided
    if output_file is None:
        base_name = Path(input_file).stem
        os.makedirs(config.output_folder, exist_ok=True)
        output_file = os.path.join(config.output_folder, f"{base_name}.txt")
    
    # Check if transcription already exists
    if os.path.exists(output_file):
        logger.info(f"Transcription already exists: {output_file}")
        overwrite = input("Overwrite existing file? (y/N): ").strip().lower()
        if overwrite != 'y':
            logger.info("Skipping transcription.")
            return False
    
    file_info = get_file_info(input_file)
    device = config.compute_device
    logger.info(f"Loading Whisper model: {model_size} on {device}")

    try:
        model = whisper.load_model(model_size, device=device)
        logger.info(f"Successfully loaded Whisper model: {model_size} on {device}")
    except NotImplementedError as e:
        # MPS backend doesn't support sparse tensor operations used by Whisper
        if "SparseMPS" in str(e) and device == "mps":
            logger.warning(
                "MPS backend doesn't support sparse tensors for Whisper, "
                "falling back to CPU"
            )
            device = "cpu"
            model = whisper.load_model(model_size, device=device)
            logger.info(f"Successfully loaded Whisper model: {model_size} on {device}")
        else:
            logger.error(f"Failed to load Whisper model '{model_size}': {e}")
            return False
    except Exception as e:
        logger.error(f"Failed to load Whisper model '{model_size}': {e}")
        return False
    
    logger.info(f"Starting transcription of '{os.path.basename(input_file)}' ({file_info})")
    
    try:
        # Transcribe the audio file
        result = model.transcribe(
            input_file,
            verbose=verbose,
            language=language if language != "auto" else None
        )
        
        # Create metadata header for the output file
        metadata = f"# Transcription Metadata\n"
        metadata += f"# File: {os.path.basename(input_file)}\n"
        metadata += f"# Size: {file_info}\n"
        metadata += f"# Model: {model_size}\n"
        metadata += f"# Transcribed: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        metadata += f"# Duration: {result.get('duration', 'unknown')} seconds\n"
        metadata += f"# Language: {result.get('language', language)}\n\n"
        
        # Save the transcribed text with metadata
        with open(output_file, "w", encoding="utf-8") as txt:
            txt.write(metadata)
            txt.write(result["text"])
        
        duration = datetime.now() - start_time
        logger.info(f"Completed '{os.path.basename(input_file)}' in {duration.total_seconds():.1f}s -> '{output_file}'")
        return True
        
    except Exception as e:
        logger.error(f"Failed to transcribe '{input_file}': {e}")
        # Clean up any partial output file
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
                logger.debug(f"Cleaned up partial output file: {output_file}")
            except Exception as cleanup_error:
                logger.warning(f"Could not clean up partial file {output_file}: {cleanup_error}")
        return False

def main():
    supported_formats = config.supported_audio_formats + config.supported_video_formats

    parser = argparse.ArgumentParser(
        description="Transcribe audio files using OpenAI Whisper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Supported audio formats: {', '.join(supported_formats)}

Environment variables:
  TRANSCRIBE_OUTPUT_FOLDER  Output directory (default: ./transcribed)
  WHISPER_MODEL_SIZE        Default model size (default: large)

Examples:
  %(prog)s audio.mp3                    # Transcribe to ./transcribed/audio.txt
  %(prog)s audio.mp3 -o transcript.txt  # Transcribe to specific file
  %(prog)s audio.mp3 -m base            # Use base model (faster, less accurate)
  %(prog)s audio.mp3 -l es              # Transcribe Spanish audio
  %(prog)s audio.mp3 -l auto            # Auto-detect language
  %(prog)s audio.mp3 -v                 # Show detailed progress

For batch processing with file watching, use transcribe_all.py
        """
    )

    parser.add_argument(
        "input_file",
        help="Path to the audio file to transcribe"
    )
    parser.add_argument(
        "-o", "--output",
        help=f"Output text file path (default: {config.output_folder}/<input_name>.txt)",
        default=None
    )
    parser.add_argument(
        "-m", "--model",
        help=f"Whisper model size (default: {config.model_size})",
        choices=["tiny", "base", "small", "medium", "large"],
        default=None
    )
    parser.add_argument(
        "-l", "--language",
        help="Language code (e.g., 'en' for English, 'auto' for auto-detect, default: en)",
        default="en"
    )
    parser.add_argument(
        "-v", "--verbose",
        help="Enable verbose output during transcription",
        action="store_true"
    )
    
    args = parser.parse_args()
    
    # Run transcription
    success = transcribe_file(
        args.input_file,
        args.output,
        args.model,
        args.language,
        args.verbose
    )
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    # If no arguments provided, show help
    if len(sys.argv) == 1:
        main()
    else:
        main()