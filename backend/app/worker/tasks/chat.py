"""
Celery task for processing chat messages via the AI Agent service.

Flow:
  1. Load conversation messages from DB
  2. Call AI Agent service (HTTP POST)
  3. Save assistant response to DB
  4. Publish result to Redis pub/sub for SSE streaming
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

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


@celery_app.task(
    bind=True,
    name="tasks.process_chat_message",
    queue="chat",
    soft_time_limit=120,
    time_limit=150,
)
def process_chat_message(
    self,
    conversation_id: str,
    user_id: str,
) -> dict:
    """
    Load conversation history, call AI agent, save response, publish SSE event.
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

        assistant_content = ai_response.get("content", "")
        tool_calls_json = None
        if ai_response.get("tool_calls"):
            tool_calls_json = json.dumps(ai_response["tool_calls"])

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
            "conversation_id": conversation_id,
            "message": {
                "id": msg_id,
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": tool_calls_json,
            },
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
            "error": error_msg,
        })
        raise

    except Exception as exc:
        error_msg = str(exc)
        logger.exception("Chat task failed for conversation %s", conversation_id)
        _publish(r, conversation_id, {
            "event": "error",
            "conversation_id": conversation_id,
            "error": error_msg,
        })
        raise
