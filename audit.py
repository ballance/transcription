"""
Audit logging for compliance.

Provides immutable audit trail with cryptographic hash chain for
tamper detection. Supports CJIS, SOC 2, and other compliance frameworks.

Usage:
    from audit import AuditLogger, get_audit_logger

    # Get singleton instance
    audit = get_audit_logger()

    # Log an event
    await audit.log(
        action="job.create",
        resource_type="transcription_job",
        resource_id=str(job.id),
        user_id=str(user.id),
        outcome="success"
    )

    # Verify chain integrity
    is_valid, first_invalid = await audit.verify_chain_integrity()
"""

import hashlib
import json
import threading
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from database import SessionLocal
from logging_config import get_logger

logger = get_logger(__name__)

_audit_logger_instance: Optional["AuditLogger"] = None
_audit_lock = threading.Lock()


class AuditLogger:
    """
    Immutable audit logging with hash chain for tamper detection.

    The hash chain ensures any tampering can be detected by verifying
    the chain integrity. Each record includes a SHA-256 hash of key fields
    combined with the previous record's hash.
    """

    def __init__(self, db_session_factory=None):
        self._session_factory = db_session_factory or SessionLocal
        self._sequence_lock = threading.Lock()

    def _get_session(self) -> Session:
        return self._session_factory()

    async def log(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        user_role: Optional[str] = None,
        agency_id: Optional[str] = None,
        api_key_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        outcome: str = "success",
        outcome_reason: Optional[str] = None,
        previous_state: Optional[dict] = None,
        new_state: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Log an audit event with cryptographic hash chain.

        Args:
            action: The action performed (e.g., "job.create", "transcript.read")
            resource_type: Type of resource accessed (e.g., "transcription_job")
            resource_id: UUID of the resource (optional)
            user_id: UUID of the user performing the action
            user_email: Email of the user (for display)
            user_role: Role of the user at time of action
            agency_id: UUID of the user's agency
            api_key_id: First 8 chars of hashed API key (if API auth)
            ip_address: Client IP address
            user_agent: Client user agent string
            request_id: UUID for request correlation
            session_id: UUID for session correlation
            outcome: Result of action ("success", "failure", "denied", "error")
            outcome_reason: Explanation if not success
            previous_state: State before modification (for updates/deletes)
            new_state: State after modification (for creates/updates)
            metadata: Additional context (sanitized)

        Returns:
            The event_id of the created audit record
        """
        db = self._get_session()

        try:
            with self._sequence_lock:
                prev = db.execute(
                    text(
                        "SELECT sequence_number, record_hash FROM audit_log "
                        "ORDER BY sequence_number DESC LIMIT 1"
                    )
                ).fetchone()

                if prev:
                    sequence_number = prev.sequence_number + 1
                    previous_hash = prev.record_hash
                else:
                    sequence_number = 1
                    previous_hash = "0" * 64

                event_timestamp = datetime.utcnow()
                event_id = str(uuid.uuid4())

                hash_input = (
                    f"{event_id}|{event_timestamp.isoformat()}|"
                    f"{action}|{resource_type}|{resource_id}|"
                    f"{user_id}|{outcome}|{previous_hash}"
                )
                record_hash = hashlib.sha256(hash_input.encode()).hexdigest()

                db.execute(
                    text("""
                        INSERT INTO audit_log (
                            event_id, event_timestamp, user_id, user_email,
                            user_role, agency_id, api_key_id, action,
                            resource_type, resource_id, ip_address, user_agent,
                            request_id, session_id, outcome, outcome_reason,
                            previous_state, new_state, sequence_number,
                            previous_hash, record_hash, metadata
                        ) VALUES (
                            :event_id, :event_timestamp, :user_id, :user_email,
                            :user_role, :agency_id, :api_key_id, :action,
                            :resource_type, :resource_id, :ip_address::inet, :user_agent,
                            :request_id, :session_id, :outcome, :outcome_reason,
                            :previous_state, :new_state, :sequence_number,
                            :previous_hash, :record_hash, :metadata
                        )
                    """),
                    {
                        "event_id": event_id,
                        "event_timestamp": event_timestamp,
                        "user_id": user_id,
                        "user_email": user_email,
                        "user_role": user_role,
                        "agency_id": agency_id,
                        "api_key_id": api_key_id,
                        "action": action,
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "ip_address": ip_address,
                        "user_agent": user_agent[:500] if user_agent else None,
                        "request_id": request_id,
                        "session_id": session_id,
                        "outcome": outcome,
                        "outcome_reason": outcome_reason,
                        "previous_state": json.dumps(previous_state) if previous_state else None,
                        "new_state": json.dumps(new_state) if new_state else None,
                        "sequence_number": sequence_number,
                        "previous_hash": previous_hash,
                        "record_hash": record_hash,
                        "metadata": json.dumps(metadata) if metadata else None,
                    },
                )
                db.commit()

                logger.debug(
                    "Audit event logged",
                    extra={
                        "event_id": event_id,
                        "action": action,
                        "resource_type": resource_type,
                        "sequence_number": sequence_number,
                    },
                )

                return event_id

        except Exception as e:
            db.rollback()
            logger.error(
                "Failed to log audit event",
                extra={"action": action, "error": str(e)},
            )
            raise
        finally:
            db.close()

    async def verify_chain_integrity(
        self, start_seq: int = 1, batch_size: int = 1000
    ) -> tuple[bool, Optional[int]]:
        """
        Verify the hash chain has not been tampered with.

        This verifies:
        1. Each record's previous_hash matches the prior record's record_hash
        2. Each record's record_hash is correctly computed from its fields

        Args:
            start_seq: Starting sequence number for verification
            batch_size: Number of records to verify per batch

        Returns:
            (is_valid, first_invalid_sequence_number)
            If valid, returns (True, None)
            If invalid, returns (False, sequence_number_of_first_invalid)
        """
        db = self._get_session()

        try:
            expected_prev_hash = None
            if start_seq > 1:
                prev = db.execute(
                    text(
                        "SELECT record_hash FROM audit_log "
                        "WHERE sequence_number = :seq"
                    ),
                    {"seq": start_seq - 1},
                ).fetchone()
                if prev:
                    expected_prev_hash = prev.record_hash
            else:
                expected_prev_hash = "0" * 64

            current_seq = start_seq
            while True:
                records = db.execute(
                    text("""
                        SELECT sequence_number, event_id, event_timestamp,
                               action, resource_type, resource_id, user_id,
                               outcome, previous_hash, record_hash
                        FROM audit_log
                        WHERE sequence_number >= :start_seq
                          AND sequence_number < :end_seq
                        ORDER BY sequence_number ASC
                    """),
                    {"start_seq": current_seq, "end_seq": current_seq + batch_size},
                ).fetchall()

                if not records:
                    break

                for record in records:
                    if expected_prev_hash and record.previous_hash != expected_prev_hash:
                        logger.warning(
                            "Audit chain break detected: previous_hash mismatch",
                            extra={
                                "sequence_number": record.sequence_number,
                                "expected": expected_prev_hash,
                                "actual": record.previous_hash,
                            },
                        )
                        return False, record.sequence_number

                    hash_input = (
                        f"{record.event_id}|{record.event_timestamp.isoformat()}|"
                        f"{record.action}|{record.resource_type}|{record.resource_id}|"
                        f"{record.user_id}|{record.outcome}|{record.previous_hash}"
                    )
                    expected_hash = hashlib.sha256(hash_input.encode()).hexdigest()

                    if record.record_hash != expected_hash:
                        logger.warning(
                            "Audit chain break detected: record_hash mismatch",
                            extra={
                                "sequence_number": record.sequence_number,
                                "expected": expected_hash,
                                "actual": record.record_hash,
                            },
                        )
                        return False, record.sequence_number

                    expected_prev_hash = record.record_hash

                current_seq += batch_size

            return True, None

        finally:
            db.close()

    async def get_chain_of_custody(
        self, resource_type: str, resource_id: str
    ) -> list[dict]:
        """
        Get complete access history for a resource (chain of custody).

        Args:
            resource_type: Type of resource (e.g., "transcription_job")
            resource_id: UUID of the resource

        Returns:
            List of audit records in chronological order
        """
        db = self._get_session()

        try:
            records = db.execute(
                text("""
                    SELECT
                        event_id, event_timestamp, user_email, user_role,
                        action, outcome, outcome_reason, ip_address,
                        metadata
                    FROM audit_log
                    WHERE resource_type = :resource_type
                      AND resource_id = :resource_id
                    ORDER BY event_timestamp ASC
                """),
                {"resource_type": resource_type, "resource_id": resource_id},
            ).fetchall()

            return [
                {
                    "event_id": str(r.event_id),
                    "timestamp": r.event_timestamp.isoformat(),
                    "user": r.user_email,
                    "role": r.user_role,
                    "action": r.action,
                    "outcome": r.outcome,
                    "reason": r.outcome_reason,
                    "ip_address": str(r.ip_address) if r.ip_address else None,
                    "metadata": r.metadata,
                }
                for r in records
            ]

        finally:
            db.close()

    async def get_failed_auth_attempts(
        self, hours: int = 24, limit: int = 100
    ) -> list[dict]:
        """
        Get recent failed authentication attempts.

        Args:
            hours: Look back period in hours
            limit: Maximum records to return

        Returns:
            List of failed auth attempts
        """
        db = self._get_session()

        try:
            records = db.execute(
                text("""
                    SELECT
                        event_timestamp, ip_address, user_email,
                        outcome_reason, metadata
                    FROM audit_log
                    WHERE action LIKE 'auth.%%'
                      AND outcome = 'failure'
                      AND event_timestamp > NOW() - make_interval(hours => :hours)
                    ORDER BY event_timestamp DESC
                    LIMIT :limit
                """),
                {"hours": hours, "limit": limit},
            ).fetchall()

            return [
                {
                    "timestamp": r.event_timestamp.isoformat(),
                    "ip_address": str(r.ip_address) if r.ip_address else None,
                    "email": r.user_email,
                    "reason": r.outcome_reason,
                    "metadata": r.metadata,
                }
                for r in records
            ]

        finally:
            db.close()


def get_audit_logger() -> AuditLogger:
    """Get or create singleton AuditLogger instance."""
    global _audit_logger_instance

    if _audit_logger_instance is None:
        with _audit_lock:
            if _audit_logger_instance is None:
                _audit_logger_instance = AuditLogger()

    return _audit_logger_instance


async def log_audit_event(
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    outcome: str = "success",
    **kwargs: Any,
) -> str:
    """
    Convenience function for logging audit events.

    This is the primary interface for audit logging throughout the application.
    """
    audit = get_audit_logger()
    return await audit.log(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        outcome=outcome,
        **kwargs,
    )
