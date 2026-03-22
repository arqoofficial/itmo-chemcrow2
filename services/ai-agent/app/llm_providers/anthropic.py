from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from app.config import settings


def get_anthropic_model() -> ChatAnthropic:
    kwargs: dict = {
        "model": settings.ANTHROPIC_MODEL,
        "api_key": settings.ANTHROPIC_API_KEY,
        "temperature": 0,
        "streaming": True,
        "max_retries": 3,
    }
    if settings.ANTHROPIC_BASE_URL:
        kwargs["anthropic_api_url"] = settings.ANTHROPIC_BASE_URL
    return ChatAnthropic(**kwargs)
