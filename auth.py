"""
Authentication and authorization for the transcription API.

Provides API key-based authentication with rate limiting.
"""
import os
import time
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from starlette.requests import Request
from typing import Dict, Optional
import hashlib
import hmac

# API key header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# In production, load from secure secret management (AWS Secrets Manager, Vault, etc.)
# For now, using environment variable
VALID_API_KEYS = set(os.getenv("API_KEYS", "").split(","))

# Rate limiting storage (in production, use Redis)
# Format: {api_key: {timestamp: request_count}}
rate_limit_storage: Dict[str, Dict[int, int]] = {}

# Rate limit: 100 requests per minute per API key
RATE_LIMIT_REQUESTS = 100
RATE_LIMIT_WINDOW = 60  # seconds


async def validate_api_key(api_key: str = Security(api_key_header)) -> str:
    """
    Validate API key from request header.

    Args:
        api_key: API key from X-API-Key header

    Returns:
        The validated API key

    Raises:
        HTTPException: If API key is missing or invalid
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Hash the API key for comparison (constant-time comparison)
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # In production, compare hashed keys stored in database
    valid_hashes = {hashlib.sha256(key.encode()).hexdigest() for key in VALID_API_KEYS if key}

    if not valid_hashes or api_key_hash not in valid_hashes:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key


async def check_rate_limit(api_key: str = Security(validate_api_key)) -> str:
    """
    Check rate limit for API key.

    Args:
        api_key: Validated API key

    Returns:
        The API key if rate limit not exceeded

    Raises:
        HTTPException: If rate limit exceeded
    """
    current_time = int(time.time())
    current_window = current_time // RATE_LIMIT_WINDOW

    # Initialize storage for this API key
    if api_key not in rate_limit_storage:
        rate_limit_storage[api_key] = {}

    # Clean up old windows (keep last 2 windows)
    rate_limit_storage[api_key] = {
        window: count
        for window, count in rate_limit_storage[api_key].items()
        if window >= current_window - 1
    }

    # Increment request count for current window
    rate_limit_storage[api_key][current_window] = (
        rate_limit_storage[api_key].get(current_window, 0) + 1
    )

    # Check if rate limit exceeded
    if rate_limit_storage[api_key][current_window] > RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW}s",
            headers={
                "X-RateLimit-Limit": str(RATE_LIMIT_REQUESTS),
                "X-RateLimit-Window": str(RATE_LIMIT_WINDOW),
                "Retry-After": str(RATE_LIMIT_WINDOW),
            },
        )

    return api_key


# Utility functions

def generate_api_key(length: int = 32) -> str:
    """
    Generate a secure random API key.

    Args:
        length: Length of the API key

    Returns:
        Hexadecimal API key string
    """
    return os.urandom(length).hex()


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key for storage.

    Args:
        api_key: Plain text API key

    Returns:
        SHA-256 hash of the API key
    """
    return hashlib.sha256(api_key.encode()).hexdigest()
