"""Celery task that delegates multi-step retrosynthesis to the microservice."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import requests
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.core.redis import publish_event_sync, task_channel
from app.models import TaskJob
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.retrosynthesis_multi_step",
    soft_time_limit=150,
    time_limit=180,
)
def retrosynthesis_multi_step(self, task_job_id: str) -> dict:
    """Call retrosynthesis microservice and persist the result."""

    channel = task_channel(task_job_id)

    with Session(engine) as session:
        task = session.get(TaskJob, task_job_id)
        if not task:
            raise ValueError(f"TaskJob {task_job_id} not found")
        input_data: dict = json.loads(task.input_data)
        task.status = "running"
        task.celery_task_id = self.request.id
        session.add(task)
        session.commit()

    publish_event_sync(channel, {"status": "running", "progress": 0})

    try:
        response = requests.post(
            f"{settings.RETROSYNTHESIS_URL}/api/v1/run",
            json=input_data,
            timeout=settings.RETROSYNTHESIS_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()

        with Session(engine) as session:
            task = session.get(TaskJob, task_job_id)
            if task:
                task.status = "completed"
                task.result_data = json.dumps(result, default=str)
                task.completed_at = datetime.now(timezone.utc)
                session.add(task)
                session.commit()

        publish_event_sync(channel, {"status": "completed", "result": result})
        return {"status": "completed", "task_job_id": task_job_id}

    except requests.HTTPError as exc:
        error_msg = f"Retrosynthesis service error: {exc.response.text[:500]}"
        logger.exception("Task %s HTTP error", task_job_id)
        _fail_task(task_job_id, error_msg, channel)
        raise

    except requests.Timeout:
        error_msg = "Retrosynthesis timed out"
        logger.error("Task %s timed out", task_job_id)
        _fail_task(task_job_id, error_msg, channel)
        raise

    except Exception as exc:
        error_msg = str(exc)
        logger.exception("Task %s failed", task_job_id)
        _fail_task(task_job_id, error_msg, channel)
        raise


def _fail_task(task_job_id: str, error_msg: str, channel: str) -> None:
    with Session(engine) as session:
        task = session.get(TaskJob, task_job_id)
        if task:
            task.status = "failed"
            task.error = error_msg
            task.completed_at = datetime.now(timezone.utc)
            session.add(task)
            session.commit()
    publish_event_sync(channel, {"status": "failed", "error": error_msg})
