# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive test suite with pytest
- CI/CD pipeline with GitHub Actions
- API key authentication and rate limiting
- Security policy and contributing guidelines
- Pre-commit hooks for code quality
- Development requirements file
- Docker image optimization with .dockerignore

### Changed
- Improved .gitignore to exclude test files and coverage reports

### Security
- Added authentication middleware (auth.py)
- Added rate limiting (100 req/min per API key)
- Added security scanning in CI pipeline

## [2.0.0] - 2025-12-26

### Added
- Production-ready async transcription API
- Celery + Redis job queue for non-blocking processing
- Thread-safe model pool with LRU eviction
- PostgreSQL database for job tracking
- Auto-retry with exponential backoff
- OOM fallback to smaller models
- Dead Letter Queue for error tracking
- Docker Compose deployment
- Admin health endpoints
- Comprehensive documentation (README, SETUP, agents.md)
- Database migrations with Alembic

### Changed
- Transformed synchronous API to async architecture
- API now returns 202 Accepted with job_id instead of blocking
- Model loading moved to worker pool (eliminates reload overhead)

### Performance
- API response: 5-30min → <500ms
- Concurrent processing: 1 → 2-4 simultaneous jobs
- Model reload: 15-30s → 0s (pool reuse)
- Throughput: 2-3 files/hour → 10-20 files/hour (4-8x improvement)

## [1.0.0] - 2025-08-11

### Added
- Single file transcription CLI (transcribe.py)
- Batch folder monitoring (transcribe_all.py)
- Basic FastAPI web server
- Configurable Whisper model sizes
- Video to audio conversion support
- Environment variable configuration
- Basic documentation

### Features
- Support for multiple audio formats (wav, mp3, m4a, flac, ogg, aac)
- Support for video formats (mp4, mkv, m4v) via FFmpeg
- Metadata in transcription outputs
- Error handling and logging
- Virtual environment setup automation

[Unreleased]: https://github.com/ballance/transcription/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/ballance/transcription/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/ballance/transcription/releases/tag/v1.0.0
