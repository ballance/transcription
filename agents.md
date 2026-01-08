# Developer & AI Agent Guide

Technical reference for developers and AI agents working on the transcription service codebase.

> **For user documentation** (quick start, API usage, configuration): see [README.md](README.md)
> **For setup and deployment**: see [SETUP.md](SETUP.md)

---

## Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                         Client                               │
│                    (HTTP Requests)                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Web Server                        │
│                      (app.py)                                │
│  - POST /transcribe/  → Submit job (202 Accepted)           │
│  - GET /transcribe/{id} → Poll status                       │
│  - DELETE /transcribe/{id} → Cancel job                     │
│  - GET /jobs/ → List jobs                                   │
│  - GET /admin/health → System health                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   PostgreSQL Database                        │
│                    (models.py)                               │
│  Tables:                                                     │
│  - transcription_jobs (job lifecycle tracking)              │
│  - transcription_results (output storage)                   │
│  - error_logs (dead letter queue)                           │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Redis Message Broker                      │
│                   (celery_app.py)                            │
│  Queues:                                                     │
│  - transcription.high (priority jobs)                       │
│  - transcription.normal (standard jobs)                     │
│  - transcription.retry (failed jobs)                        │
│  - transcription.dlq (permanent failures)                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Celery Worker(s)                          │
│                   (worker.py, tasks.py)                      │
│  - Consumes tasks from queues                               │
│  - Acquires model from pool                                 │
│  - Transcribes audio                                        │
│  - Updates job status in DB                                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                     Model Pool                               │
│                   (model_pool.py)                            │
│  - Thread-safe Whisper model cache                          │
│  - LRU eviction policy                                      │
│  - OOM fallback to smaller models                          │
│  - Statistics tracking (hits/misses)                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Files & Their Responsibilities

### Core Application Files

#### `config.py`
**Purpose**: Centralized configuration management
- Reads environment variables
- Provides default values
- Type conversion and validation
- Used by all other modules

**Key Configuration:**
```python
database_url: str              # PostgreSQL connection
redis_url: str                 # Redis connection
model_size: str                # Default Whisper model (tiny/base/small/medium/large)
model_pool_size: int           # Base pool size (default: 2)
model_pool_max_size: int       # Max models before eviction (default: 4)
celery_worker_concurrency: int # Worker process count (default: 2)
```

#### `app.py`
**Purpose**: FastAPI async web server
- Defines all REST API endpoints
- Handles file uploads
- Creates job records in database
- Submits tasks to Celery queue
- Returns job status to clients

**Key Endpoints:**
- `POST /transcribe/` - Submit job (returns immediately with job_id)
- `GET /transcribe/{job_id}` - Poll job status/results
- `DELETE /transcribe/{job_id}` - Cancel pending/processing job
- `GET /jobs/` - List jobs with filtering
- `GET /health` - Basic health check
- `GET /admin/health` - Comprehensive system health
- `GET /admin/errors` - View dead letter queue

**Important**:
- API is non-blocking - returns 202 Accepted immediately
- No Whisper model is loaded in the web process
- All transcription happens asynchronously in workers

#### `models.py`
**Purpose**: SQLAlchemy database models
- Defines database schema
- Provides ORM for database operations

**Tables:**

1. **TranscriptionJob** - Main job tracking
   - Fields: id (UUID), status, progress, model_size, file_path, language, error_message, timestamps
   - Status values: pending, processing, completed, failed, cancelled

2. **TranscriptionResult** - Transcription output
   - Fields: job_id (FK), transcription_text, language, duration, word_count, confidence

3. **ErrorLog** - Dead Letter Queue
   - Fields: job_id (FK), error_type, error_message, retry_count, resolved, stack_trace

#### `database.py`
**Purpose**: Database connection and session management
- Creates SQLAlchemy engine with connection pooling
- Provides session factory (`SessionLocal`)
- Helper functions: `get_db()`, `get_db_session()`, `init_db()`, `check_db_connection()`
- Configures SQLite pragma for foreign keys (if using SQLite)

