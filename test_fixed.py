#!/usr/bin/env python3
"""Test transcription of the fixed audio file."""

import whisper
import os

file_path = "./work/2025-08-27 09-59-54 product standup Wednesday_repaired_fixed.mp3"

if os.path.exists(file_path):
    print(f"Testing file: {file_path}")
    print(f"File size: {os.path.getsize(file_path) / (1024*1024):.1f}MB")
    
    print("Loading Whisper model (base for quick test)...")
    model = whisper.load_model("base")
    
    print("Starting transcription...")
    try:
        result = model.transcribe(file_path, fp16=False, language="en")
        print("Success! First 500 characters of transcription:")
        print(result["text"][:500])
        
        # Save full transcription
        output_file = "./transcribed/2025-08-27_product_standup_test.txt"
        with open(output_file, "w") as f:
            f.write(result["text"])
        print(f"\nFull transcription saved to: {output_file}")
        
    except Exception as e:
        print(f"Error: {e}")
else:
    print(f"File not found: {file_path}")