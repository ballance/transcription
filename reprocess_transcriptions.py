#!/usr/bin/env python3
"""
Utility script to analyze, reprocess suspicious transcriptions, and rename with summary suffixes.

Usage:
    python reprocess_transcriptions.py analyze      # Show analysis of transcriptions and work folder
    python reprocess_transcriptions.py reprocess    # Reprocess suspicious transcriptions
    python reprocess_transcriptions.py reconvert    # Reconvert suspicious audio from work folder
    python reprocess_transcriptions.py rename       # Add summary suffixes to transcription filenames
    python reprocess_transcriptions.py all          # Do all of the above

Options:
    --execute          Actually perform changes (default is dry-run)
    --repetition-only  Only reprocess files with repetition artifacts
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class TranscriptionAnalysis:
    """Analysis results for a transcription file."""

    file_path: str
    file_size: int
    source_file: str | None
    source_size: int | None
    duration: str | None
    content_length: int  # Length of actual transcription text (excluding metadata)
    word_count: int
    is_suspicious: bool
    suspicion_reasons: list[str]
    suggested_summary: str | None


@dataclass
class ConvertedAudioAnalysis:
    """Analysis results for a converted audio file in the work folder."""

    file_path: str
    file_size: int
    file_mtime: float
    original_video_path: str | None
    original_video_size: int | None
    original_video_mtime: float | None
    is_suspicious: bool
    suspicion_reasons: list[str]
    has_transcription: bool


def parse_transcription_metadata(file_path: str) -> dict:
    """Parse metadata from a transcription file."""
    metadata = {}
    content_lines = []
    in_metadata = True

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if in_metadata and line.startswith("# "):
                if ": " in line:
                    key, value = line[2:].split(": ", 1)
                    metadata[key.strip()] = value.strip()
            elif in_metadata and line.strip() == "":
                in_metadata = False
            else:
                in_metadata = False
                content_lines.append(line)

    metadata["_content"] = "".join(content_lines).strip()
    return metadata


def find_source_file(transcription_name: str) -> tuple[str | None, int | None]:
    """Find the source audio/video file for a transcription."""
    base_name = os.path.splitext(transcription_name)[0]

    # Check work folder for converted audio
    for ext in config.supported_audio_formats:
        audio_path = os.path.join(config.work_folder, base_name + ext)
        if os.path.exists(audio_path):
            return audio_path, os.path.getsize(audio_path)

    # Check video folder for original video
    for ext in config.supported_video_formats:
        video_path = os.path.join(config.video_folder, base_name + ext)
        if os.path.exists(video_path):
            return video_path, os.path.getsize(video_path)

    # Check audio folder
    for ext in config.supported_audio_formats:
        audio_path = os.path.join(config.audio_folder, base_name + ext)
        if os.path.exists(audio_path):
            return audio_path, os.path.getsize(audio_path)

    return None, None


def estimate_expected_words(audio_size_bytes: int, is_video: bool = False) -> int:
    """
    Estimate expected word count based on audio file size.

    Assumptions:
    - MP3 at ~64kbps = 8KB per second of audio
    - Average speaking rate: ~150 words per minute = 2.5 words per second
    - Video files are larger due to video track (estimate 10x for raw video)
    """
    if is_video:
        audio_size_bytes = audio_size_bytes // 10  # Rough estimate

    seconds = audio_size_bytes / 8000  # 64kbps = 8KB/s
    expected_words = int(seconds * 2.5)
    return expected_words


def extract_summary_from_content(content: str, max_length: int = 50) -> str | None:
    """
    Extract a summary/title from transcription content.

    Looks for:
    1. Meeting type keywords (standup, sync, review, etc.)
    2. Topic mentions
    3. Project/product names
    4. First meaningful sentence
    """
    if not content or len(content) < 20:
        return None

    content_lower = content.lower()

    # Meeting type patterns (ordered by specificity)
    meeting_types = {
        "stand-up": "Standup",
        "standup": "Standup",
        "stand up": "Standup",
        "retrospective": "Retro",
        "retro ": "Retro",
        "kickoff": "Kickoff",
        "kick-off": "Kickoff",
        "one-on-one": "1on1",
        "1:1": "1on1",
        "all hands": "All Hands",
        "town hall": "Town Hall",
        "planning": "Planning",
        "sprint planning": "Sprint Planning",
        "backlog": "Backlog",
        "grooming": "Grooming",
        "refinement": "Refinement",
        "demo": "Demo",
        "presentation": "Presentation",
        "interview": "Interview",
        "training": "Training",
        "workshop": "Workshop",
        "brainstorm": "Brainstorm",
        "sync": "Sync",
        "check-in": "Check-in",
        "check in": "Check-in",
        "weekly": "Weekly",
        "daily": "Daily",
        "review": "Review",
    }

    # Project/product patterns
    projects = {
        "transcription": "Transcription",
        "simulation": "Simulation",
        "assessment": "Assessment",
        "curriculum": "Curriculum",
        "analytics": "Analytics",
        "dashboard": "Dashboard",
    }

    # Technical topic patterns
    topics = {
        "kafka": "Kafka",
        "deployment": "Deployment",
        "infrastructure": "Infra",
        "infra": "Infra",
        "terraform": "Terraform",
        "database": "Database",
        "api ": "API",
        "frontend": "Frontend",
        "backend": "Backend",
        "testing": "Testing",
        "bug fix": "Bug Fix",
        "hotfix": "Hotfix",
        "hot fix": "Hotfix",
        "security": "Security",
        "performance": "Performance",
        "architecture": "Architecture",
        "design": "Design",
        "sprint": "Sprint",
        "release": "Release",
        "incident": "Incident",
        "outage": "Outage",
        "rca": "RCA",
        "postmortem": "Postmortem",
        "migration": "Migration",
    }

    # Look for team names
    teams = {
        "devops": "DevOps",
        "sre": "SRE",
        "engineering": "Engineering",
        "product": "Product",
    }

    summary_parts = []

    # Find team (prefer longer matches)
    for pattern, name in sorted(teams.items(), key=lambda x: -len(x[0])):
        if pattern in content_lower:
            summary_parts.append(name)
            break

    # Find meeting type (prefer longer matches)
    for pattern, name in sorted(meeting_types.items(), key=lambda x: -len(x[0])):
        if pattern in content_lower:
            summary_parts.append(name)
            break

    # If we have a meeting type but no team, look for projects
    if len(summary_parts) == 1:
        for pattern, name in sorted(projects.items(), key=lambda x: -len(x[0])):
            if pattern in content_lower:
                summary_parts.insert(0, name)
                break

    # If still not enough context, look for technical topics
    if len(summary_parts) < 2:
        for pattern, name in sorted(topics.items(), key=lambda x: -len(x[0])):
            if pattern in content_lower:
                if name not in summary_parts:
                    summary_parts.append(name)
                    if len(summary_parts) >= 2:
                        break

    if summary_parts:
        summary = " ".join(summary_parts)
        return summary[:max_length]

    # Fallback: extract first meaningful sentence (skip common greetings)
    greetings = [
        "thank you", "hello", "hi everyone", "hey guys", "good morning",
        "good afternoon", "hey everyone", "hi there", "welcome",
    ]
    sentences = re.split(r"[.!?]+", content)
    for sentence in sentences:
        sentence = sentence.strip()
        # Skip very short sentences or common greetings
        if len(sentence) > 30 and not any(g in sentence.lower() for g in greetings):
            # Clean and truncate to meaningful words
            words = [w for w in sentence.split() if len(w) > 2][:5]
            if len(words) >= 3:
                return " ".join(words)

    return None


def analyze_transcription(file_path: str) -> TranscriptionAnalysis:
    """Analyze a single transcription file for issues."""
    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)

    metadata = parse_transcription_metadata(file_path)
    content = metadata.get("_content", "")
    source_file_name = metadata.get("File", "")
    duration = metadata.get("Duration", "unknown")

    source_path, source_size = find_source_file(file_name)

    word_count = len(content.split()) if content else 0
    content_length = len(content)

    suspicion_reasons = []

    # Check for unknown duration (file may have been incomplete during transcription)
    if "unknown" in str(duration).lower():
        suspicion_reasons.append("Duration unknown (file may have been incomplete)")

    # Check if transcription seems too short for source file
    if source_size:
        is_video = source_path and source_path.lower().endswith(config.supported_video_formats)
        expected_words = estimate_expected_words(source_size, is_video)

        # If we got less than 10% of expected words, something might be wrong
        if expected_words > 50 and word_count < expected_words * 0.1:
            suspicion_reasons.append(
                f"Word count ({word_count}) much lower than expected ({expected_words})"
            )

    # Check for very short content
    if content_length < 50 and source_size and source_size > 500000:  # 500KB source
        suspicion_reasons.append("Very short transcription for large source file")

    # Check for truncation indicators
    if content and not content.rstrip().endswith((".", "!", "?", '"', "'")):
        # Might be truncated mid-sentence
        last_words = content.split()[-3:] if content.split() else []
        if last_words and len(last_words[-1]) < 3:
            suspicion_reasons.append("Content may be truncated (ends mid-word)")

    # Check for repetition artifacts (sign of processing incomplete file)
    if content:
        # Look for repeated phrases (5+ word sequences repeated 3+ times)
        words = content.split()
        for window_size in [5, 7, 10]:
            if len(words) >= window_size * 3:
                phrases = {}
                for i in range(len(words) - window_size + 1):
                    phrase = " ".join(words[i : i + window_size])
                    phrases[phrase] = phrases.get(phrase, 0) + 1
                for phrase, count in phrases.items():
                    if count >= 3:
                        suspicion_reasons.append(
                            f"Repetition detected: '{phrase[:40]}...' appears {count}x"
                        )
                        break
                if suspicion_reasons and "Repetition" in suspicion_reasons[-1]:
                    break

    suggested_summary = extract_summary_from_content(content)

    return TranscriptionAnalysis(
        file_path=file_path,
        file_size=file_size,
        source_file=source_path,
        source_size=source_size,
        duration=duration,
        content_length=content_length,
        word_count=word_count,
        is_suspicious=len(suspicion_reasons) > 0,
        suspicion_reasons=suspicion_reasons,
        suggested_summary=suggested_summary,
    )


def analyze_all_transcriptions() -> list[TranscriptionAnalysis]:
    """Analyze all transcription files in the output folder."""
    results = []

    if not os.path.exists(config.output_folder):
        logger.warning(f"Output folder does not exist: {config.output_folder}")
        return results

    for file_name in os.listdir(config.output_folder):
        if file_name.endswith(".txt") and not file_name.endswith("_error.txt"):
            file_path = os.path.join(config.output_folder, file_name)
            try:
                analysis = analyze_transcription(file_path)
                results.append(analysis)
            except Exception as e:
                logger.error(f"Error analyzing {file_path}: {e}")

    return results


def find_original_video(audio_name: str) -> tuple[str | None, int | None, float | None]:
    """Find the original video file for a converted audio file."""
    base_name = os.path.splitext(audio_name)[0]

    for ext in config.supported_video_formats:
        video_path = os.path.join(config.video_folder, base_name + ext)
        if os.path.exists(video_path):
            return video_path, os.path.getsize(video_path), os.path.getmtime(video_path)

    return None, None, None


def analyze_converted_audio(file_path: str) -> ConvertedAudioAnalysis:
    """Analyze a converted audio file in the work folder."""
    file_size = os.path.getsize(file_path)
    file_mtime = os.path.getmtime(file_path)
    file_name = os.path.basename(file_path)
    base_name = os.path.splitext(file_name)[0]

    video_path, video_size, video_mtime = find_original_video(file_name)

    # Check if transcription exists for this audio
    transcription_path = os.path.join(config.output_folder, base_name + ".txt")
    has_transcription = os.path.exists(transcription_path)

    suspicion_reasons = []

    if video_path and video_size and video_mtime:
        # Check if video was modified AFTER audio was created
        # This suggests video was still being written when we converted it
        if video_mtime > file_mtime:
            time_diff = video_mtime - file_mtime
            suspicion_reasons.append(
                f"Video modified {time_diff:.0f}s after audio conversion (video was still writing)"
            )

        # Check size ratio - converted MP3 should be roughly proportional to video
        # Video at ~5Mbps, audio at 64kbps = ratio of ~80:1
        # But videos vary a lot, so we use a wide range
        expected_audio_min = video_size / 200  # Very compressed video
        expected_audio_max = video_size / 20   # High bitrate video

        if file_size < expected_audio_min:
            suspicion_reasons.append(
                f"Audio file suspiciously small ({file_size:,} bytes) for video ({video_size:,} bytes)"
            )

    # Check if audio file is very small (< 10KB suggests truncation)
    if file_size < 10000:
        suspicion_reasons.append(f"Audio file very small ({file_size:,} bytes)")

    return ConvertedAudioAnalysis(
        file_path=file_path,
        file_size=file_size,
        file_mtime=file_mtime,
        original_video_path=video_path,
        original_video_size=video_size,
        original_video_mtime=video_mtime,
        is_suspicious=len(suspicion_reasons) > 0,
        suspicion_reasons=suspicion_reasons,
        has_transcription=has_transcription,
    )


def analyze_work_folder() -> list[ConvertedAudioAnalysis]:
    """Analyze all converted audio files in the work folder."""
    results = []

    if not os.path.exists(config.work_folder):
        logger.warning(f"Work folder does not exist: {config.work_folder}")
        return results

    for file_name in os.listdir(config.work_folder):
        if file_name.lower().endswith(config.supported_audio_formats):
            file_path = os.path.join(config.work_folder, file_name)
            try:
                analysis = analyze_converted_audio(file_path)
                results.append(analysis)
            except Exception as e:
                logger.error(f"Error analyzing {file_path}: {e}")

    return results


def print_work_folder_report(analyses: list[ConvertedAudioAnalysis]) -> None:
    """Print analysis report for work folder."""
    print("\n" + "=" * 80)
    print("WORK FOLDER (CONVERTED AUDIO) ANALYSIS")
    print("=" * 80)

    suspicious = [a for a in analyses if a.is_suspicious]
    clean = [a for a in analyses if not a.is_suspicious]

    print(f"\nTotal converted audio files: {len(analyses)}")
    print(f"Suspicious: {len(suspicious)}")
    print(f"Clean: {len(clean)}")

    if suspicious:
        print("\n" + "-" * 40)
        print("SUSPICIOUS CONVERTED AUDIO (may need reconversion)")
        print("-" * 40)

        for analysis in suspicious:
            print(f"\n  File: {os.path.basename(analysis.file_path)}")
            print(f"  Size: {analysis.file_size:,} bytes")
            if analysis.original_video_size:
                print(f"  Original video: {analysis.original_video_size:,} bytes")
            print(f"  Has transcription: {'Yes' if analysis.has_transcription else 'No'}")
            print(f"  Issues:")
            for reason in analysis.suspicion_reasons:
                print(f"    - {reason}")

    print("\n" + "=" * 80)


def reconvert_suspicious_audio(
    analyses: list[ConvertedAudioAnalysis], dry_run: bool = True
) -> None:
    """
    Reconvert suspicious audio files by removing them from the work folder.
    Also removes corresponding transcriptions so they get reprocessed.
    """
    suspicious = [a for a in analyses if a.is_suspicious and a.original_video_path]

    if not suspicious:
        print("\nNo suspicious converted audio with available source videos to reconvert.")
        return

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Reconverting {len(suspicious)} suspicious audio files:")

    for analysis in suspicious:
        file_name = os.path.basename(analysis.file_path)
        base_name = os.path.splitext(file_name)[0]
        print(f"\n  {file_name}")
        print(f"    Reasons: {', '.join(analysis.suspicion_reasons)}")

        transcription_path = os.path.join(config.output_folder, base_name + ".txt")

        if dry_run:
            print(f"    Would remove audio: {analysis.file_path}")
            if analysis.has_transcription:
                print(f"    Would remove transcription: {transcription_path}")
        else:
            # Backup and remove audio
            backup_path = analysis.file_path + ".backup"
            shutil.copy2(analysis.file_path, backup_path)
            print(f"    Backed up audio to: {backup_path}")
            os.remove(analysis.file_path)
            print(f"    Removed audio: {analysis.file_path}")

            # Also remove transcription if it exists
            if analysis.has_transcription and os.path.exists(transcription_path):
                backup_txt = transcription_path + ".backup"
                shutil.copy2(transcription_path, backup_txt)
                print(f"    Backed up transcription to: {backup_txt}")
                os.remove(transcription_path)
                print(f"    Removed transcription: {transcription_path}")

            print(f"    Will be reconverted and retranscribed on next scan")


def print_analysis_report(analyses: list[TranscriptionAnalysis]) -> None:
    """Print a formatted analysis report."""
    print("\n" + "=" * 80)
    print("TRANSCRIPTION ANALYSIS REPORT")
    print("=" * 80)

    suspicious = [a for a in analyses if a.is_suspicious]
    clean = [a for a in analyses if not a.is_suspicious]

    print(f"\nTotal files: {len(analyses)}")
    print(f"Suspicious: {len(suspicious)}")
    print(f"Clean: {len(clean)}")

    if suspicious:
        print("\n" + "-" * 40)
        print("SUSPICIOUS TRANSCRIPTIONS (may need reprocessing)")
        print("-" * 40)

        for analysis in suspicious:
            print(f"\n  File: {os.path.basename(analysis.file_path)}")
            print(f"  Size: {analysis.file_size} bytes, Words: {analysis.word_count}")
            if analysis.source_size:
                print(f"  Source: {analysis.source_size:,} bytes")
            print(f"  Issues:")
            for reason in analysis.suspicion_reasons:
                print(f"    - {reason}")

    print("\n" + "-" * 40)
    print("SUMMARY SUGGESTIONS")
    print("-" * 40)

    for analysis in analyses:
        file_name = os.path.basename(analysis.file_path)
        # Check if file already has a summary suffix (contains " - ")
        if " - " in file_name and not file_name.startswith("20"):
            continue  # Already has a suffix
        base = os.path.splitext(file_name)[0]
        if " - " in base:
            continue  # Already has a suffix

        if analysis.suggested_summary:
            print(f"\n  {file_name}")
            print(f"    Suggested: {base} - {analysis.suggested_summary}.txt")

    print("\n" + "=" * 80)


def reprocess_suspicious(analyses: list[TranscriptionAnalysis], dry_run: bool = True) -> None:
    """
    Reprocess suspicious transcriptions by removing the output file
    so the next scan will re-transcribe them.
    """
    suspicious = [a for a in analyses if a.is_suspicious and a.source_file]

    if not suspicious:
        print("\nNo suspicious transcriptions with available source files to reprocess.")
        return

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Reprocessing {len(suspicious)} suspicious transcriptions:")

    for analysis in suspicious:
        file_name = os.path.basename(analysis.file_path)
        print(f"\n  {file_name}")
        print(f"    Reasons: {', '.join(analysis.suspicion_reasons)}")

        if dry_run:
            print(f"    Would remove: {analysis.file_path}")
        else:
            # Create backup
            backup_path = analysis.file_path + ".backup"
            shutil.copy2(analysis.file_path, backup_path)
            print(f"    Backed up to: {backup_path}")

            # Remove the transcription so it gets reprocessed
            os.remove(analysis.file_path)
            print(f"    Removed: {analysis.file_path}")
            print(f"    Will be reprocessed on next scan")


def rename_with_summaries(analyses: list[TranscriptionAnalysis], dry_run: bool = True) -> None:
    """Rename transcription files to include summary suffixes."""
    renamed_count = 0

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Renaming transcriptions with summaries:")

    for analysis in analyses:
        if not analysis.suggested_summary:
            continue

        file_name = os.path.basename(analysis.file_path)
        base_name = os.path.splitext(file_name)[0]

        # Skip if already has a summary suffix
        if " - " in base_name:
            continue

        # Create new filename with summary
        safe_summary = re.sub(r'[<>:"/\\|?*]', "", analysis.suggested_summary)  # Remove invalid chars
        safe_summary = safe_summary[:50]  # Limit length
        new_name = f"{base_name} - {safe_summary}.txt"
        new_path = os.path.join(os.path.dirname(analysis.file_path), new_name)

        print(f"\n  {file_name}")
        print(f"    -> {new_name}")

        if not dry_run:
            # Also rename corresponding audio file in work folder if it exists
            if analysis.source_file and analysis.source_file.startswith(config.work_folder):
                source_base = os.path.splitext(os.path.basename(analysis.source_file))[0]
                source_ext = os.path.splitext(analysis.source_file)[1]
                new_source_name = f"{source_base} - {safe_summary}{source_ext}"
                new_source_path = os.path.join(config.work_folder, new_source_name)

                if os.path.exists(analysis.source_file):
                    os.rename(analysis.source_file, new_source_path)
                    print(f"    Renamed audio: {new_source_name}")

            os.rename(analysis.file_path, new_path)
            renamed_count += 1

    print(f"\n{'Would rename' if dry_run else 'Renamed'}: {renamed_count} files")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze and reprocess transcriptions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "action",
        choices=["analyze", "reprocess", "reconvert", "rename", "all"],
        help="Action to perform",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform changes (default is dry-run)",
    )
    parser.add_argument(
        "--repetition-only",
        action="store_true",
        help="Only reprocess files with repetition artifacts (skip 'duration unknown' only files)",
    )

    args = parser.parse_args()
    dry_run = not args.execute

    if dry_run and args.action in ("reprocess", "reconvert", "rename", "all"):
        print("\n*** DRY RUN MODE - No changes will be made ***")
        print("*** Use --execute to apply changes ***\n")

    # Always analyze transcriptions first
    transcription_analyses = analyze_all_transcriptions()

    # Also analyze work folder
    work_folder_analyses = analyze_work_folder()

    # Filter if --repetition-only is set
    if args.repetition_only:
        transcription_analyses = [
            a for a in transcription_analyses
            if any("Repetition" in r for r in a.suspicion_reasons)
        ]

    if args.action == "analyze" or args.action == "all":
        print_analysis_report(analyze_all_transcriptions())  # Show full report
        print_work_folder_report(work_folder_analyses)

    if args.action == "reprocess" or args.action == "all":
        reprocess_suspicious(transcription_analyses, dry_run=dry_run)

    if args.action == "reconvert" or args.action == "all":
        reconvert_suspicious_audio(work_folder_analyses, dry_run=dry_run)

    if args.action == "rename" or args.action == "all":
        rename_with_summaries(analyze_all_transcriptions(), dry_run=dry_run)


if __name__ == "__main__":
    main()
