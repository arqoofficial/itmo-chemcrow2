import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from starlette.requests import Request
from sse_starlette import EventSourceResponse

from app.api.deps import CurrentUser, SessionDep
from app.core.redis import conversation_channel, get_async_redis, task_channel
from app.models import Conversation, TaskJob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/tasks/{task_id}")
async def task_events(
    task_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    current_user: CurrentUser,
) -> EventSourceResponse:
    """
    SSE stream for real-time task status updates.

    Events:
      - task_update: status/progress changes
      - task_completed: final result
      - task_failed: error details

    Stream auto-closes on terminal status (completed/failed).
    """
    task = session.get(TaskJob, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    initial_status = task.status
    initial_data = {
        "task_id": str(task_id),
        "status": task.status,
        "task_type": task.task_type,
    }
    if task.result_data:
        initial_data["result_data"] = task.result_data
    if task.error:
        initial_data["error"] = task.error

    async def event_generator():
        if initial_status in ("completed", "failed"):
            yield {
                "event": f"task_{initial_status}",
                "data": json.dumps(initial_data),
                "id": "initial",
            }
            return

        yield {
            "event": "task_update",
            "data": json.dumps(initial_data),
            "id": "initial",
        }

        r = get_async_redis()
        pubsub = r.pubsub()
        channel = task_channel(str(task_id))
        await pubsub.subscribe(channel)

        try:
            while True:
                if await request.is_disconnected():
                    break

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    data = message["data"]
                    parsed = json.loads(data) if isinstance(data, str) else data
                    status = parsed.get("status", "")

                    event_name = "task_update"
                    if status == "completed":
                        event_name = "task_completed"
                    elif status == "failed":
                        event_name = "task_failed"

                    yield {
                        "event": event_name,
                        "data": json.dumps(parsed),
                    }

                    if status in ("completed", "failed"):
                        break

                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.debug("SSE stream cancelled for task %s", task_id)
            raise
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return EventSourceResponse(
        event_generator(),
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
        ping=15,
    )


@router.get("/conversations/{conversation_id}")
async def conversation_events(
    conversation_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    current_user: CurrentUser,
) -> EventSourceResponse:
    """
    SSE stream for real-time chat updates in a conversation.

    Events:
      - thinking: agent is processing
      - message: new assistant message (complete)
      - error: processing error

    Stream stays open until client disconnects.
    """
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    async def event_generator():
        yield {
            "event": "connected",
            "data": json.dumps({"conversation_id": str(conversation_id)}),
            "id": "initial",
        }

        r = get_async_redis()
        pubsub = r.pubsub()
        channel = conversation_channel(str(conversation_id))
        await pubsub.subscribe(channel)

        try:
            while True:
                if await request.is_disconnected():
                    break

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    data = message["data"]
                    parsed = json.loads(data) if isinstance(data, str) else data
                    event_name = parsed.pop("event", "message")

                    yield {
                        "event": event_name,
                        "data": json.dumps(parsed),
                    }

                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.debug(
                "SSE stream cancelled for conversation %s", conversation_id
            )
            raise
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return EventSourceResponse(
        event_generator(),
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
        ping=15,
    )
