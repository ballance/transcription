import logging
import os
import subprocess
import time
from datetime import datetime

import progress as prog
from config import config
from reprocess_transcriptions import extract_summary_from_content
from whisperx_pipeline import (
    format_segments_as_text,
    load_transcription_model,
    strip_formatting_for_summary,
    transcribe as whisperx_transcribe,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("transcription.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# File stability tracking - tracks (size, mtime, first_stable_time) for each file
# Files must be unchanged for stability_window seconds before processing
file_stability_tracker: dict[str, tuple[int, float, float]] = {}

logger.info(f"Initializing transcription service with model: {config.model_size}")
logger.info(
    f"Video folder: {config.video_folder}, Audio folder: {config.audio_folder}, "
    f"Output folder: {config.output_folder}"
)
logger.info(f"Skipping files created before: {config.skip_files_before_date}")
logger.info(f"File stability window: {config.stability_window}s (files must be unchanged before processing)")
logger.info(f"Prioritize recent files: {config.prioritize_recent}")

# Load WhisperX model
try:
    load_transcription_model()
except Exception as e:
    logger.error(f"Failed to load WhisperX model '{config.model_size}': {e}")
    raise


def is_file_stable(file_path: str) -> bool:
    """
    Check if a file has been stable (unchanged) for the configured stability window.

    This prevents processing files that are still being written to.
    Returns True if file is ready for processing, False if still potentially being written.
    """
    try:
        current_size = os.path.getsize(file_path)
        current_mtime = os.path.getmtime(file_path)
    except OSError as e:
        logger.debug(f"Cannot stat file {file_path}: {e}")
        return False

    now = time.time()

    if file_path in file_stability_tracker:
        last_size, last_mtime, first_stable = file_stability_tracker[file_path]

        if current_size == last_size and current_mtime == last_mtime:
            # File unchanged - check if stable long enough
            stable_duration = now - first_stable
            if stable_duration >= config.stability_window:
                logger.debug(
                    f"File stable for {stable_duration:.1f}s (>= {config.stability_window}s): {file_path}"
                )
                return True
            else:
                logger.debug(
                    f"File stable for {stable_duration:.1f}s (need {config.stability_window}s): {file_path}"
                )
                return False
        else:
            # File changed - reset tracker
            logger.debug(
                f"File changed (size: {last_size}->{current_size}, mtime: {last_mtime}->{current_mtime}): {file_path}"
            )
            file_stability_tracker[file_path] = (current_size, current_mtime, now)
            return False
    else:
        # First time seeing this file
        logger.debug(f"First observation of file, starting stability tracking: {file_path}")
        file_stability_tracker[file_path] = (current_size, current_mtime, now)
        return False


def cleanup_stability_tracker(existing_files: set[str]) -> None:
    """Remove entries from stability tracker for files that no longer exist or were processed."""
    stale_paths = [path for path in file_stability_tracker if path not in existing_files]
    for path in stale_paths:
        del file_stability_tracker[path]
        logger.debug(f"Removed from stability tracker: {path}")


def get_file_info(file_path):
    try:
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        return f"{size_mb:.1f}MB"
    except Exception:
        return "unknown size"


def create_error_file(output_file, input_file, error_msg):
    """Create an error file with details about the failed transcription."""
    error_file = output_file.replace(".txt", "_error.txt")
    try:
        with open(error_file, "w", encoding="utf-8") as f:
            f.write(f"# Transcription Failed\n")
            f.write(f"# File: {os.path.basename(input_file)}\n")
            f.write(f"# Error: {error_msg}\n")
            f.write(f"# Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(
                f"\nPlease check the audio file for corruption or try converting it manually.\n"
            )
        logger.info(f"Created error file: {error_file}")
    except Exception as e:
        logger.error(f"Failed to create error file: {e}")


def rename_with_summary(output_file: str) -> str:
    """Rename transcript file with content summary. Returns final path."""
    if not config.auto_rename:
        return output_file

    try:
        with open(output_file, "r", encoding="utf-8") as f:
            full_text = f.read()

        content = strip_formatting_for_summary(full_text)

        summary = extract_summary_from_content(content)
        if not summary:
            logger.info(f"No summary generated for '{os.path.basename(output_file)}', keeping original name")
            return output_file

        # Build new filename: <base> - <summary>.txt
        directory = os.path.dirname(output_file)
        base_name = os.path.splitext(os.path.basename(output_file))[0]
        new_name = f"{base_name} - {summary}.txt"
        new_path = os.path.join(directory, new_name)

        os.rename(output_file, new_path)
        logger.info(f"Renamed transcript: '{os.path.basename(output_file)}' → '{new_name}'")

        # Create symlink from original name to renamed file so skip-checks still work
        try:
            os.symlink(new_name, output_file)
            logger.debug(f"Created symlink: '{os.path.basename(output_file)}' → '{new_name}'")
        except OSError as e:
            logger.warning(f"Could not create symlink for '{os.path.basename(output_file)}': {e}")

        return new_path

    except Exception as e:
        logger.warning(f"Failed to rename transcript with summary: {e}")
        return output_file


def repair_audio_file(input_file):
    """Attempt to repair audio file using ffmpeg."""
    try:
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        repaired_file = os.path.join(config.work_folder, base_name + "_repaired.mp3")

        if os.path.exists(repaired_file):
            logger.debug(f"Repaired file already exists: {repaired_file}")
            return repaired_file

        logger.info(f"Attempting to repair audio file: {input_file}")

        # Use ffmpeg to re-encode the audio file
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_file,
                "-acodec",
                "libmp3lame",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-ab",
                "64k",
                repaired_file,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
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
        logger.error(
            f"Failed to repair audio file: {e.stderr.decode() if e.stderr else str(e)}"
        )
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
            stderr=subprocess.PIPE,
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


def transcribe_file(input_file, retry_count=0, max_retries=None):
    """Transcribe audio file using Whisper with retry logic."""
    if max_retries is None:
        max_retries = config.max_retries

    start_time = datetime.now()
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_file = os.path.join(config.output_folder, base_name + ".txt")

    if os.path.exists(output_file):
        logger.debug(f"Skipping transcription; already exists: {output_file}")
        return

    if not os.path.isfile(input_file) or os.path.getsize(input_file) == 0:
        logger.error(f"File missing or empty: {input_file}")
        return

    file_info = get_file_info(input_file)

    if retry_count == 0:
        logger.info(
            f"Starting transcription of '{os.path.basename(input_file)}' ({file_info})"
        )
        prog.start_file(input_file)
    else:
        logger.info(
            f"Retrying transcription of '{os.path.basename(input_file)}' (attempt {retry_count + 1}/{max_retries + 1})"
        )

    try:
        result = whisperx_transcribe(input_file, language="en")

        segments = result["segments"]
        diarization_applied = result["diarization_applied"]
        detected_language = result["language"]
        recognized_speakers = result.get("recognized_speakers", {})

        formatted_text = format_segments_as_text(segments, diarization_applied)

        diarize_info = "disabled"
        if diarization_applied:
            speakers = {s.get("speaker") for s in segments if "speaker" in s}
            diarize_info = f"enabled ({len(speakers)} speakers"
            if recognized_speakers:
                names = ", ".join(sorted(recognized_speakers.values()))
                diarize_info += f", recognized: {names}"
            diarize_info += ")"

        metadata = (
            f"# Transcription Metadata\n"
            f"# File: {os.path.basename(input_file)}\n"
            f"# Size: {file_info}\n"
            f"# Model: {config.model_size}\n"
            f"# Engine: whisperx\n"
            f"# Diarization: {diarize_info}\n"
            f"# Transcribed: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"# Language: {detected_language}\n\n"
        )
        with open(output_file, "w", encoding="utf-8") as txt:
            txt.write(metadata)
            txt.write(formatted_text)

        # Rename with content summary (returns new path or original if unchanged)
        output_file = rename_with_summary(output_file)

        duration = datetime.now() - start_time
        logger.info(
            f"Completed '{os.path.basename(input_file)}' in {duration.total_seconds():.1f}s → '{os.path.basename(output_file)}'"
        )
        prog.finish_file()

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
                logger.error(
                    f"Failed to transcribe '{input_file}' after {max_retries} retries: {e}"
                )
                prog.set_error(str(e))
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
                logger.warning(
                    f"Could not remove partial file {output_file}: {cleanup_error}"
                )

        if retry_count < max_retries:
            time.sleep(2 ** (retry_count + 1))
            transcribe_file(input_file, retry_count + 1, max_retries)
        else:
            create_error_file(output_file, input_file, str(e))


def process_file(file_path):
    """Convert video to audio if needed, then transcribe synchronously."""

    base_name = os.path.splitext(os.path.basename(file_path))[0]

    # Check if this file has already been processed (transcription exists)
    transcription_file = os.path.join(config.output_folder, base_name + ".txt")
    if os.path.exists(transcription_file):
        logger.debug(f"Skipping already processed file: {file_path}")
        return

    # Check if file was created before the configured cutoff date
    try:
        file_creation_time = os.path.getctime(file_path)
        creation_date = datetime.fromtimestamp(file_creation_time)

        if creation_date < config.cutoff_datetime:
            logger.debug(
                f"Skipping file created before {config.skip_files_before_date}: {file_path} "
                f"(created: {creation_date.strftime('%Y-%m-%d')})"
            )
            return
    except Exception as e:
        logger.warning(f"Could not check creation date for {file_path}: {e}")

    if file_path.lower().endswith(config.supported_video_formats):
        mp3_file = os.path.join(config.work_folder, base_name + ".mp3")
        # Blocking conversion first
        if convert_to_mp3(file_path, mp3_file):
            transcribe_file(mp3_file)
    elif file_path.lower().endswith(config.supported_audio_formats):
        if os.path.getsize(file_path) > 0:
            transcribe_file(file_path)


def scan_folder():
    """Scan video and audio folders and process files.

    Files must be stable (unchanged) for the configured stability_window
    before they will be processed. This prevents processing files that
    are still being written.

    When prioritize_recent is enabled, files are sorted by modification time
    (newest first) before processing.
    """
    seen_files: set[str] = set()
    candidate_files: list[str] = []

    try:
        # Collect video files
        if os.path.exists(config.video_folder):
            for file_name in os.listdir(config.video_folder):
                if file_name.lower().endswith(config.supported_video_formats):
                    file_path = os.path.join(config.video_folder, file_name)
                    seen_files.add(file_path)
                    if is_file_stable(file_path):
                        candidate_files.append(file_path)
        else:
            logger.warning(f"Video folder does not exist: {config.video_folder}")

        # Collect audio files
        if os.path.exists(config.audio_folder):
            for file_name in os.listdir(config.audio_folder):
                if file_name.lower().endswith(config.supported_audio_formats):
                    file_path = os.path.join(config.audio_folder, file_name)
                    seen_files.add(file_path)
                    if is_file_stable(file_path):
                        candidate_files.append(file_path)
        else:
            logger.warning(f"Audio folder does not exist: {config.audio_folder}")

        # Sort files: PRIORITY files first, then by modification time (newest first) if enabled
        if candidate_files:
            def sort_key(f: str) -> tuple:
                filename = os.path.basename(f).upper()
                is_priority = 0 if "PRIORITY" in filename else 1
                mtime = -os.path.getmtime(f) if config.prioritize_recent else 0
                return (is_priority, mtime)

            candidate_files.sort(key=sort_key)

        # Process files
        for file_path in candidate_files:
            process_file(file_path)

        # Clean up tracker entries for files that no longer exist
        cleanup_stability_tracker(seen_files)

    except PermissionError as e:
        logger.error(f"Permission denied accessing folder: {e}")
    except Exception as e:
        logger.error(f"Error scanning folders: {e}")


if __name__ == "__main__":
    os.makedirs(config.output_folder, exist_ok=True)
    os.makedirs(config.work_folder, exist_ok=True)
    logger.info(
        f"Starting folder scan (interval: {config.scan_interval}s, "
        f"stability window: {config.stability_window}s)"
    )

    try:
        with prog.progress_display():
            while True:
                scan_folder()
                time.sleep(config.scan_interval)
    except KeyboardInterrupt:
        logger.info("Transcription service stopped by user.")
        prog.clear_progress()
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
        raise
