import time

import redis as redis_lib

from app.core.config import settings
from app.worker.celery_app import celery_app


@celery_app.task(bind=True, name="tasks.example_long_task")
def example_long_task(self: celery_app.Task, task_job_id: str, duration: int = 10) -> dict:  # type: ignore[name-defined]
    """Example long-running task that publishes progress via Redis pub/sub."""
    r = redis_lib.from_url(settings.REDIS_URL)
    channel = f"task:{task_job_id}"

    total_steps = 10
    for step in range(1, total_steps + 1):
        time.sleep(duration / total_steps)
        progress = int(step / total_steps * 100)
        self.update_state(state="PROGRESS", meta={"progress": progress})
        r.publish(
            channel,
            f'{{"status": "running", "progress": {progress}}}',
        )

    r.publish(
        channel,
        f'{{"status": "completed", "result": "Task {task_job_id} finished"}}',
    )
    return {"status": "completed", "task_job_id": task_job_id}
