from __future__ import annotations

from langchain.chat_models.base import BaseChatModel

from app.config import settings
from app.llm_providers.anthropic import get_anthropic_model
from app.llm_providers.openai import get_openai_model

_PROVIDERS: dict[str, callable] = {
    "openai": get_openai_model,
    "anthropic": get_anthropic_model,
}


def get_llm(provider: str | None = None) -> BaseChatModel:
    """Get an LLM instance by provider name. Defaults to config setting."""
    provider = provider or settings.DEFAULT_LLM_PROVIDER
    factory = _PROVIDERS.get(provider)
    if not factory:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Available: {list(_PROVIDERS)}")
    return factory()
