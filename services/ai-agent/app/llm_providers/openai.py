from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.config import settings


def get_openai_model() -> ChatOpenAI:
    kwargs: dict = {
        "model": settings.OPENAI_MODEL,
        "api_key": settings.OPENAI_API_KEY,
        "temperature": 0,
        "streaming": True,
    }
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    return ChatOpenAI(**kwargs)
