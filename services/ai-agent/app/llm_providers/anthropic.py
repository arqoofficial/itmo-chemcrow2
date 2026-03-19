from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from app.config import settings


def get_anthropic_model() -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.ANTHROPIC_MODEL,
        api_key=settings.ANTHROPIC_API_KEY,
        temperature=0,
        streaming=True,
    )
