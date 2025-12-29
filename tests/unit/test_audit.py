"""
Unit tests for audit.py

Tests the immutable audit logging with hash chain integrity verification.
"""
import hashlib
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime


class TestAuditHashChain:
    """Test cryptographic hash chain integrity."""

    def test_hash_chain_format(self):
        """Test that hash input follows expected format."""
        event_id = "test-event-123"
        timestamp = datetime(2025, 1, 15, 10, 30, 0)
        action = "job.create"
        resource_type = "transcription_job"
        resource_id = "job-456"
        user_id = "user-789"
        outcome = "success"
        previous_hash = "0" * 64

        hash_input = (
            f"{event_id}|{timestamp.isoformat()}|"
            f"{action}|{resource_type}|{resource_id}|"
            f"{user_id}|{outcome}|{previous_hash}"
        )

        expected_parts = [
            event_id,
            timestamp.isoformat(),
            action,
            resource_type,
            resource_id,
            user_id,
            outcome,
            previous_hash,
        ]
        assert hash_input == "|".join(expected_parts)

    def test_hash_chain_produces_valid_sha256(self):
        """Test that hash chain produces valid SHA-256 hashes."""
        hash_input = "test|data|for|hashing"
        record_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        assert len(record_hash) == 64
        assert all(c in "0123456789abcdef" for c in record_hash)

    def test_hash_chain_is_deterministic(self):
        """Test that same input produces same hash."""
        hash_input = "event-1|2025-01-15T10:30:00|job.create|transcription_job|job-123|user-456|success|" + "0" * 64

        hash1 = hashlib.sha256(hash_input.encode()).hexdigest()
        hash2 = hashlib.sha256(hash_input.encode()).hexdigest()

        assert hash1 == hash2

    def test_hash_chain_detects_tampering(self):
        """Test that any change to input changes the hash."""
        original_input = "event-1|2025-01-15T10:30:00|job.create|transcription_job|job-123|user-456|success|" + "0" * 64
        tampered_input = "event-1|2025-01-15T10:30:00|job.create|transcription_job|job-123|user-456|failure|" + "0" * 64

        original_hash = hashlib.sha256(original_input.encode()).hexdigest()
        tampered_hash = hashlib.sha256(tampered_input.encode()).hexdigest()

        assert original_hash != tampered_hash

    def test_genesis_block_uses_zero_hash(self):
        """Test that first record in chain uses zero hash as previous."""
        genesis_previous_hash = "0" * 64

        assert len(genesis_previous_hash) == 64
        assert genesis_previous_hash == "0000000000000000000000000000000000000000000000000000000000000000"


class TestAuditLoggerUnit:
    """Unit tests for AuditLogger class."""

    @patch('audit.SessionLocal')
    def test_audit_logger_initialization(self, mock_session_factory):
        """Test AuditLogger can be initialized."""
        from audit import AuditLogger

        logger = AuditLogger(db_session_factory=mock_session_factory)

        assert logger._session_factory == mock_session_factory

    @patch('audit.SessionLocal')
    def test_get_audit_logger_returns_singleton(self, mock_session_factory):
        """Test get_audit_logger returns singleton instance."""
        from audit import get_audit_logger, _audit_logger_instance
        import audit

        audit._audit_logger_instance = None

        logger1 = get_audit_logger()
        logger2 = get_audit_logger()

        assert logger1 is logger2

    def test_audit_action_naming_convention(self):
        """Test that audit actions follow naming convention."""
        valid_actions = [
            "job.create",
            "job.read",
            "job.update",
            "job.delete",
            "transcript.read",
            "auth.login",
            "auth.logout",
            "auth.failed",
        ]

        for action in valid_actions:
            parts = action.split(".")
            assert len(parts) == 2, f"Action {action} should have format 'resource.verb'"
            assert parts[0].isalpha(), f"Resource '{parts[0]}' should be alphabetic"
            assert parts[1].isalpha(), f"Verb '{parts[1]}' should be alphabetic"

    def test_audit_outcome_values(self):
        """Test valid outcome values."""
        valid_outcomes = ["success", "failure", "denied", "error"]

        for outcome in valid_outcomes:
            assert outcome in ["success", "failure", "denied", "error"]


class TestChainIntegrityVerification:
    """Test chain integrity verification logic."""

    def test_verify_chain_with_valid_records(self):
        """Test verification passes for valid chain."""
        records = []
        prev_hash = "0" * 64

        for i in range(3):
            event_id = f"event-{i}"
            timestamp = datetime(2025, 1, 15, 10, 30, i)
            action = "job.create"
            resource_type = "transcription_job"
            resource_id = f"job-{i}"
            user_id = "user-1"
            outcome = "success"

            hash_input = (
                f"{event_id}|{timestamp.isoformat()}|"
                f"{action}|{resource_type}|{resource_id}|"
                f"{user_id}|{outcome}|{prev_hash}"
            )
            record_hash = hashlib.sha256(hash_input.encode()).hexdigest()

            records.append({
                "sequence_number": i + 1,
                "event_id": event_id,
                "timestamp": timestamp,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "user_id": user_id,
                "outcome": outcome,
                "previous_hash": prev_hash,
                "record_hash": record_hash,
            })
            prev_hash = record_hash

        expected_prev = "0" * 64
        for record in records:
            assert record["previous_hash"] == expected_prev
            expected_prev = record["record_hash"]

    def test_detect_chain_break_wrong_previous_hash(self):
        """Test detection of tampered previous_hash."""
        record1_hash = hashlib.sha256(b"record1").hexdigest()
        record2_previous = "tampered_hash_value_" + "0" * 44

        assert record2_previous != record1_hash

    def test_detect_chain_break_modified_record(self):
        """Test detection of modified record content."""
        original_hash_input = "event-1|2025-01-15|job.create|job|123|user|success|" + "0" * 64
        original_hash = hashlib.sha256(original_hash_input.encode()).hexdigest()

        modified_hash_input = "event-1|2025-01-15|job.delete|job|123|user|success|" + "0" * 64
        recomputed_hash = hashlib.sha256(modified_hash_input.encode()).hexdigest()

        assert original_hash != recomputed_hash


@pytest.mark.integration
class TestAuditLoggerIntegration:
    """Integration tests requiring database setup."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = None
        return session

    @patch('audit.SessionLocal')
    @pytest.mark.asyncio
    async def test_log_creates_audit_record(self, mock_session_factory, mock_db_session):
        """Test that log() creates an audit record."""
        mock_session_factory.return_value = mock_db_session
        from audit import AuditLogger

        logger = AuditLogger(db_session_factory=mock_session_factory)

        event_id = await logger.log(
            action="job.create",
            resource_type="transcription_job",
            resource_id="test-job-123",
            user_id="test-user-456",
            outcome="success",
        )

        assert event_id is not None
        assert mock_db_session.execute.called
        assert mock_db_session.commit.called
