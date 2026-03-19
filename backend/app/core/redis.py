from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
import redis as sync_redis

from app.core.config import settings

_async_redis: aioredis.Redis | None = None
_sync_redis: sync_redis.Redis | None = None


def get_async_redis() -> aioredis.Redis:
    """Lazy singleton for async Redis client (pub/sub, SSE endpoints)."""
    global _async_redis
    if _async_redis is None:
        _async_redis = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
    return _async_redis


def get_sync_redis() -> sync_redis.Redis:
    """Lazy singleton for sync Redis client (Celery workers)."""
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = sync_redis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
    return _sync_redis


async def publish_event(channel: str, data: dict[str, Any]) -> None:
    """Async publish JSON event to a Redis pub/sub channel."""
    r = get_async_redis()
    await r.publish(channel, json.dumps(data, default=str))


def publish_event_sync(channel: str, data: dict[str, Any]) -> None:
    """Sync publish JSON event (for Celery workers)."""
    r = get_sync_redis()
    r.publish(channel, json.dumps(data, default=str))


def task_channel(task_id: str) -> str:
    """Build Redis channel name for a task."""
    return f"task:{task_id}"


def conversation_channel(conversation_id: str) -> str:
    """Build Redis channel name for a conversation (chat streaming)."""
    return f"conversation:{conversation_id}"
