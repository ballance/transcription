# Audio-to-Text Transcription with OpenAI Whisper

[![CI/CD](https://github.com/ballance/transcription/actions/workflows/ci.yml/badge.svg)](https://github.com/ballance/transcription/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A production-ready transcription service powered by OpenAI's Whisper, featuring asynchronous job processing, intelligent model pooling, and a RESTful API.

---

## Security Notice for Production Use

**This repository is a technical demonstration of async transcription architecture.**

While security foundations are in place, additional hardening is recommended before handling sensitive data in production.

**Current security features:**
- API key authentication with SHA-256 hashing
- Rate limiting (100 requests/minute per API key)
- PII-safe logging with automatic redaction (SSN, credit cards, emails, phones)
- Immutable audit trail with cryptographic hash chain for tamper detection
- HTTPS redirect middleware for production deployments

**Not yet implemented (see [SECURITY.md](SECURITY.md) for roadmap):**
- Role-Based Access Control (RBAC)
- Multi-factor authentication (MFA)
- Encryption at rest
- Full CJIS/HIPAA compliance certification

**This demonstration focuses on:**
- Async job queue architecture
- Model pooling for performance
- Distributed task processing
- Database-backed job tracking

---

## Overview

This service provides multiple ways to transcribe audio/video files:

1. **🚀 Async API** - RESTful API with job queue for on-demand, concurrent transcription
2. **📁 Batch CLI** - Folder monitoring script for automated batch processing
3. **⚡ Single File CLI** - Simple command-line tool for individual files

### Key Features

#### Production-Ready Async API
- ✅ **Non-blocking job submission** - API returns immediately with job_id (202 Accepted)
- ✅ **Concurrent processing** - Multiple transcriptions run in parallel (2-4 simultaneous)
- ✅ **Model pooling** - Zero reload overhead, 4-8x throughput improvement
- ✅ **Job tracking** - Full lifecycle management with PostgreSQL persistence
- ✅ **Auto-retry** - Exponential backoff, audio repair, OOM fallback to smaller models
- ✅ **Dead Letter Queue** - Error tracking and resolution monitoring
- ✅ **Admin endpoints** - Health checks, pool statistics, error monitoring
- ✅ **Docker Compose** - One-command deployment of full stack

#### Local CLI Tools
- ✅ **Single file transcription** - Command-line tool for individual files
- ✅ **Folder monitoring** - Automated batch processing with file watcher
- ✅ **Flexible configuration** - Environment variables and .env file support
- ✅ **Multi-format support** - Audio (mp3, wav, m4a, flac) and video (mp4, mkv, m4v)

---

## Quick Start (Docker Compose - Recommended)

### Prerequisites
- Docker & Docker Compose installed
- At least 8GB RAM (16GB recommended for large model)
- 10GB free disk space

### 1. Clone and Configure

```bash
git clone <repository-url>
cd transcription

# Create .env file
cat > .env << 'EOF'
DB_PASSWORD=transcription
WHISPER_MODEL_SIZE=tiny      # Options: tiny, base, small, medium, large
MODEL_POOL_SIZE=2            # Base number of models in pool
MODEL_POOL_MAX_SIZE=4        # Max models before eviction
CELERY_CONCURRENCY=2         # Concurrent worker processes
EOF
```

### 2. Start the Stack

```bash
# Build and start all services
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f
```

### 3. Run Database Migrations

```bash
docker-compose exec web alembic upgrade head
```

### 4. Test the API

```bash
# Health check
curl http://localhost:8000/health

# Submit a transcription job
curl -X POST "http://localhost:8000/transcribe/" \
  -F "file=@your_audio.mp3" \
  -F "language=en"

# Response: {"job_id": "abc-123...", "status": "pending", ...}

# Check job status
curl "http://localhost:8000/transcribe/{job_id}"

# List all jobs
curl "http://localhost:8000/jobs/"
```

**Services Running:**
- **API** - http://localhost:8000 (FastAPI web server)
- **Swagger Docs** - http://localhost:8000/docs
- **Flower** - http://localhost:5555 (Celery monitoring)
- **PostgreSQL** - localhost:5432
- **Redis** - localhost:6380

For detailed setup, testing, and troubleshooting, see **[SETUP.md](SETUP.md)**.

---

## Architecture

```
User → FastAPI → PostgreSQL → Redis → Celery Workers → Model Pool → Whisper
                                                                      ↓
User ← Poll /transcribe/{job_id} ←──────── PostgreSQL (Results) ←────┘
```

**Components:** FastAPI (async API), PostgreSQL (job tracking), Redis (message broker), Celery (task queue), Model Pool (thread-safe Whisper cache), Docker Compose (orchestration).

> **For detailed architecture diagrams and code-level documentation, see [agents.md](agents.md).**

---

## API Endpoints

### Core Endpoints

#### Submit Transcription Job
```bash
POST /transcribe/
```
- **Returns**: 202 Accepted with job_id
- **Body**: multipart/form-data
  - `file`: Audio/video file
  - `model_size`: (optional) tiny, base, small, medium, large
  - `language`: (optional) Language code (e.g., "en", "es") or "auto"

**Example:**
```bash
curl -X POST "http://localhost:8000/transcribe/" \
  -F "file=@audio.mp3" \
  -F "model_size=small" \
  -F "language=en"
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Transcription job submitted successfully..."
}
```

#### Get Job Status
```bash
GET /transcribe/{job_id}
```

**Response (processing):**
```json
{
  "job_id": "550e8400-...",
  "status": "processing",
  "progress": 45.0,
  "current_step": "Transcribing audio",
  "created_at": "2025-01-11T10:30:00",
  "model_size": "small"
}
```

**Response (completed):**
```json
{
  "job_id": "550e8400-...",
  "status": "completed",
  "progress": 100.0,
  "transcription": "This is the transcribed text...",
  "language": "en",
  "duration": 180.5,
  "word_count": 245,
  "completed_at": "2025-01-11T10:35:00"
}
```

#### Cancel Job
```bash
DELETE /transcribe/{job_id}
```

#### List Jobs
```bash
GET /jobs/?status=completed&limit=50
```

### Admin Endpoints

#### Health Check
```bash
GET /health
```

#### Comprehensive Health Check
```bash
GET /admin/health
```
Returns database status, queue depths, model pool statistics, error rates.

#### View Errors (Dead Letter Queue)
```bash
GET /admin/errors?limit=50&resolved=false
```

---

## Local Development (Without Docker)

### Prerequisites
- Python 3.9+
- PostgreSQL 15+
- Redis 7+
- FFmpeg

### Installation

```bash
# 1. Install system dependencies
# macOS:
brew install postgresql@15 redis ffmpeg

# Ubuntu/Debian:
sudo apt update && sudo apt install postgresql redis ffmpeg

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Set environment variables
export DATABASE_URL="postgresql://transcription:transcription@localhost/transcription"
export REDIS_URL="redis://localhost:6379/0"
export WHISPER_MODEL_SIZE="small"

# 5. Create database
createdb transcription

# 6. Run migrations
alembic upgrade head
```

### Running Services

```bash
# Terminal 1 - PostgreSQL (if using Homebrew)
brew services start postgresql@15

# Terminal 2 - Redis
redis-server

# Terminal 3 - API Server
uvicorn app:app --reload --port 8000

# Terminal 4 - Celery Worker
python worker.py

# Terminal 5 - Flower (optional)
celery -A celery_app flower
```

---

## CLI Tools (Standalone - No Docker Required)

The CLI tools work independently of the API and are useful for local batch processing.

### Single File Transcription

```bash
# Activate virtual environment
source .venv/bin/activate

# Basic usage
python transcribe.py audio.mp3

# Specify output file
python transcribe.py audio.mp3 -o output.txt

# Use different model
python transcribe.py audio.mp3 -m small

# Specify language
python transcribe.py audio.mp3 -l es

# Auto-detect language
python transcribe.py audio.mp3 -l auto

# Verbose mode
python transcribe.py audio.mp3 -v
```

### Batch Folder Monitoring

```bash
# Start folder watcher
python transcribe_all.py

# The script will:
# - Monitor ./work folder for audio/video files
# - Automatically transcribe new files to ./transcribed/
# - Skip already transcribed files
# - Log activity to transcription.log
# - Scan every 30 seconds (configurable)
```

**When to Use Each:**

| Tool | Use Case |
|------|----------|
| **API** | On-demand transcription, concurrent processing, programmatic access |
| **transcribe_all.py** | Automated folder monitoring, batch processing, "set and forget" |
| **transcribe.py** | Quick single-file transcription, testing, simple workflows |

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://...` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `WHISPER_MODEL_SIZE` | `tiny` | Model size (tiny, base, small, medium, large) |
| `MODEL_POOL_SIZE` | `2` | Base number of models in pool |
| `MODEL_POOL_MAX_SIZE` | `4` | Maximum models before LRU eviction |
| `CELERY_CONCURRENCY` | `2` | Concurrent worker processes |
| `CELERY_TASK_TIMEOUT` | `3600` | Task timeout (seconds) |
| `MAX_UPLOAD_SIZE_MB` | `500` | Maximum upload file size |
| `TRANSCRIBE_VIDEO_FOLDER` | `~/Movies` | Folder for videos (CLI) |
| `TRANSCRIBE_AUDIO_FOLDER` | `./work` | Folder for audio (CLI) |
| `TRANSCRIBE_OUTPUT_FOLDER` | `./transcribed` | Output folder (CLI) |
| `SCAN_INTERVAL` | `30` | Folder scan interval (CLI) |
| `SKIP_FILES_BEFORE_DATE` | `2025-12-01` | Skip old files (CLI) |

### Model Size Recommendations

| Model | Accuracy | Speed | RAM | Best For |
|-------|----------|-------|-----|----------|
| **tiny** | ⭐⭐ | ⚡⚡⚡⚡ | 1GB | Testing, drafts |
| **base** | ⭐⭐⭐ | ⚡⚡⚡ | 1GB | Quick transcripts |
| **small** | ⭐⭐⭐⭐ | ⚡⚡ | 2GB | Balance speed/accuracy ⭐ |
| **medium** | ⭐⭐⭐⭐ | ⚡ | 5GB | High accuracy |
| **large** | ⭐⭐⭐⭐⭐ | ⚡ | 10GB | Best accuracy |

---

## Performance Benchmarks

### Before (Synchronous API)
- API response time: **5-30 minutes** (blocking)
- Concurrent transcriptions: **1** (sequential only)
- Model reload overhead: **15-30 seconds** per file
- Throughput: **2-3 files/hour**

### After (Async + Model Pool)
- API response time: **<500ms** (returns job_id immediately)
- Concurrent transcriptions: **2-4** simultaneous
- Model reload overhead: **0 seconds** (reused from pool)
- Throughput: **10-20 files/hour** (4-8x improvement!)

---

## Supported Formats

**Audio:** `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`, `.aac`
**Video:** `.mp4`, `.mkv`, `.m4v` (audio extracted via FFmpeg)

---

## Troubleshooting

```bash
docker-compose ps              # Check service status
docker-compose logs worker     # View worker logs
docker-compose restart worker  # Restart worker
curl http://localhost:8000/admin/health | jq  # System health
```

**Common fixes:**
- Jobs stuck in "pending" → Check worker is running, restart if needed
- Out of memory → Reduce `WHISPER_MODEL_SIZE`, `MODEL_POOL_SIZE`, `CELERY_CONCURRENCY`

For detailed troubleshooting, see **[SETUP.md](SETUP.md)** and **[agents.md](agents.md#debugging-tips)**.

---

## Project Structure

**Core:** `app.py` (API), `worker.py`, `celery_app.py`, `tasks.py`, `model_pool.py`
**Data:** `models.py`, `database.py`, `config.py`, `migrations/`
**CLI:** `transcribe.py`, `transcribe_all.py`
**Ops:** `docker-compose.yml`, `Dockerfile`, `requirements.txt`
**Docs:** `README.md`, `SETUP.md`, `SECURITY.md`, `agents.md`

> **For detailed file-by-file documentation, see [agents.md](agents.md#key-files--their-responsibilities).**

---

## Development Roadmap

### ✅ Completed (Phase 1 & 2)
- [x] Async job queue (Celery + Redis)
- [x] Model pooling with LRU eviction
- [x] PostgreSQL job tracking
- [x] Dead Letter Queue for errors
- [x] Auto-retry with exponential backoff
- [x] OOM fallback to smaller models
- [x] Docker Compose deployment
- [x] Admin health endpoints
- [x] API documentation

### 🚧 Future Enhancements
- [ ] Speaker diarization (who spoke when)
- [ ] Custom vocabulary/terminology
- [ ] Multi-language auto-detection
- [ ] Real-time streaming transcription
- [ ] Translation to other languages
- [ ] Text summarization
- [ ] Sentiment analysis
- [ ] WebSocket support for live progress
- [ ] Horizontal worker scaling
- [ ] Prometheus metrics & Grafana dashboards
- [ ] Comprehensive test suite (pytest)

---

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request with clear description

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- **OpenAI Whisper** - [GitHub Repository](https://github.com/openai/whisper)
- **FastAPI** - Modern async web framework
- **Celery** - Distributed task queue
- **SQLAlchemy** - Python SQL toolkit

---

## Support

For detailed setup instructions, testing guide, and troubleshooting: **[SETUP.md](SETUP.md)**

For questions or issues, please open a GitHub issue.
