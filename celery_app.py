"""
Celery application configuration for async transcription processing.

Configures:
- Redis broker and result backend
- Task routing to different queues (high priority, normal, DLQ)
- Retry policies and error handling
- Dead letter queue for failed tasks
"""

import logging
from celery import Celery, signals
from celery.signals import task_failure

from config import config

logger = logging.getLogger(__name__)

# Create Celery application
celery_app = Celery('transcription')

# Configure Celery
celery_app.conf.update(
    # Broker and backend
    broker_url=config.celery_broker_url,
    result_backend=config.celery_result_backend,

    # Serialization
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,

    # Task routing - map tasks to queues
    task_routes={
        'tasks.transcribe_audio_task': {'queue': 'transcription.normal'},
        'tasks.convert_video_task': {'queue': 'transcription.normal'},
        'tasks.dlq_handler_task': {'queue': 'transcription.dlq'},
        'tasks.repair_and_retry_task': {'queue': 'transcription.retry'},
    },

    # Default queue
    task_default_queue='transcription.normal',
    task_default_exchange='transcription',
    task_default_routing_key='transcription.normal',

    # Task execution
    task_acks_late=True,  # Acknowledge only after task completes (prevents message loss)
    task_reject_on_worker_lost=True,  # Re-queue if worker dies
    worker_prefetch_multiplier=1,  # One task per worker at a time (prevents hogging)
    worker_max_tasks_per_child=10,  # Restart worker after N tasks (prevents memory leaks)

    # Time limits
    task_time_limit=config.celery_task_timeout,  # Hard limit (kills task)
    task_soft_time_limit=config.celery_task_timeout - 60,  # Soft limit (raises exception)

    # Results
    result_expires=86400,  # Results expire after 24 hours
    result_persistent=True,  # Persist results to backend

    # Monitoring
    worker_send_task_events=True,  # Enable task events for monitoring
    task_send_sent_event=True,  # Send event when task is sent

    # Error handling
    task_annotations={
        '*': {
            'on_failure': lambda self, exc, task_id, args, kwargs, einfo: send_to_dlq(
                task_id, exc, str(einfo), args, kwargs
            ),
        }
    },
)


def send_to_dlq(task_id: str, exc: Exception, traceback: str, args: tuple, kwargs: dict):
    """
    Send failed task to Dead Letter Queue for manual review.

    This handler is called automatically when a task fails after all retries.

    Args:
        task_id: Celery task ID
        exc: Exception that caused the failure
        traceback: Full traceback string
        args: Task positional arguments
        kwargs: Task keyword arguments
    """
    try:
        # Avoid circular import
        from tasks import dlq_handler_task

        logger.error(
            f"Task {task_id} failed permanently, sending to DLQ: {exc}",
            extra={
                'task_id': task_id,
                'exception': str(exc),
                'args': args,
                'kwargs': kwargs
            }
        )

        # Submit to DLQ queue for processing
        dlq_handler_task.apply_async(
            kwargs={
                'task_id': task_id,
                'exception': str(exc),
                'traceback': traceback,
                'args': list(args),  # Convert tuple to list for JSON serialization
                'kwargs': kwargs
            },
            queue='transcription.dlq',
            priority=1  # Low priority
        )
    except Exception as dlq_error:
        # If DLQ submission fails, log but don't raise (avoid recursive errors)
        logger.error(f"Failed to send task {task_id} to DLQ: {dlq_error}", exc_info=True)


@signals.worker_ready.connect
def on_worker_ready(sender, **kwargs):
    """Called when Celery worker is ready to accept tasks."""
    logger.info(
        "Celery worker ready",
        extra={
            'hostname': sender.hostname,
            'queues': list(sender.app.amqp.queues.keys())
        }
    )


@signals.worker_shutdown.connect
def on_worker_shutdown(sender, **kwargs):
    """Called when Celery worker is shutting down."""
    logger.info(
        "Celery worker shutting down",
        extra={'hostname': sender.hostname}
    )


@task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, einfo=None, **kw):
    """
    Signal handler for task failures.

    Logs detailed failure information for debugging.
    """
    logger.error(
        f"Task failure: {sender.name}",
        extra={
            'task_id': task_id,
            'task_name': sender.name,
            'exception': str(exception),
            'args': args,
            'kwargs': kwargs
        },
        exc_info=einfo
    )


# Import tasks to register them with Celery
# This must be done after celery_app is configured
try:
    import tasks  # noqa: F401
    logger.info("Celery tasks registered successfully")
except ImportError as e:
    logger.warning(f"Could not import tasks module (this is expected during initial setup): {e}")
