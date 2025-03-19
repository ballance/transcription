import whisper

output_file_name = "./transcribed/house-of-sky-and-breath.txt"

# Load the pre-trained Whisper model. Models come in various sizes (tiny, base, small, medium, large).
# Larger models provide better accuracy but require more computational resources.
model = whisper.load_model("large")

# Transcribe the audio file and store the result
result = model.transcribe("./house-of-sky-and-breath.wav", verbose=True)

# Save the transcribed text to an output file with UTF-8 encoding
with open(output_file_name, "w", encoding="utf-8") as txt:
    txt.write(result["text"])
