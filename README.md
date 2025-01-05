# Audio-to-Text Transcription with OpenAI Whisper

This Python script transcribes an input audio file to text using OpenAI's Whisper library. It processes an audio file, extracts the transcription, and saves the output to a text file.

---

## Features

- Leverages OpenAI's Whisper model for transcription.
- Supports transcription of `.wav` audio files.
- Saves the transcribed text into a user-defined file for easy reference.

---

## Requirements

Before running the script, ensure the following requirements are met:

1. **Python**: Version 3.8 or higher.
2. **Dependencies**:
   - `openai-whisper` library.

---

## Installation

1. Clone this repository or download the script.
2. Install the required library:
   ```bash
   pip install git+https://github.com/openai/whisper.git
3. Ensure your audio file is in .wav format and placed in the script’s directory.

## Usage
1.	Modify the script to specify your audio file and output text file:
 - Update the file_name variable to set the desired output text file name.
 - Replace "./house-of-sky-and-breath.wav" with the path to your audio file.
2.	Run the script:
   ```bash
   python ./transcription.py
  ```
3. Ensure your audio file is in .wav format and placed in the script’s directory.

## Example

Here’s an example of how to set up and run the script:

### Input
- Audio File: `house-of-sky-and-breath.wav`

### Script Configuration
```python
file_name = "house-of-sky-and-breath.txt"
model = whisper.load_model("base")
result = model.transcribe("./house-of-sky-and-breath.wav")
```

### Output
 - Transcription saved to `house-of-sky-and-breath.txt`

## Limitations
 - Currently supports .wav format only.
 - Requires sufficient hardware resources for Whisper to transcribe efficiently.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgments
 - OpenAI for the Whisper library: [GitHub Repository](https://github.com/openai/whisper).

