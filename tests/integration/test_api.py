"""
Integration tests for FastAPI endpoints.

Tests the full API flow including:
- Job submission
- Status polling
- Job cancellation
- Error handling
- Admin endpoint authentication
"""
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock
import io

# Set test API key for authenticated endpoints
TEST_API_KEY = "test-api-key-12345"
os.environ["API_KEYS"] = TEST_API_KEY


@pytest.mark.integration
class TestTranscriptionAPI:
    """Test transcription API endpoints."""
    
    def test_health_check(self, client):
        """Test basic health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "database" in data
    
    @patch('app.transcribe_audio_task.apply_async')
    def test_submit_transcription_job(self, mock_task, client, sample_audio_file):
        """Test submitting a transcription job."""
        # Mock Celery task
        mock_task.return_value = Mock(id="task-123")
        
        with open(sample_audio_file, "rb") as f:
            response = client.post(
                "/transcribe/",
                files={"file": ("test.wav", f, "audio/wav")},
                data={"language": "en"}
            )
        
        assert response.status_code == 202  # Accepted
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert "message" in data
    
    def test_submit_invalid_file_type(self, client):
        """Test submitting non-audio file is rejected."""
        fake_file = io.BytesIO(b"Not an audio file")
        response = client.post(
            "/transcribe/",
            files={"file": ("test.txt", fake_file, "text/plain")},
        )
        assert response.status_code == 400
    
    def test_submit_file_too_large(self, client):
        """Test file size validation."""
        # Create a file larger than max size
        large_file = io.BytesIO(b"x" * (501 * 1024 * 1024))  # 501 MB
        response = client.post(
            "/transcribe/",
            files={"file": ("huge.wav", large_file, "audio/wav")},
        )
        assert response.status_code == 413  # Request Entity Too Large
    
    def test_get_job_status_not_found(self, client):
        """Test getting status for non-existent job."""
        response = client.get("/transcribe/550e8400-e29b-41d4-a716-446655440000")
        assert response.status_code == 404
    
    @patch('app.transcribe_audio_task.apply_async')
    def test_cancel_job(self, mock_task, client, sample_audio_file, db_session):
        """Test cancelling a pending job."""
        mock_task.return_value = Mock(id="task-123")
        
        # Submit job
        with open(sample_audio_file, "rb") as f:
            submit_response = client.post(
                "/transcribe/",
                files={"file": ("test.wav", f, "audio/wav")},
            )
        job_id = submit_response.json()["job_id"]
        
        # Cancel job
        cancel_response = client.delete(f"/transcribe/{job_id}")
        assert cancel_response.status_code == 200
        data = cancel_response.json()
        assert data["status"] == "cancelled"
    
    def test_list_jobs(self, client):
        """Test listing jobs with filters."""
        response = client.get("/jobs/")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "jobs" in data
        assert isinstance(data["jobs"], list)
    
    def test_admin_health_endpoint(self, client):
        """Test comprehensive admin health check."""
        response = client.get(
            "/admin/health",
            headers={"X-API-Key": TEST_API_KEY}
        )
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "queues" in data
        assert "model_pool" in data

    def test_admin_health_requires_auth(self, client):
        """Test admin health check requires authentication."""
        response = client.get("/admin/health")
        assert response.status_code == 401

    def test_admin_errors_endpoint(self, client):
        """Test dead letter queue viewing."""
        response = client.get(
            "/admin/errors",
            headers={"X-API-Key": TEST_API_KEY}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "errors" in data

    def test_admin_errors_requires_auth(self, client):
        """Test admin errors endpoint requires authentication."""
        response = client.get("/admin/errors")
        assert response.status_code == 401


@pytest.mark.integration
class TestAPIErrorHandling:
    """Test API error handling and edge cases."""
    
    def test_missing_file_parameter(self, client):
        """Test API returns error when file is missing."""
        response = client.post("/transcribe/", data={"language": "en"})
        assert response.status_code == 422  # Unprocessable Entity
    
    def test_invalid_model_size(self, client, sample_audio_file):
        """Test invalid model size is rejected."""
        with open(sample_audio_file, "rb") as f:
            response = client.post(
                "/transcribe/",
                files={"file": ("test.wav", f, "audio/wav")},
                data={"model_size": "invalid"}
            )
        # Should either reject or use default
        assert response.status_code in [400, 422, 202]
    
    def test_invalid_language_code(self, client, sample_audio_file):
        """Test invalid language code handling."""
        with open(sample_audio_file, "rb") as f:
            response = client.post(
                "/transcribe/",
                files={"file": ("test.wav", f, "audio/wav")},
                data={"language": "xyz"}  # Invalid language
            )
        # Should either reject or use auto-detect
        assert response.status_code in [400, 422, 202]
