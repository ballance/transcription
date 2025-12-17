# Audio-to-Text Transcription with OpenAI Whisper

This Python script transcribes an input audio file to text using OpenAI's Whisper library. It processes an audio file, extracts the transcription, and saves the output to a text file.

---

## Script Features

### Single File Transcription (`transcribe.py`)
- Command-line interface for transcribing individual audio files
- Configurable model size (tiny, base, small, medium, large)
- Language detection and specification support
- Metadata included in output (file info, duration, timestamp, etc.)
- Progress logging and error handling
- Environment variable configuration support

### Batch Processing with File Watcher (`transcribe_all.py`)
- Continuously monitors a folder for new audio files
- Automatic transcription of multiple files
- Skip already transcribed files
- Comprehensive logging to file and console
- Configurable scan interval
- Graceful error handling and cleanup

### Supported Features
- Leverages OpenAI's Whisper model LOCALLY for transcription
- Supports various audio formats: `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`, `.aac`, `.m4v` (via FFmpeg)
- Saves transcribed text with metadata headers
- Environment variable configuration

## API Features

- Hosts a `/transcribe/` endpoint that accepts an audio file input and returns the transcribed text
- Built with FastAPI for high performance
- Automatic cleanup of temporary files
- Comprehensive error handling

---

## Requirements

Before running the script, ensure the following requirements are met:

1. **Python**: Version 3.8 or higher.
2. **FFmpeg**: Required for audio processing (Whisper dependency).
3. **Dependencies**: Listed in `requirements.txt`

---

## Installation

1. Clone this repository or download the script.
2. Install FFmpeg (if not already installed):
   - **macOS**: `brew install ffmpeg`
   - **Ubuntu/Debian**: `sudo apt update && sudo apt install ffmpeg`
   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html)
3. Create and activate a virtual environment:
   ```bash
   # Create virtual environment
   python3 -m venv .venv

   # Activate virtual environment
   # On macOS/Linux:
   source .venv/bin/activate

   # On Windows:
   .venv\Scripts\activate
   ```
4. Install the required Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Script Usage

**Note**: Make sure your virtual environment is activated before running any scripts:
```bash
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate  # On Windows
```

### Single File Transcription

Use `transcribe.py` for transcribing individual audio files:

```bash
# Basic usage - transcribe to ./transcribed/ folder
python transcribe.py audio.mp3

# Specify output file
python transcribe.py audio.mp3 -o custom_output.txt

# Use a different model size (base is faster, large is more accurate)
python transcribe.py audio.mp3 -m base

# Transcribe Spanish audio
python transcribe.py audio.mp3 -l es

# Auto-detect language
python transcribe.py audio.mp3 -l auto

# Show verbose progress
python transcribe.py audio.mp3 -v

# View help and all options
python transcribe.py --help
```

### Batch Processing with File Watcher

Use `transcribe_all.py` to continuously monitor and transcribe files:

```bash
# Start the file watcher (monitors ./work folder by default)
python transcribe_all.py

# The script will:
# - Monitor the ./work folder for audio files
# - Automatically transcribe new files to ./transcribed/
# - Skip files that have already been transcribed
# - Log all activity to transcription.log
# - Check for new files every 30 seconds
```

### Environment Variables

Configure the scripts using environment variables:

```bash
# Set input folder for batch processing (transcribe_all.py)
export TRANSCRIBE_INPUT_FOLDER="./my_audio_files"

# Set output folder for transcriptions
export TRANSCRIBE_OUTPUT_FOLDER="./my_transcriptions"

# Set default Whisper model size (tiny, base, small, medium, large)
export WHISPER_MODEL_SIZE="medium"

# Set scan interval in seconds (transcribe_all.py only)
export SCAN_INTERVAL="60"
```

## Examples

### Example 1: Single File Transcription
Transcribe a podcast episode:
```bash
python transcribe.py podcast-episode-01.mp3
```
Output: `./transcribed/podcast-episode-01.txt` with metadata and transcription

### Example 2: Batch Processing
Monitor a folder and automatically transcribe all audio files:
```bash
# Place audio files in ./work folder
cp *.mp3 ./work/

# Start the watcher
python transcribe_all.py

# Output files will appear in ./transcribed/ as they're processed
```

### Example 3: Custom Configuration
Set up for Spanish transcription with smaller model:
```bash
export WHISPER_MODEL_SIZE="small"
python transcribe.py spanish-audio.mp3 -l es
```

### Output Format
Transcribed files include metadata headers:
```
# Transcription Metadata
# File: podcast-episode-01.mp3
# Size: 45.2MB
# Model: large
# Transcribed: 2025-01-11 14:30:00
# Duration: 1800 seconds
# Language: en

[Transcribed text content follows...]
```

## API Usage

### Running Locally

1. Activate the virtual environment (if not already activated):
   ```bash
   source .venv/bin/activate  # On macOS/Linux
   ```

2. Start the API server:
   ```bash
   uvicorn app:app --reload --host 0.0.0.0 --port 8000
   ```

3. The API will be available at `http://localhost:8000`

4. API Documentation is automatically available at:
   - Swagger UI: `http://localhost:8000/docs`
   - ReDoc: `http://localhost:8000/redoc`

### API Endpoint

**POST** `/transcribe/`

- **Description**: Transcribes an uploaded audio file to text
- **Content-Type**: `multipart/form-data`
- **Request Body**: Audio file (supported formats: wav, mp3, m4a, flac, etc.)
- **Response**: JSON object containing the transcribed text

Example using curl:
```bash
curl -X POST "http://localhost:8000/transcribe/" \
  -H "accept: application/json" \
  -F "file=@your_audio_file.mp3"
```

Example response:
```json
{
  "transcription": "This is the transcribed text from your audio file."
}
```

## Running the Application as a Dockerized API

You can also run this application as a Dockerized API. Follow the steps below to build and run the Docker container:

1. **Build the Docker Image**:

   Ensure you have [Docker installed](https://docs.docker.com/get-docker/). In the root directory of the repository, execute:

   ```bash
   docker build -t transcription-api .
   ```
   This command builds the Docker image and tags it as transcription-api.
   
2. **Run the Docker Container:**:
   After building the image, run the container with:
   ```bash
   docker run -d -p 8000:8000 transcription-api
   ```
   This command runs the container in detached mode, mapping port 8000 of the host to port 8000 of the container.

3. **Access the API**
   With the container running, access the API at `http://localhost:8000`

4. **Stopping the Container:**
To stop the running container, first identify its Container ID:
```bash
docker ps
```

Then stop it using 
```bash
docker stop <container_id>
```
Replace <container_id> with the actual ID from the docker ps output.

## Limitations

- Requires sufficient hardware resources for Whisper to transcribe efficiently.
- Large audio files may take considerable time to process.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgments
 - OpenAI for the Whisper library: [GitHub Repository](https://github.com/openai/whisper).

