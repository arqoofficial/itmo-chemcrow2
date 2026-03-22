"""
Celery task for processing chat messages via the AI Agent service.

Flow:
  1. Load conversation messages from DB
  2. Call AI Agent streaming endpoint (SSE)
  3. Forward tokens to Redis pub/sub in real time
  4. Save assembled assistant response to DB
  5. Publish final message event
"""
from __future__ import annotations

import json
import logging
import re

import httpx
import redis as redis_lib
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.models import ChatMessage, Conversation, get_datetime_utc
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_redis() -> redis_lib.Redis:
    return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


def _publish(r: redis_lib.Redis, conversation_id: str, data: dict) -> None:
    r.publish(f"conversation:{conversation_id}", json.dumps(data, default=str))


def _iter_sse_events(response: httpx.Response):
    """Parse SSE events from an httpx streaming response."""
    event_type = "message"
    data_buf: list[str] = []

    for line in response.iter_lines():
        if not line:
            if data_buf:
                yield event_type, "\n".join(data_buf)
                event_type = "message"
                data_buf = []
            continue

        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_buf.append(line[5:].strip())
        # ignore comments (lines starting with ':')

    if data_buf:
        yield event_type, "\n".join(data_buf)


def _extract_dois(tool_output: str) -> list[str]:
    """Extract unique, non-N/A DOIs from a literature_search tool output string."""
    seen: set[str] = set()
    result: list[str] = []
    for match in re.finditer(r"DOI:\s*(\S+)", tool_output):
        doi = match.group(1)
        if doi != "N/A" and doi not in seen:
            seen.add(doi)
            result.append(doi)
    return result


def _get_conversation_article_jobs(r: redis_lib.Redis, conversation_id: str) -> list[dict]:
    """Return all stored {doi, job_id} pairs for a conversation from Redis."""
    raw = r.lrange(f"conversation:{conversation_id}:article_jobs", 0, -1)
    return [json.loads(item) for item in raw]


def _build_article_status_block(jobs: list[dict]) -> str:
    """Format a status summary string for injection into the AI agent context."""
    if not jobs:
        return ""
    label_map = {"done": "available", "failed": "failed"}
    lines = ["[Article Download Status]"]
    for job in jobs:
        label = label_map.get(job.get("status", ""), "downloading")
        lines.append(f"- {job['doi']}: {label}")
    return "\n".join(lines)


def _process_streaming(
    conversation_id: str,
    messages_payload: list[dict],
    r: redis_lib.Redis,
) -> tuple[str, list[dict] | None]:
    """Stream from ai-agent, forward tokens via Redis, return assembled content and tool_calls."""
    content_parts: list[str] = []
    tool_calls: list[dict] = []

    timeout = httpx.Timeout(
        connect=10.0,
        read=settings.AI_AGENT_TIMEOUT,
        write=10.0,
        pool=10.0,
    )

    with httpx.Client(timeout=timeout) as client:
        with client.stream(
            "POST",
            f"{settings.AI_AGENT_URL}/api/v1/chat/stream",
            json={
                "messages": messages_payload,
                "conversation_id": conversation_id,
            },
        ) as response:
            response.raise_for_status()
            for event_type, data_str in _iter_sse_events(response):
                try:
                    data = json.loads(data_str)
                except (json.JSONDecodeError, ValueError):
                    continue

                if event_type == "token":
                    chunk = data.get("content", "")
                    if chunk:
                        content_parts.append(chunk)
                        _publish(r, conversation_id, {
                            "event": "token",
                            "content": chunk,
                        })

                elif event_type == "tool_start":
                    tool_calls.append({
                        "name": data.get("tool", ""),
                        "args": data.get("input", {}),
                    })
                    _publish(r, conversation_id, {
                        "event": "tool_call",
                        "name": data.get("tool", ""),
                        "args": data.get("input", {}),
                    })

                elif event_type == "tool_end":
                    _publish(r, conversation_id, {
                        "event": "tool_end",
                        "tool": data.get("tool", ""),
                        "output": data.get("output", ""),
                    })

                elif event_type == "hazards":
                    _publish(r, conversation_id, {
                        "event": "hazards",
                        "chemicals": data.get("chemicals", []),
                    })

                elif event_type == "error":
                    raise RuntimeError(data.get("error", "Unknown AI agent error"))

    assembled = "".join(content_parts)
    return assembled, tool_calls if tool_calls else None


def _process_sync(
    conversation_id: str,
    messages_payload: list[dict],
) -> tuple[str, list[dict] | None]:
    """Fallback: call the synchronous ai-agent endpoint."""
    with httpx.Client(timeout=settings.AI_AGENT_TIMEOUT) as client:
        response = client.post(
            f"{settings.AI_AGENT_URL}/api/v1/chat",
            json={
                "messages": messages_payload,
                "conversation_id": conversation_id,
            },
        )
        response.raise_for_status()
        ai_response = response.json()

    return ai_response.get("content", ""), ai_response.get("tool_calls")


@celery_app.task(
    bind=True,
    name="tasks.process_chat_message",
    queue="chat",
    soft_time_limit=settings.CHAT_TASK_SOFT_TIME_LIMIT,
    time_limit=settings.CHAT_TASK_HARD_TIME_LIMIT,
)
def process_chat_message(
    self,
    conversation_id: str,
    user_id: str,
) -> dict:
    """
    Load conversation history, call AI agent with streaming,
    forward tokens via Redis, save final response to DB.
    """
    r = _get_redis()

    _publish(r, conversation_id, {
        "event": "thinking",
        "conversation_id": conversation_id,
    })

    try:
        with Session(engine) as session:
            conv = session.get(Conversation, conversation_id)
            if not conv:
                raise ValueError(f"Conversation {conversation_id} not found")

            messages_db = session.exec(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(col(ChatMessage.created_at).asc())
            ).all()

            messages_payload = [
                {"role": msg.role, "content": msg.content}
                for msg in messages_db
            ]

        try:
            assistant_content, tool_calls_raw = _process_streaming(
                conversation_id, messages_payload, r,
            )
        except Exception:
            logger.warning(
                "Streaming failed for conversation %s, falling back to sync",
                conversation_id,
                exc_info=True,
            )
            assistant_content, tool_calls_raw = _process_sync(
                conversation_id, messages_payload,
            )

        tool_calls_json = json.dumps(tool_calls_raw) if tool_calls_raw else None

        with Session(engine) as session:
            assistant_message = ChatMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_content,
                tool_calls=tool_calls_json,
            )
            session.add(assistant_message)

            conv = session.get(Conversation, conversation_id)
            if conv:
                conv.updated_at = get_datetime_utc()
                session.add(conv)

            session.commit()
            session.refresh(assistant_message)
            msg_id = str(assistant_message.id)

        _publish(r, conversation_id, {
            "event": "message",
            "id": msg_id,
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": tool_calls_json,
            "created_at": str(assistant_message.created_at),
        })

        return {
            "status": "completed",
            "conversation_id": conversation_id,
            "message_id": msg_id,
        }

    except httpx.HTTPStatusError as exc:
        error_msg = f"AI Agent returned {exc.response.status_code}: {exc.response.text}"
        logger.exception("Chat task failed for conversation %s", conversation_id)
        _publish(r, conversation_id, {
            "event": "error",
            "conversation_id": conversation_id,
            "detail": error_msg,
        })
        raise

    except Exception as exc:
        error_msg = str(exc)
        logger.exception("Chat task failed for conversation %s", conversation_id)
        _publish(r, conversation_id, {
            "event": "error",
            "conversation_id": conversation_id,
            "detail": error_msg,
        })
        raise
