import uuid
from datetime import datetime, timezone

from pydantic import EmailStr, model_validator
from sqlalchemy import Column, DateTime, JSON, Text
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)
    conversations: list["Conversation"] = Relationship(
        back_populates="user", cascade_delete=True
    )
    tasks: list["TaskJob"] = Relationship(
        back_populates="user", cascade_delete=True
    )


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(ItemBase):
    title: str | None = Field(default=None, min_length=1, max_length=255)  # type: ignore


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


# --- Conversation models ---


class ConversationBase(SQLModel):
    title: str = Field(max_length=255)


class ConversationCreate(ConversationBase):
    pass


class ConversationUpdate(SQLModel):
    title: str | None = Field(default=None, max_length=255)


class Conversation(ConversationBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    user: User | None = Relationship(back_populates="conversations")
    messages: list["ChatMessage"] = Relationship(
        back_populates="conversation", cascade_delete=True
    )


class ConversationPublic(ConversationBase):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationsPublic(SQLModel):
    data: list[ConversationPublic]
    count: int


# --- ChatMessage models ---


class ChatMessageCreate(SQLModel):
    role: str = Field(max_length=20)
    content: str


class ChatMessage(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    conversation_id: uuid.UUID = Field(
        foreign_key="conversation.id", nullable=False, ondelete="CASCADE", index=True
    )
    role: str = Field(max_length=20)
    content: str = Field(sa_type=Text())  # type: ignore
    tool_calls: str | None = Field(default=None, sa_type=Text())  # type: ignore
    msg_metadata: dict | None = Field(
        default=None, sa_column=Column("metadata", JSON, nullable=True)
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    conversation: Conversation | None = Relationship(back_populates="messages")


class ChatMessagePublic(SQLModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    tool_calls: str | None = None
    metadata: dict | None = None
    created_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _remap_msg_metadata(cls, data: object) -> object:
        """Map msg_metadata (ORM attr) → metadata (public field name)."""
        if hasattr(data, "msg_metadata"):
            return {
                "id": data.id,  # type: ignore[union-attr]
                "conversation_id": data.conversation_id,  # type: ignore[union-attr]
                "role": data.role,  # type: ignore[union-attr]
                "content": data.content,  # type: ignore[union-attr]
                "tool_calls": data.tool_calls,  # type: ignore[union-attr]
                "metadata": data.msg_metadata,  # type: ignore[union-attr]
                "created_at": data.created_at,  # type: ignore[union-attr]
            }
        if isinstance(data, dict) and "msg_metadata" in data:
            data = dict(data)
            data["metadata"] = data.pop("msg_metadata")
        return data


class ChatMessagesPublic(SQLModel):
    data: list[ChatMessagePublic]
    count: int


# --- TaskJob models ---


class TaskJobCreate(SQLModel):
    task_type: str = Field(max_length=50)
    input_data: str
    source: str = Field(default="manual", max_length=20)
    conversation_id: uuid.UUID | None = None


class TaskJob(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    task_type: str = Field(max_length=50)
    status: str = Field(default="pending", max_length=20, index=True)
    source: str = Field(default="manual", max_length=20)
    conversation_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="conversation.id",
        nullable=True,
        ondelete="SET NULL",
        index=True,
    )
    input_data: str = Field(sa_type=Text())  # type: ignore
    result_data: str | None = Field(default=None, sa_type=Text())  # type: ignore
    error: str | None = Field(default=None, sa_type=Text())  # type: ignore
    celery_task_id: str | None = Field(default=None, max_length=255, index=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    user: User | None = Relationship(back_populates="tasks")


class TaskJobPublic(SQLModel):
    id: uuid.UUID
    user_id: uuid.UUID
    task_type: str
    status: str
    source: str
    conversation_id: uuid.UUID | None = None
    input_data: str
    result_data: str | None = None
    error: str | None = None
    celery_task_id: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class TaskJobsPublic(SQLModel):
    data: list[TaskJobPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
