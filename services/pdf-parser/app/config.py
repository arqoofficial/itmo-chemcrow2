from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Redis
    REDIS_URL: str = "redis://localhost:6379/1"
    REDIS_JOB_TTL: int = 86400  # seconds; 24 h

    # articles-minio (shared with article-fetcher)
    ARTICLES_MINIO_ENDPOINT: str = "articles-minio:9000"
    ARTICLES_MINIO_ACCESS_KEY: str = "minioadmin"
    ARTICLES_MINIO_SECRET_KEY: str = "minioadmin"
    ARTICLES_MINIO_INPUT_BUCKET: str = "articles"        # PDFs live here
    ARTICLES_MINIO_OUTPUT_BUCKET: str = "parsed-chunks"  # chunks written here
    ARTICLES_MINIO_SECURE: bool = False

    # ai-agent ingest webhook
    AI_AGENT_INGEST_URL: str = "http://ai-agent:8000"

    # LLM (OpenAI-compatible)
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str = "openai/gpt-3.5-turbo"

    # Langfuse (optional tracing)
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_BASE_URL: str | None = None

    ENVIRONMENT: str = "development"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
