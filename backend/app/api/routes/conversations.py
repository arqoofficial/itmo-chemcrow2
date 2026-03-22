"""
CRUD for conversations and messages + trigger AI agent via Celery.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    ChatMessage,
    ChatMessageCreate,
    ChatMessagePublic,
    ChatMessagesPublic,
    Conversation,
    ConversationCreate,
    ConversationPublic,
    ConversationsPublic,
    ConversationUpdate,
    Message,
    get_datetime_utc,
)
from app.worker.tasks import dispatch_chat_task

# Минимальный интервал между сообщениями пользователя в одном диалоге.
# Защита от спама: даже если nginx rate-limit обойдут, БД не даст чаще.
_MIN_MESSAGE_INTERVAL_SECONDS = 3

router = APIRouter(prefix="/conversations", tags=["conversations"])


# ──────────────────────── Conversations CRUD ────────────────────────


@router.post("/", response_model=ConversationPublic, status_code=201)
def create_conversation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: ConversationCreate,
) -> Any:
    conversation = Conversation.model_validate(
        body, update={"user_id": current_user.id}
    )
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


@router.get("/", response_model=ConversationsPublic)
def list_conversations(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = Query(default=50, le=200),
) -> Any:
    base = select(Conversation).where(Conversation.user_id == current_user.id)
    count_q = select(func.count()).select_from(Conversation).where(
        Conversation.user_id == current_user.id
    )
    count = session.exec(count_q).one()
    items = session.exec(
        base.order_by(col(Conversation.updated_at).desc()).offset(skip).limit(limit)
    ).all()
    return ConversationsPublic(data=items, count=count)


@router.get("/{conversation_id}", response_model=ConversationPublic)
def get_conversation(
    session: SessionDep,
    current_user: CurrentUser,
    conversation_id: uuid.UUID,
) -> Any:
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return conv


@router.patch("/{conversation_id}", response_model=ConversationPublic)
def update_conversation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
) -> Any:
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    update_data = body.model_dump(exclude_unset=True)
    conv.sqlmodel_update(update_data)
    conv.updated_at = get_datetime_utc()
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return conv


@router.delete("/{conversation_id}")
def delete_conversation(
    session: SessionDep,
    current_user: CurrentUser,
    conversation_id: uuid.UUID,
) -> Message:
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    session.delete(conv)
    session.commit()
    return Message(message="Conversation deleted")


# ──────────────────────── Messages ────────────────────────


@router.get("/{conversation_id}/messages", response_model=ChatMessagesPublic)
def list_messages(
    session: SessionDep,
    current_user: CurrentUser,
    conversation_id: uuid.UUID,
    skip: int = 0,
    limit: int = Query(default=100, le=500),
) -> Any:
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    base = select(ChatMessage).where(
        ChatMessage.conversation_id == conversation_id
    )
    count_q = select(func.count()).select_from(ChatMessage).where(
        ChatMessage.conversation_id == conversation_id
    )
    count = session.exec(count_q).one()
    messages = session.exec(
        base.order_by(col(ChatMessage.created_at).asc()).offset(skip).limit(limit)
    ).all()
    return ChatMessagesPublic(data=messages, count=count)


# ──────────────────────── Send message (triggers AI) ────────────────────────


@router.post(
    "/{conversation_id}/messages",
    response_model=ChatMessagePublic,
    status_code=201,
)
def send_message(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    conversation_id: uuid.UUID,
    body: ChatMessageCreate,
) -> Any:
    """
    Save a user message and dispatch a Celery task to get an AI response.

    The AI response will be streamed via SSE at:
      GET /api/v1/events/conversations/{conversation_id}
    """
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    # Rate-limit на уровне БД: проверяем время последнего сообщения пользователя
    last_user_msg = session.exec(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.role == "user",
        )
        .order_by(col(ChatMessage.created_at).desc())
        .limit(1)
    ).first()

    if last_user_msg is not None:
        now = get_datetime_utc()
        elapsed = (now - last_user_msg.created_at).total_seconds()
        if elapsed < _MIN_MESSAGE_INTERVAL_SECONDS:
            raise HTTPException(
                status_code=429,
                detail=f"Too many messages. Please wait {_MIN_MESSAGE_INTERVAL_SECONDS} seconds between messages.",
            )

    user_message = ChatMessage(
        conversation_id=conversation_id,
        role=body.role,
        content=body.content,
    )
    session.add(user_message)
    conv.updated_at = get_datetime_utc()
    session.add(conv)
    session.commit()
    session.refresh(user_message)

    dispatch_chat_task(
        conversation_id=str(conversation_id),
        user_id=str(current_user.id),
    )

    return user_message
