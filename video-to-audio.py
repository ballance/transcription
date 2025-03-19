import os
from moviepy.editor import VideoFileClip

import moviepy
print("moviepy is loaded from:", moviepy.__file__)

from moviepy.editor import VideoFileClip
print("moviepy.editor is loaded from:", moviepy.editor.__file__)


# Directories
input_dir = "raw_video"
output_dir = "raw_audio"

# Ensure the output directory exists
os.makedirs(output_dir, exist_ok=True)

# Process each file in the input directory
for filename in os.listdir(input_dir):
    if filename.lower().endswith(".mp4"):
        input_path = os.path.join(input_dir, filename)
        base_name, _ = os.path.splitext(filename)
        output_path = os.path.join(output_dir, base_name + ".wav")

        # Skip if output file already exists
        if os.path.exists(output_path):
            print(f"Skipping {filename}: output already exists.")
            continue

        print(f"Processing {filename}...")

        # Extract audio and write to WAV file
        video = VideoFileClip(input_path)
        audio = video.audio
        audio.write_audiofile(output_path)
        video.close()
        
        print(f"Saved audio to {output_path}")