**Key Functions:**
```python
get_db()            # Generator for FastAPI dependency injection
get_db_session()    # Context manager with auto-commit/rollback
init_db()           # Create all tables (use Alembic in production)
check_db_connection() # Health check
get_db_stats()      # Connection pool statistics
```

#### `celery_app.py`
**Purpose**: Celery configuration and initialization
- Configures broker (Redis) and result backend
- Defines task routes and queues
- Sets retry policies and timeouts
- Configures task serialization

**Queue Configuration:**
- `transcription.high` - Priority queue for API requests
- `transcription.normal` - Standard queue
- `transcription.retry` - Failed jobs with retry logic
- `transcription.dlq` - Dead letter queue for permanent failures

**Key Settings:**
```python
task_acks_late = True           # Only ack after task completes
worker_prefetch_multiplier = 1  # Prevent task hoarding
task_soft_time_limit = 3600     # Soft timeout (1 hour)
task_time_limit = 3900          # Hard timeout (1h 5min)
```

#### `tasks.py`
**Purpose**: Celery task definitions
- Defines async transcription task
- Handles job lifecycle (pending → processing → completed/failed)
- Integrates with model pool
- Implements retry logic with exponential backoff
- Updates job status in database

**Main Task: `transcribe_audio_task`**
```python
@celery_app.task(bind=True, max_retries=5, retry_backoff=True)
def transcribe_audio_task(self, file_path, model_size, language, job_id):
    # 1. Update job status to "processing"
    # 2. Acquire model from pool (blocking if pool is full)
    # 3. Transcribe audio with Whisper
    # 4. Save result to database
    # 5. Update job status to "completed"
    # 6. Handle errors with retry/DLQ logic
```

**Error Handling:**
- Transient errors (network, OOM) → Retry with exponential backoff
- Corrupt audio → Attempt repair with FFmpeg, then retry
- Permanent failures → Move to Dead Letter Queue

#### `model_pool.py`
**Purpose**: Thread-safe Whisper model cache
- Eliminates model reload overhead (15-30s per file → 0s)
- Implements LRU eviction when pool is full
- Provides OOM fallback to smaller models
- Tracks hit/miss statistics

**Key Classes:**

1. **ModelInstance** - Wrapper for loaded Whisper model
   ```python
   model: Any              # The Whisper model
   model_size: str         # tiny/base/small/medium/large
   loaded_at: datetime     # When model was loaded
   last_used: datetime     # For LRU eviction
   use_count: int          # Usage statistics
   memory_mb: float        # Model memory footprint
   ```

2. **ModelPool** - Thread-safe model manager
   ```python
   acquire(model_size, timeout=300) → ModelInstance
   release(instance: ModelInstance)
   get_stats() → dict  # hits, misses, evictions, oom_fallbacks
   ```

**Usage Pattern:**
```python
# Context manager automatically releases model back to pool
with acquire_model(model_size='small') as model:
    result = model.transcribe(audio_file)
# Model is now available for reuse
```

#### `worker.py`
**Purpose**: Celery worker entry point
- Starts Celery worker process
- Configures worker concurrency
- Sets queue priorities
- Handles worker lifecycle

**Worker Configuration:**
```python
Concurrency: 2-4 processes (configurable via CELERY_CONCURRENCY)
Queues: high > normal > retry > dlq (priority order)
Pool: prefork (multi-process)
```

---

## Database Schema

### Job Lifecycle States

```
pending → processing → completed
                    ↓
                  failed → retry → processing
                                ↓
                              dlq (dead letter queue)
                    ↓
                cancelled
```

### Key Relationships

```sql
transcription_jobs (1) ←→ (0..1) transcription_results
transcription_jobs (1) ←→ (0..n) error_logs
```

---

## Common Development Tasks

### Adding a New API Endpoint

1. Define endpoint in `app.py`
2. Add database operations if needed (using `models.py`)
3. Update API documentation (FastAPI auto-generates from docstrings)
4. Test with curl or Swagger UI at `/docs`

