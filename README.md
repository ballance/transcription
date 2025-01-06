# Audio-to-Text Transcription with OpenAI Whisper

This Python script transcribes an input audio file to text using OpenAI's Whisper library. It processes an audio file, extracts the transcription, and saves the output to a text file.

---

## Script Features

- Leverages OpenAI's Whisper model for transcription.
- Supports transcription of `.wav` audio files.
- Saves the transcribed text into a user-defined file for easy reference.

## API Features

 - Hosts a `/transcription` endpoint that accepts an audio file input and returns the transcribed text

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

## Script Usage
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

## Running the Application as a Dockerized API

You can now run this application as a Dockerized API. Follow the steps below to build and run the Docker container:

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
 - Currently supports .wav format only.
 - Requires sufficient hardware resources for Whisper to transcribe efficiently.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgments
 - OpenAI for the Whisper library: [GitHub Repository](https://github.com/openai/whisper).

