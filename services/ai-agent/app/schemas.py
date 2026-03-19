from __future__ import annotations

from pydantic import BaseModel, Field


class MessageIn(BaseModel):
    role: str = "user"
    content: str


class ChatRequest(BaseModel):
    messages: list[MessageIn]
    conversation_id: str | None = None
    provider: str | None = Field(
        default=None,
        description="LLM provider override: 'openai' or 'anthropic'",
    )


class ChatResponse(BaseModel):
    role: str = "assistant"
    content: str
    tool_calls: list[dict] | None = None


class StreamEvent(BaseModel):
    event: str
    data: str
