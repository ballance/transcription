#!/usr/bin/env python
"""
Rename transcript files based on content summary without triggering reprocessing.

Creates symlinks from original names to renamed files so the processing system
still finds the expected filename and skips reprocessing.
"""

import os
import re
import sys
from pathlib import Path

# Configuration
TRANSCRIBED_FOLDER = "./transcribed"
MAX_SUMMARY_LENGTH = 40  # Max characters for summary portion


def extract_content(file_path: str) -> str:
    """Extract transcript content, skipping metadata header."""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Skip metadata lines (start with #) and empty lines
    content_lines = []
    in_content = False
    for line in lines:
        if not line.startswith('#') and line.strip():
            in_content = True
        if in_content:
            content_lines.append(line.strip())

    return ' '.join(content_lines[:50])  # First ~50 lines of content


def suggest_summary(content: str) -> str:
    """Generate a short summary suggestion from content."""
    # Clean up the content
    content = content.replace('\n', ' ').strip()

    # Look for common meeting patterns
    patterns = [
        r"(?:talk(?:ing)?|discuss(?:ing)?|about|regarding|for|on)\s+([A-Z][a-zA-Z\s]{3,30})",
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\s+(?:meeting|sync|standup|call)",
        r"(?:work(?:ing)?\s+on|working\s+on)\s+([A-Za-z\s]{3,25})",
    ]

    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            summary = match.group(1).strip()
            if len(summary) > 3:
                return summary[:MAX_SUMMARY_LENGTH]

    # Fall back to first few words after common greetings
    content = re.sub(r'^(hey|hi|hello|okay|alright|so|um|uh|yeah|well)\s*[,.]?\s*', '', content, flags=re.I)
    content = re.sub(r'^(hey|hi|hello|okay|alright|so|um|uh|yeah|well)\s*[,.]?\s*', '', content, flags=re.I)

    # Get first substantive phrase
    words = content.split()[:8]
    return ' '.join(words)[:MAX_SUMMARY_LENGTH] if words else "Unknown"


def get_original_name(filename: str) -> str:
    """Extract the original base name (timestamp portion) from a filename."""
    # Pattern: "YYYY-MM-DD HH-MM-SS" possibly followed by " - Summary"
    match = re.match(r'^(\d{4}-\d{2}-\d{2}\s+\d{2}-\d{2}-\d{2})', filename)
    if match:
        return match.group(1)
    # If no timestamp pattern, return filename without extension
    return os.path.splitext(filename)[0]


def is_already_renamed(filename: str) -> bool:
    """Check if file already has a summary suffix."""
    base = os.path.splitext(filename)[0]
    return ' - ' in base and re.match(r'^\d{4}-\d{2}-\d{2}\s+\d{2}-\d{2}-\d{2}\s+-\s+', base)


def rename_with_symlink(folder: str, old_name: str, new_name: str) -> bool:
    """Rename file and create symlink from original name."""
    old_path = os.path.join(folder, old_name)
    new_path = os.path.join(folder, new_name)

    # Get the original timestamp-based name for symlink
    original_base = get_original_name(old_name)
    symlink_name = original_base + ".txt"
    symlink_path = os.path.join(folder, symlink_name)

    try:
        # Rename the file
        os.rename(old_path, new_path)

        # Create symlink from original name to new name (if different)
        if symlink_name != new_name and not os.path.exists(symlink_path):
            # Create relative symlink
            os.symlink(new_name, symlink_path)
            print(f"  Created symlink: {symlink_name} -> {new_name}")

        return True
    except Exception as e:
        print(f"  Error: {e}")
        # Try to restore if rename succeeded but symlink failed
        if os.path.exists(new_path) and not os.path.exists(old_path):
            os.rename(new_path, old_path)
        return False


def main():
    folder = Path(TRANSCRIBED_FOLDER)
    if not folder.exists():
        print(f"Folder not found: {folder}")
        sys.exit(1)

    # Get all .txt files (not symlinks, not backups)
    txt_files = [
        f for f in os.listdir(folder)
        if f.endswith('.txt')
        and not f.endswith('.backup')
        and not os.path.islink(folder / f)
    ]

    # Sort by modification time (newest first)
    txt_files.sort(key=lambda f: os.path.getmtime(folder / f), reverse=True)

    if not txt_files:
        print("No transcript files found.")
        return

    print(f"Found {len(txt_files)} transcript files.\n")

    renamed_count = 0
    skipped_count = 0

    for filename in txt_files:
        file_path = folder / filename

        # Skip already renamed files
        if is_already_renamed(filename):
            print(f"[SKIP] {filename} (already has summary)")
            skipped_count += 1
            continue

        # Extract content and suggest summary
        content = extract_content(str(file_path))
        if not content.strip():
            print(f"[SKIP] {filename} (empty content)")
            skipped_count += 1
            continue

        suggested = suggest_summary(content)

        # Build new filename
        base_name = get_original_name(filename)
        new_filename = f"{base_name} - {suggested}.txt"

        print(f"\nFile: {filename}")
        print(f"Preview: {content[:200]}...")
        print(f"\nSuggested: {new_filename}")

        # Ask user
        response = input("Accept (y), edit (e), skip (s/Enter)? ").strip().lower()

        if response == 'y':
            if rename_with_symlink(str(folder), filename, new_filename):
                print(f"  Renamed to: {new_filename}")
                renamed_count += 1
            else:
                print("  Failed to rename")
        elif response == 'e':
            custom = input("Enter summary (will be added after timestamp): ").strip()
            if custom:
                new_filename = f"{base_name} - {custom}.txt"
                if rename_with_symlink(str(folder), filename, new_filename):
                    print(f"  Renamed to: {new_filename}")
                    renamed_count += 1
                else:
                    print("  Failed to rename")
            else:
                print("  Skipped (empty input)")
                skipped_count += 1
        else:
            print("  Skipped")
            skipped_count += 1

    print(f"\n--- Summary ---")
    print(f"Renamed: {renamed_count}")
    print(f"Skipped: {skipped_count}")


if __name__ == '__main__':
    main()
