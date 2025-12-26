"""
Pytest configuration and shared fixtures.
"""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app import app
from database import Base
from models import TranscriptionJob, TranscriptionResult, ErrorLog


@pytest.fixture(scope="session")
def test_db_engine():
    """Create a test database engine."""
    # Use in-memory SQLite for fast tests
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(test_db_engine):
    """Create a new database session for each test."""
    SessionLocal = sessionmaker(bind=test_db_engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="module")
def client():
    """FastAPI test client."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sample_audio_file(tmp_path):
    """Create a sample audio file for testing."""
    audio_file = tmp_path / "test_audio.wav"
    # Create a minimal valid WAV file (44 bytes header + silence)
    with open(audio_file, "wb") as f:
        # WAV header (44 bytes)
        f.write(b'RIFF')
        f.write((36).to_bytes(4, 'little'))  # File size - 8
        f.write(b'WAVE')
        f.write(b'fmt ')
        f.write((16).to_bytes(4, 'little'))  # Subchunk1Size
        f.write((1).to_bytes(2, 'little'))   # AudioFormat (PCM)
        f.write((1).to_bytes(2, 'little'))   # NumChannels
        f.write((16000).to_bytes(4, 'little'))  # SampleRate
        f.write((32000).to_bytes(4, 'little'))  # ByteRate
        f.write((2).to_bytes(2, 'little'))   # BlockAlign
        f.write((16).to_bytes(2, 'little'))  # BitsPerSample
        f.write(b'data')
        f.write((0).to_bytes(4, 'little'))   # Subchunk2Size
    return audio_file


@pytest.fixture
def mock_whisper_model(mocker):
    """Mock Whisper model for testing without loading actual models."""
    mock_model = mocker.MagicMock()
    mock_model.transcribe.return_value = {
        "text": "This is a test transcription.",
        "language": "en",
        "duration": 10.5
    }
    return mock_model
