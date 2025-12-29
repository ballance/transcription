# Use slim Python image for smaller container size
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies (including Git and ffmpeg for Whisper)
RUN apt-get update && apt-get install -y \
    ffmpeg git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy only necessary files to avoid caching issues
COPY requirements.txt .

# Upgrade pip
RUN pip install --upgrade pip

# Install CPU-only PyTorch first (much smaller ~200MB vs ~3GB for CUDA)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install remaining Python dependencies
RUN pip install --no-cache-dir --timeout=300 --retries=5 -r requirements.txt

# Copy the rest of the application files into the container
COPY . .

# Expose the port your app runs on
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
