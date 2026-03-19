from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "chemcrow2",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.worker.tasks.chat",
        "app.worker.tasks.example",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=240,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_queues={
        "default": {"exchange": "default", "routing_key": "default"},
        "chat": {"exchange": "chat", "routing_key": "chat"},
        "gpu": {"exchange": "gpu", "routing_key": "gpu"},
    },
    result_expires=86400,
)

celery_app.autodiscover_tasks()
