#!/usr/bin/env python3
"""Test script to verify transcription fixes."""

import os
import sys
import time
from pathlib import Path

# Import the transcribe_file function from our main script
from transcribe_all import transcribe_file

def test_transcription():
    """Test the transcription with the problematic file."""
    test_file = "./work/2025-08-27 09-59-54 product standup Wednesday_repaired.mp3"
    
    if not os.path.exists(test_file):
        print(f"Test file not found: {test_file}")
        print("Looking for audio files in work directory...")
        work_files = list(Path("./work").glob("*.mp3"))
        if work_files:
            test_file = str(work_files[0])
            print(f"Using file: {test_file}")
        else:
            print("No MP3 files found in work directory")
            return
    
    print(f"Testing transcription of: {test_file}")
    print(f"File size: {os.path.getsize(test_file) / (1024*1024):.1f}MB")
    
    # Call the transcribe function with the test file
    try:
        transcribe_file(test_file)
        print("Transcription completed or handled successfully")
    except Exception as e:
        print(f"Transcription failed with error: {e}")

if __name__ == "__main__":
    test_transcription()