Example:
```python
@app.get("/transcribe/{job_id}/metadata")
async def get_job_metadata(job_id: str, db: Session = Depends(get_db)):
    """Get job metadata without transcription text."""
    job = db.query(TranscriptionJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": str(job.id),
        "filename": job.original_filename,
        "status": job.status,
        "created_at": job.created_at,
        "model_size": job.model_size
    }
```

### Adding a New Celery Task

1. Define task in `tasks.py` with `@celery_app.task` decorator
2. Add task route in `celery_app.py` if using custom queue
3. Call task with `task_name.apply_async()` from API or other tasks
4. Test task execution via Flower UI or logs

Example:
```python
@celery_app.task(bind=True, max_retries=3)
def cleanup_old_files(self, days_old: int):
    """Delete files older than N days."""
    cutoff = datetime.now() - timedelta(days=days_old)
    # Implementation here
```

### Adding a Database Migration

1. Modify models in `models.py`
2. Generate migration:
   ```bash
   alembic revision --autogenerate -m "Description of change"
   ```
3. Review generated migration in `migrations/versions/`
4. Apply migration:
   ```bash
   alembic upgrade head
   ```

### Modifying Model Pool Behavior

File: `model_pool.py`

Common modifications:
- Adjust LRU eviction policy (`_evict_lru_model()`)
- Add new fallback strategies (`_fallback_to_smaller_model()`)
- Implement model warmup on worker startup
- Add memory pressure detection

### Adding Error Handling for New Error Types

1. Define error classifier in `tasks.py`
2. Add error handling in `transcribe_audio_task`
3. Update Dead Letter Queue handler (`dlq_handler_task`)
4. Add error type to ErrorLog model if needed

Example:
```python
except CustomErrorType as e:
    if should_retry(e):
        raise self.retry(exc=e, countdown=exponential_backoff())
    else:
        move_to_dlq(job_id, error=e)
```

---

## Testing

