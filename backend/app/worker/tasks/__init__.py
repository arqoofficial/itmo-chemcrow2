"""
Task registry: maps task_type strings to Celery task names.

To register a new task type:
  1. Create a Celery task in this package (e.g. retrosynthesis.py)
  2. Add an entry to TASK_REGISTRY below
  3. Optionally specify a non-default queue in TASK_QUEUES
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.worker.celery_app import celery_app

if TYPE_CHECKING:
    from app.models import TaskJob

logger = logging.getLogger(__name__)

TASK_REGISTRY: dict[str, str] = {
    "example": "tasks.example_long_task",
    "chat": "tasks.process_chat_message",
}

TASK_QUEUES: dict[str, str] = {
    "retrosynthesis": "gpu",
    "chat": "chat",
}

DEFAULT_QUEUE = "default"


def dispatch_task(task_job: TaskJob) -> str:
    """
    Dispatch a Celery task based on TaskJob.task_type.
    Returns the Celery async result ID.
    """
    celery_task_name = TASK_REGISTRY.get(task_job.task_type)
    if not celery_task_name:
        raise ValueError(f"Unknown task_type: {task_job.task_type!r}")

    queue = TASK_QUEUES.get(task_job.task_type, DEFAULT_QUEUE)

    result = celery_app.send_task(
        celery_task_name,
        kwargs={"task_job_id": str(task_job.id)},
        queue=queue,
    )
    logger.info(
        "Dispatched %s (job=%s, celery=%s, queue=%s)",
        celery_task_name,
        task_job.id,
        result.id,
        queue,
    )
    return result.id


def dispatch_chat_task(conversation_id: str, user_id: str) -> str:
    """
    Dispatch a chat processing task to the 'chat' Celery queue.
    Returns the Celery async result ID.
    """
    result = celery_app.send_task(
        "tasks.process_chat_message",
        kwargs={
            "conversation_id": conversation_id,
            "user_id": user_id,
        },
        queue="chat",
    )
    logger.info(
        "Dispatched chat task (conversation=%s, celery=%s)",
        conversation_id,
        result.id,
    )
    return result.id


def revoke_task(task_job: TaskJob) -> None:
    """Revoke a Celery task by its celery_task_id."""
    if task_job.celery_task_id:
        celery_app.control.revoke(task_job.celery_task_id, terminate=True)
        logger.info(
            "Revoked celery task %s (job=%s)", task_job.celery_task_id, task_job.id
        )
