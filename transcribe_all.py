import os
import time
import whisper

# Define the folders for input and output.
input_folder = "./work"
output_folder = "./transcribed"

# Load the pre-trained Whisper model (choose a model size that suits your needs).
model = whisper.load_model("large")

def transcribe_file(input_file):
    """Transcribe a single audio file if it has not yet been processed."""
    # Get the base file name without extension.
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    # Define the output file path with the same naming convention but .txt extension.
    output_file = os.path.join(output_folder, base_name + ".txt")
    
    # Check if transcription already exists.
    if os.path.exists(output_file):
        #print(f"Skipping '{input_file}'; transcription already exists.")
        return
    
    print(f"Transcribing '{input_file}'...")
    # Transcribe the audio file.
    result = model.transcribe(input_file, 
        verbose=True,
        language="en")
    
    # Save the transcribed text.
    with open(output_file, "w", encoding="utf-8") as txt:
        txt.write(result["text"])
    print(f"Finished transcribing '{input_file}' to '{output_file}'.")

def scan_folder():
    """Scan the input folder for new files and transcribe them."""
    # List all files in the input folder.
    for file_name in os.listdir(input_folder):
        # Process only files with the .m4v extension (adjust as needed).
        if file_name.lower().endswith((".m4v", ".mp3", ".wav")):
            input_file = os.path.join(input_folder, file_name)
            transcribe_file(input_file)

if __name__ == "__main__":
    # Ensure output folder exists.
    os.makedirs(output_folder, exist_ok=True)
    
    print("Starting folder scan. Press Ctrl+C to stop.")
    try:
        # Continuously scan for new files.
        while True:
            scan_folder()
            # Sleep for 30 seconds before scanning again (adjust time as needed).
            time.sleep(30)
    except KeyboardInterrupt:
        print("Stopped folder scanning.")