> **For basic API testing commands**, see [README.md](README.md#quick-start-docker-compose---recommended).

### Testing Model Pool

```bash
# Submit multiple concurrent jobs to test pool reuse
for i in {1..5}; do
  curl -X POST "http://localhost:8000/transcribe/" \
    -F "file=@test$i.mp3" &
done

# Check pool statistics
curl -s http://localhost:8000/admin/health | jq '.model_pool'

# Expected: High hit_rate on subsequent jobs after first loads model
```

### Testing Error Handling

```bash
# Submit corrupted file
echo "invalid" > corrupt.mp3
curl -X POST "http://localhost:8000/transcribe/" -F "file=@corrupt.mp3"

# Check DLQ
curl -s "http://localhost:8000/admin/errors" | jq
```

---

## Configuration Best Practices

> **For environment variable reference**, see [README.md](README.md#configuration).

### Development Environment

```bash
# .env for development
WHISPER_MODEL_SIZE=tiny        # Fast for testing
MODEL_POOL_SIZE=1              # Minimal memory usage
MODEL_POOL_MAX_SIZE=2
CELERY_CONCURRENCY=1           # Single worker
DATABASE_URL=postgresql://transcription:transcription@localhost/transcription
REDIS_URL=redis://localhost:6379/0
```

### Production Environment

```bash
# .env for production
WHISPER_MODEL_SIZE=medium      # Balance accuracy/speed
MODEL_POOL_SIZE=2              # Efficient model reuse
MODEL_POOL_MAX_SIZE=4          # Handle bursts
CELERY_CONCURRENCY=4           # Parallel processing
MAX_UPLOAD_SIZE_MB=1000        # Support large files
```

### Performance Tuning

**For high throughput:**
```bash
CELERY_CONCURRENCY=8           # More workers
MODEL_POOL_SIZE=4              # More cached models
MODEL_POOL_MAX_SIZE=8
WHISPER_MODEL_SIZE=small       # Faster processing
```

**For high accuracy:**
```bash
CELERY_CONCURRENCY=2           # Fewer workers (models are large)
MODEL_POOL_SIZE=2
MODEL_POOL_MAX_SIZE=3
WHISPER_MODEL_SIZE=large       # Best accuracy
```

**For low memory:**
```bash
CELERY_CONCURRENCY=1
MODEL_POOL_SIZE=1
MODEL_POOL_MAX_SIZE=2
WHISPER_MODEL_SIZE=tiny        # Smallest model
```

---

## Debugging Tips

### Check What's Running

```bash
# Docker processes
docker-compose ps

# Worker processes inside container
docker-compose exec worker ps aux | grep python

# Database connections
docker-compose exec postgres pg_stat_activity

# Redis queue depths
docker-compose exec redis redis-cli llen transcription.normal
```

### Common Issues

**Issue: Jobs stuck in "pending"**
- Check: Worker is running (`docker-compose ps worker`)
- Check: Worker logs for errors (`docker-compose logs worker`)
- Check: Redis connection (`docker-compose exec web redis-cli -h redis ping`)

**Issue: Model loading fails**
- Check: Sufficient disk space for model download
- Check: Network connectivity for model download
- Check: Memory available for model loading
- Fallback: Use smaller model size

**Issue: Database connection errors**
- Check: PostgreSQL is healthy (`docker-compose ps postgres`)
- Check: Migrations are up to date (`docker-compose exec web alembic current`)
- Check: Connection string in environment variables

**Issue: High memory usage**
- Reduce: `MODEL_POOL_SIZE` and `MODEL_POOL_MAX_SIZE`
- Reduce: `CELERY_CONCURRENCY`
- Use: Smaller model size
- Check: Memory leaks in `model_pool.py`

### Useful Log Patterns

```bash
# Find model pool statistics
docker-compose logs worker | grep "Model acquired in"

# Find failed jobs
docker-compose logs worker | grep "ERROR"

# Find retry attempts
docker-compose logs worker | grep "retry:"

# Find OOM fallbacks
docker-compose logs worker | grep "OOM loading"
```

---

## Code Style & Conventions

### Naming Conventions

- **Files**: snake_case (e.g., `model_pool.py`)
- **Classes**: PascalCase (e.g., `ModelPool`, `TranscriptionJob`)
- **Functions**: snake_case (e.g., `acquire_model`, `get_db_session`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `MAX_RETRIES`)
- **Private methods**: Leading underscore (e.g., `_load_model`, `_evict_lru`)

### Logging

All modules use Python's standard logging:
```python
import logging
logger = logging.getLogger(__name__)

logger.info("Job started: {job_id}")     # General info
logger.warning("Pool full, evicting...")  # Warnings
logger.error("Failed: {error}", exc_info=True)  # Errors with stack trace
logger.debug("Detailed state: {state}")   # Debug (disabled in production)
```

### Error Handling

```python
# Specific exceptions first
try:
    result = operation()
except SpecificError as e:
    handle_specific(e)
except Exception as e:
    logger.error(f"Unexpected: {e}", exc_info=True)
    raise
finally:
    cleanup()
```

### Database Operations

Always use context managers or explicit session management:
```python
# FastAPI endpoints - dependency injection
def endpoint(db: Session = Depends(get_db)):
    job = db.query(TranscriptionJob).filter_by(id=job_id).first()

# Celery tasks - context manager
with get_db_session() as db:
    job = db.query(TranscriptionJob).filter_by(id=job_id).first()
    # Auto-commit on success, rollback on exception
```

---

## Additional Resources

- **Swagger UI**: http://localhost:8000/docs
- **Flower (task monitoring)**: http://localhost:5555
- **[README.md](README.md)** - User guide, API reference, configuration
- **[SETUP.md](SETUP.md)** - Deployment and setup instructions
- **[SECURITY.md](SECURITY.md)** - Security architecture and roadmap

---

## Future Architecture Considerations

When implementing future features, consider:

1. **Speaker Diarization**: May require separate model pool (diarization models)
2. **Streaming**: Requires WebSocket support in FastAPI, streaming Whisper API
3. **Horizontal Scaling**: Add load balancer, shared Redis/PostgreSQL
4. **Metrics**: Add Prometheus exporters to worker and API
5. **Testing**: Add pytest suite with fixtures for database, Celery, model pool
6. **Authentication**: Add JWT or API key authentication to endpoints
7. **Rate Limiting**: Add Redis-based rate limiting to prevent abuse
