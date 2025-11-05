#!/usr/bin/env python3
"""Repair problematic audio file for transcription."""

import subprocess
import os
import sys

def repair_audio(input_file):
    """Aggressively repair audio file for Whisper compatibility."""
    
    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        return None
    
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_file = f"./work/{base_name}_fixed.mp3"
    
    print(f"Repairing: {input_file}")
    print(f"Output: {output_file}")
    
    try:
        # More aggressive repair: convert to WAV first, then to MP3
        # This often fixes corrupted audio streams
        wav_temp = f"./work/{base_name}_temp.wav"
        
        # Step 1: Convert to WAV with specific settings
        print("Step 1: Converting to WAV...")
        subprocess.run([
            "ffmpeg", "-y", "-i", input_file,
            "-acodec", "pcm_s16le",  # Standard PCM encoding
            "-ar", "16000",           # 16kHz sample rate (good for speech)
            "-ac", "1",               # Mono
            wav_temp
        ], check=True, capture_output=True)
        
        # Step 2: Convert WAV back to MP3
        print("Step 2: Converting WAV to MP3...")
        subprocess.run([
            "ffmpeg", "-y", "-i", wav_temp,
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            "-ab", "64k",
            output_file
        ], check=True, capture_output=True)
        
        # Clean up temp file
        if os.path.exists(wav_temp):
            os.remove(wav_temp)
            
        print(f"Successfully repaired: {output_file}")
        print(f"File size: {os.path.getsize(output_file) / (1024*1024):.1f}MB")
        
        return output_file
        
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e.stderr.decode() if e.stderr else str(e)}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    # Try to repair the problematic file
    problem_file = "./work/2025-08-27 09-59-54 product standup Wednesday_repaired.mp3"
    
    if not os.path.exists(problem_file):
        # Try the original file
        problem_file = "./work/2025-08-27 09-59-54 product standup Wednesday.mp3"
    
    if os.path.exists(problem_file):
        repaired = repair_audio(problem_file)
        if repaired:
            print(f"\nRepaired file created: {repaired}")
            print("You can now try transcribing this file.")
    else:
        print(f"Could not find file: {problem_file}")