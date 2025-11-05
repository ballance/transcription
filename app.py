from fastapi import FastAPI, UploadFile, File, HTTPException
import whisper
import os
import logging
logging.basicConfig(level=logging.DEBUG)

# Initialize the FastAPI app

print("App is initializing.") 
app = FastAPI()
print("FastAPI app initialized.") 

# Load the Whisper model
model = whisper.load_model("base")
print("Whisper model loaded.") 

@app.get("/")
async def root():
    """Root endpoint for basic connectivity check"""
    return {"status": "healthy", "service": "owl-web"}

@app.get("/health")
async def health_check():
    """Health check endpoint for ECS/ALB"""
    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "service": "owl-web"
    }

@app.post("/transcribe/")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Endpoint to transcribe an audio file to text.
    Accepts an uploaded audio file and returns the transcription.
    """
    try:
         # Read file contents to get its size
        file_content = await file.read()
        file_size = len(file_content)
        print(f"Uploaded file size: {file_size} bytes")

        # Reset the file pointer so it can be read again later
        await file.seek(0)
        
        # Save the uploaded file temporarily
        temp_file = f"./temp_{file.filename}"
        with open(temp_file, "wb") as f:
            f.write(await file.read())
        
        print("Temporary file written.") 

        print(f"Content type is: {file.content_type}") 
        # Ensure the file is a valid audio file
        if not (file.content_type.startswith("audio/") or file.content_type == "application/octet-stream"):
            os.remove(temp_file)
            print("MIME type validation failed.")
            raise HTTPException(status_code=400, detail="Uploaded file must be an audio file")

        print("File appears to be valid audio.") 

        # Transcribe the audio file
        result = model.transcribe(temp_file, verbose=True)

        print("Transcription completed.")
        
        # Clean up the temporary file
        os.remove(temp_file)
        
        # Return the transcription text
        return {"transcription": result["text"]}
    
    except Exception as e:
        # Handle errors and clean up the temporary file
        if os.path.exists(temp_file):
            os.remove(temp_file)
        print(f"Error during processing: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing the file: {str(e)}")