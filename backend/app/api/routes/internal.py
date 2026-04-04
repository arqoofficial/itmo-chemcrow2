"""Internal endpoints — no auth, Docker-network only. Never expose to public internet."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.redis import get_sync_redis

logger = logging.getLogger(__name__)

# Lazy import guard: task module doesn't exist until Task 5 is implemented.
# The name must be at module level so unittest.mock.patch can target it.
try:
    from app.worker.tasks.continuation import run_s2_search  # noqa: F401
except ImportError:
    run_s2_search = None  # type: ignore[assignment]

router = APIRouter(prefix="/internal", tags=["internal"])


class QueueBackgroundToolRequest(BaseModel):
    type: str  # only "s2_search" supported
    conversation_id: str
    query: str
    max_results: int = 5


@router.post("/queue-background-tool", status_code=202)
def queue_background_tool(payload: QueueBackgroundToolRequest) -> dict:
    """Queue a background tool call. Called by ai-agent literature_search tool."""
    if payload.type != "s2_search":
        return {"status": "ignored", "reason": f"unknown type: {payload.type}"}

    # Persist query for retry support (24h TTL)
    r = get_sync_redis()
    r.set(
        f"s2_last_query:{payload.conversation_id}",
        payload.query,
        ex=24 * 3600,
    )

    run_s2_search.delay(payload.conversation_id, payload.query, payload.max_results)
    logger.info("Queued run_s2_search for conv=%s query=%r", payload.conversation_id, payload.query)
    return {"status": "queued"}
