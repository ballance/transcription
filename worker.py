#!/usr/bin/env python
"""
Celery worker entry point for transcription tasks.

Starts a Celery worker that processes transcription jobs from the queue.

Usage:
    python worker.py

    Or with custom options:
    celery -A celery_app worker --loglevel=info --concurrency=4

Environment variables:
    CELERY_CONCURRENCY: Number of concurrent worker processes (default: 4)
    CELERY_LOG_LEVEL: Logging level (default: info)
    CELERY_QUEUES: Comma-separated list of queues to consume from
"""

import logging
import sys

from celery_app import celery_app
from config import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('worker.log')
    ]
)

logger = logging.getLogger(__name__)


def main():
    """
    Start the Celery worker.

    Configures and starts a Celery worker with settings from config.
    """
    logger.info("Starting Celery worker for transcription service")
    logger.info(f"Concurrency: {config.celery_worker_concurrency}")
    logger.info(f"Broker: {config.celery_broker_url}")
    logger.info(f"Database: {config.database_url}")

    # Worker arguments
    argv = [
        'worker',
        '--loglevel=info',
        f'--concurrency={config.celery_worker_concurrency}',
        '--pool=prefork',  # Use prefork pool for better isolation
        '--queues=transcription.high,transcription.normal,transcription.retry,transcription.dlq',
        '--autoscale=4,1',  # Autoscale between 1-4 workers based on load
        '--max-tasks-per-child=10',  # Restart worker after 10 tasks (prevent memory leaks)
        '--time-limit=3900',  # Hard time limit (65 minutes)
        '--soft-time-limit=3600',  # Soft time limit (60 minutes)
    ]

    try:
        celery_app.worker_main(argv)
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker crashed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
