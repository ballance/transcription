"""
PII-safe structured logging configuration.

All logs are sanitized to prevent leaking sensitive information
from filenames, audio content, or transcripts.

Usage:
    from logging_config import setup_logging, get_logger

    # Initialize once at application startup
    setup_logging()

    # Get logger for your module
    logger = get_logger(__name__)
    logger.info("Processing job", extra={"job_id": job_id})
"""

import logging
import os
import re
import json
from typing import Any, Optional
from datetime import datetime


class PIISafeFilter(logging.Filter):
    """
    Remove PII from log records before emission.

    This filter catches common PII patterns and replaces them with
    safe placeholders. It's not 100% comprehensive but catches the
    most common cases that could leak in logs.
    """

    PII_PATTERNS = [
        # Social Security Numbers
        (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN-REDACTED]"),
        (r"\b\d{9}\b(?!\d)", "[SSN-REDACTED]"),

        # Credit Card Numbers (various formats)
        (r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b", "[CARD-REDACTED]"),
        (r"\b\d{16}\b", "[CARD-REDACTED]"),

        # Email Addresses
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL-REDACTED]"),

        # Phone Numbers (US formats)
        (r"\b\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b", "[PHONE-REDACTED]"),
        (r"\b1-[0-9]{3}-[0-9]{3}-[0-9]{4}\b", "[PHONE-REDACTED]"),

        # Driver's License (common state patterns)
        (r"\b[A-Z]\d{7}\b", "[DL-REDACTED]"),
        (r"\b[A-Z]{2}\d{6}\b", "[DL-REDACTED]"),

        # License Plates (generic US pattern - may have false positives)
        # Only match if preceded/followed by common keywords
        (r"(?i)(?:plate|license|tag)[:\s]+([A-Z0-9]{2,8})", r"plate:[PLATE-REDACTED]"),

        # IP Addresses (optional - uncomment if needed)
        # (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[IP-REDACTED]"),
    ]

    REDACT_FIELDS = frozenset({
        "password",
        "api_key",
        "apikey",
        "token",
        "secret",
        "authorization",
        "auth",
        "credential",
        "transcription",
        "transcript",
        "transcript_text",
        "transcription_text",
        "audio_content",
        "file_content",
        "ssn",
        "social_security",
        "credit_card",
        "card_number",
        "cvv",
        "pin",
    })

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize log message and extra fields."""
        if hasattr(record, "msg") and record.msg:
            record.msg = self._sanitize_string(str(record.msg))

        if record.args:
            sanitized_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    sanitized_args.append(self._sanitize_string(arg))
                elif isinstance(arg, dict):
                    sanitized_args.append(self._sanitize_dict(arg))
                else:
                    sanitized_args.append(arg)
            record.args = tuple(sanitized_args)

        for key in list(vars(record).keys()):
            if key.lower() in self.REDACT_FIELDS:
                setattr(record, key, "[REDACTED]")
            elif isinstance(getattr(record, key, None), str):
                value = getattr(record, key)
                setattr(record, key, self._sanitize_string(value))

        return True

    def _sanitize_string(self, text: str) -> str:
        """Apply PII patterns to sanitize a string."""
        if not text:
            return text

        for pattern, replacement in self.PII_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        return text

    def _sanitize_dict(self, data: dict) -> dict:
        """Recursively sanitize a dictionary."""
        sanitized = {}
        for key, value in data.items():
            if key.lower() in self.REDACT_FIELDS:
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, str):
                sanitized[key] = self._sanitize_string(value)
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_dict(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_string(v) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                sanitized[key] = value
        return sanitized


class StructuredFormatter(logging.Formatter):
    """
    JSON structured logging formatter for production.

    Outputs logs in JSON format suitable for log aggregation
    services like ELK, Datadog, or CloudWatch.
    """

    INTERNAL_FIELDS = frozenset({
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "exc_info",
        "exc_text",
        "thread",
        "threadName",
        "message",
        "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        for key, value in record.__dict__.items():
            if key not in self.INTERNAL_FIELDS:
                if isinstance(value, (str, int, float, bool, type(None))):
                    log_data[key] = value
                elif isinstance(value, (list, dict)):
                    try:
                        json.dumps(value)
                        log_data[key] = value
                    except (TypeError, ValueError):
                        log_data[key] = str(value)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


class HumanReadableFormatter(logging.Formatter):
    """Human-readable formatter for development environments."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        reset = self.RESET if color else ""

        timestamp = datetime.utcfromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        message = record.getMessage()

        extra_fields = []
        for key, value in record.__dict__.items():
            if key not in StructuredFormatter.INTERNAL_FIELDS:
                if isinstance(value, (str, int, float, bool)):
                    extra_fields.append(f"{key}={value}")

        extras = " | " + " ".join(extra_fields) if extra_fields else ""

        return f"{timestamp} {color}{record.levelname:8}{reset} [{record.name}] {message}{extras}"


def setup_logging(
    log_level: Optional[str] = None,
    json_format: Optional[bool] = None,
    logger_name: Optional[str] = None,
) -> None:
    """
    Configure PII-safe logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                   Defaults to LOG_LEVEL env var or INFO.
        json_format: Use JSON structured logging. Defaults to LOG_FORMAT env var
                     or True in production (when DEBUG=false).
        logger_name: Specific logger to configure. None configures root logger.
    """
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    if json_format is None:
        log_format_env = os.getenv("LOG_FORMAT", "").lower()
        if log_format_env == "json":
            json_format = True
        elif log_format_env == "human":
            json_format = False
        else:
            debug_mode = os.getenv("DEBUG", "false").lower() == "true"
            json_format = not debug_mode

    handler = logging.StreamHandler()
    handler.addFilter(PIISafeFilter())

    if json_format:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(HumanReadableFormatter())

    target_logger = logging.getLogger(logger_name)
    target_logger.handlers = [handler]
    target_logger.setLevel(getattr(logging, log_level))

    if logger_name is None:
        for lib_logger in ["uvicorn", "uvicorn.access", "celery", "sqlalchemy.engine"]:
            lib = logging.getLogger(lib_logger)
            lib.handlers = [handler]
            lib.addFilter(PIISafeFilter())
            lib.propagate = False


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with PII-safe filtering.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(PIISafeFilter())

        log_format = os.getenv("LOG_FORMAT", "").lower()
        debug_mode = os.getenv("DEBUG", "false").lower() == "true"

        if log_format == "json" or (log_format != "human" and not debug_mode):
            handler.setFormatter(StructuredFormatter())
        else:
            handler.setFormatter(HumanReadableFormatter())

        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger


def log_job_event(
    logger: logging.Logger,
    event: str,
    job_id: str,
    level: int = logging.INFO,
    **kwargs: Any
) -> None:
    """
    Log a job-related event with structured fields.

    This helper ensures consistent logging format for job events
    without accidentally including sensitive job content.

    Args:
        logger: Logger instance
        event: Event name (e.g., "job.created", "job.completed")
        job_id: Job UUID (safe to log)
        level: Logging level
        **kwargs: Additional safe fields to include
    """
    safe_fields = {
        "job_id",
        "status",
        "progress",
        "model_size",
        "language",
        "duration_seconds",
        "file_size_bytes",
        "error_type",
        "worker_id",
        "retry_count",
        "agency_id",
        "user_role",
    }

    extra = {"event": event, "job_id": job_id}
    for key, value in kwargs.items():
        if key in safe_fields:
            extra[key] = value
        else:
            extra[key] = "[REDACTED]"

    logger.log(level, f"Job event: {event}", extra=extra)
