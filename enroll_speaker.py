#!/usr/bin/env python3
"""
CLI for enrolling speaker voice profiles.

Subcommands:
  record <name>            Record from microphone and enroll
  enroll <name> <files..>  Enroll from existing audio files
  list                     List enrolled speakers
  remove <name>            Remove a speaker profile

Examples:
  python enroll_speaker.py record "Alice" --duration 30 --samples 3
  python enroll_speaker.py enroll "Bob" meeting.mp3 interview.wav
  python enroll_speaker.py list
  python enroll_speaker.py remove "Alice"
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
import tempfile

from config import config
from speaker_profiles import (
    SpeakerProfile,
    extract_embedding_from_audio,
    load_profiles,
    save_profiles,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def record_audio(output_path: str, duration: int = 30) -> bool:
    """Record audio from the default microphone.

    Tries sox (rec) first, then falls back to ffmpeg with avfoundation (macOS).
    """
    if shutil.which("rec"):
        logger.info(f"Recording {duration}s of audio with sox...")
        print(f"Recording for {duration} seconds. Speak clearly into your microphone.")
        print("Press Ctrl+C to stop early.\n")
        try:
            subprocess.run(
                [
                    "rec",
                    "-r", "16000",
                    "-c", "1",
                    "-b", "16",
                    output_path,
                    "trim", "0", str(duration),
                ],
                check=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"sox recording failed: {e}")
            return False
        except KeyboardInterrupt:
            print("\nRecording stopped early.")
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0

    if shutil.which("ffmpeg"):
        logger.info(f"Recording {duration}s of audio with ffmpeg (avfoundation)...")
        print(f"Recording for {duration} seconds. Speak clearly into your microphone.")
        print("Press Ctrl+C to stop early.\n")
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f", "avfoundation",
                    "-i", ":default",
                    "-ar", "16000",
                    "-ac", "1",
                    "-t", str(duration),
                    output_path,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg recording failed: {e}")
            return False
        except KeyboardInterrupt:
            print("\nRecording stopped early.")
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0

    logger.error("No recording tool found. Install sox or ffmpeg.")
    return False


def cmd_record(args):
    """Record voice samples from microphone and enroll."""
    name = args.name
    duration = args.duration
    num_samples = args.samples
    profiles_path = config.speaker_profiles_path

    if not config.hf_token:
        logger.error(
            "HF_TOKEN is required for embedding extraction. "
            "Set it in your .env or environment."
        )
        sys.exit(1)

    profiles = load_profiles(profiles_path)

    if name in profiles:
        print(f"Profile '{name}' already exists with {profiles[name].sample_count} sample(s).")
        answer = input("Add more samples? (y/N): ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    profile = profiles.get(name, SpeakerProfile(name=name))

    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(num_samples):
            print(f"\n--- Sample {i + 1}/{num_samples} ---")
            audio_file = os.path.join(tmpdir, f"sample_{i}.wav")

            if not record_audio(audio_file, duration):
                logger.error(f"Failed to record sample {i + 1}")
                continue

            print("Extracting speaker embedding...")
            try:
                embedding = extract_embedding_from_audio(
                    audio_file, config.hf_token, config.whisperx_device
                )
                profile.add_embedding(embedding)
                print(f"Sample {i + 1} enrolled successfully.")
            except Exception as e:
                logger.error(f"Failed to extract embedding from sample {i + 1}: {e}")

    if profile.sample_count > 0:
        profiles[name] = profile
        save_profiles(profiles, profiles_path)
        print(f"\nEnrolled '{name}' with {profile.sample_count} sample(s).")
    else:
        print(f"\nNo samples were enrolled for '{name}'.")


def cmd_enroll(args):
    """Enroll a speaker from existing audio files."""
    name = args.name
    files = args.files
    profiles_path = config.speaker_profiles_path

    if not config.hf_token:
        logger.error(
            "HF_TOKEN is required for embedding extraction. "
            "Set it in your .env or environment."
        )
        sys.exit(1)

    profiles = load_profiles(profiles_path)

    if name in profiles:
        print(f"Profile '{name}' already exists with {profiles[name].sample_count} sample(s).")
        answer = input("Add more samples? (y/N): ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    profile = profiles.get(name, SpeakerProfile(name=name))

    for audio_file in files:
        if not os.path.isfile(audio_file):
            logger.error(f"File not found: {audio_file}")
            continue

        print(f"Extracting embedding from '{os.path.basename(audio_file)}'...")
        try:
            embedding = extract_embedding_from_audio(
                audio_file, config.hf_token, config.whisperx_device
            )
            profile.add_embedding(embedding)
            print(f"  Enrolled successfully.")
        except Exception as e:
            logger.error(f"Failed to extract embedding from '{audio_file}': {e}")

    if profile.sample_count > 0:
        profiles[name] = profile
        save_profiles(profiles, profiles_path)
        print(f"\nEnrolled '{name}' with {profile.sample_count} total sample(s).")
    else:
        print(f"\nNo samples were enrolled for '{name}'.")


def cmd_list(args):
    """List all enrolled speaker profiles."""
    profiles_path = config.speaker_profiles_path
    profiles = load_profiles(profiles_path)

    if not profiles:
        print("No speaker profiles enrolled.")
        print(f"  Use: python enroll_speaker.py record <name>")
        print(f"  Or:  python enroll_speaker.py enroll <name> <audio_file>")
        return

    print(f"Enrolled speakers ({len(profiles)}):\n")
    for name, profile in sorted(profiles.items()):
        print(f"  {profile.name}")
        print(f"    Samples:  {profile.sample_count}")
        print(f"    Created:  {profile.created_at}")
        print(f"    Updated:  {profile.updated_at}")
        print()


def cmd_remove(args):
    """Remove a speaker profile."""
    name = args.name
    profiles_path = config.speaker_profiles_path
    profiles = load_profiles(profiles_path)

    if name not in profiles:
        print(f"No profile found for '{name}'.")
        print(f"Available profiles: {', '.join(profiles.keys()) or '(none)'}")
        return

    answer = input(f"Remove profile '{name}'? (y/N): ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    del profiles[name]
    save_profiles(profiles, profiles_path)
    print(f"Removed profile '{name}'.")


def main():
    parser = argparse.ArgumentParser(
        description="Manage speaker voice profiles for recognition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # record
    rec_parser = subparsers.add_parser(
        "record", help="Record from microphone and enroll"
    )
    rec_parser.add_argument("name", help="Speaker name")
    rec_parser.add_argument(
        "--duration", type=int, default=30, help="Recording duration in seconds (default: 30)"
    )
    rec_parser.add_argument(
        "--samples", type=int, default=3, help="Number of samples to record (default: 3)"
    )
    rec_parser.set_defaults(func=cmd_record)

    # enroll
    enroll_parser = subparsers.add_parser(
        "enroll", help="Enroll from existing audio files"
    )
    enroll_parser.add_argument("name", help="Speaker name")
    enroll_parser.add_argument(
        "files", nargs="+", help="Audio file(s) containing the speaker's voice"
    )
    enroll_parser.set_defaults(func=cmd_enroll)

    # list
    list_parser = subparsers.add_parser("list", help="List enrolled speakers")
    list_parser.set_defaults(func=cmd_list)

    # remove
    remove_parser = subparsers.add_parser("remove", help="Remove a speaker profile")
    remove_parser.add_argument("name", help="Speaker name to remove")
    remove_parser.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
