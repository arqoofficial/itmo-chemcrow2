import json
import logging
import time
from datetime import datetime, timezone

import redis as redis_lib
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.models import TaskJob
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_redis() -> redis_lib.Redis:
    return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


def _publish(r: redis_lib.Redis, task_job_id: str, data: dict) -> None:
    r.publish(f"task:{task_job_id}", json.dumps(data, default=str))


@celery_app.task(bind=True, name="tasks.example_long_task")
def example_long_task(self, task_job_id: str, duration: int = 10) -> dict:
    """
    Example long-running task with DB status tracking and Redis progress events.
    """
    r = _get_redis()

    with Session(engine) as session:
        task = session.get(TaskJob, task_job_id)
        if task:
            task.status = "running"
            task.celery_task_id = self.request.id
            session.add(task)
            session.commit()

    _publish(r, task_job_id, {"status": "running", "progress": 0})

    try:
        total_steps = 10
        for step in range(1, total_steps + 1):
            time.sleep(duration / total_steps)
            progress = int(step / total_steps * 100)
            self.update_state(state="PROGRESS", meta={"progress": progress})
            _publish(r, task_job_id, {"status": "running", "progress": progress})

        result = {"message": f"Task {task_job_id} completed successfully"}

        with Session(engine) as session:
            task = session.get(TaskJob, task_job_id)
            if task:
                task.status = "completed"
                task.result_data = json.dumps(result)
                task.completed_at = datetime.now(timezone.utc)
                session.add(task)
                session.commit()

        _publish(r, task_job_id, {"status": "completed", "result": result})
        return {"status": "completed", "task_job_id": task_job_id}

    except Exception as exc:
        error_msg = str(exc)
        logger.exception("Task %s failed", task_job_id)

        with Session(engine) as session:
            task = session.get(TaskJob, task_job_id)
            if task:
                task.status = "failed"
                task.error = error_msg
                task.completed_at = datetime.now(timezone.utc)
                session.add(task)
                session.commit()

        _publish(r, task_job_id, {"status": "failed", "error": error_msg})
        raise
