from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )

    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM providers
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4-turbo"
    OPENAI_BASE_URL: str = ""

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    ANTHROPIC_BASE_URL: str = ""

    DEFAULT_LLM_PROVIDER: Literal["openai", "anthropic"] = "openai"

    # Internal service URLs
    BACKEND_URL: str = "http://backend:8000"

    # Optional tool API keys
    SERP_API_KEY: str = ""
    CHEMSPACE_API_KEY: str = ""
    SEMANTIC_SCHOLAR_API_KEY: str = ""

    # Reaction containers
    REACTION_PREDICT_URL: str = "http://reaction-predict:8051"
    RETROSYNTHESIS_URL: str = "http://retrosynthesis:8052"

    # Agent limits
    AGENT_MAX_ITERATIONS: int = 10
    AGENT_TIMEOUT_SECONDS: int = 120

    # Langfuse observability (optional)
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "http://langfuse-server:3000"


settings = Settings()  # type: ignore
