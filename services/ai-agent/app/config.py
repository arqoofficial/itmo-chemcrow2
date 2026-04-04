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
    BACKEND_INTERNAL_URL: str = "http://backend:8000"

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

    # RAG settings
    RAG_ENABLED: bool = True
    RAG_DATA_DIR: str = "app/data-rag"  # used by evaluation scripts for benchmark files
    RAG_SOURCES_DIR: str = "app/data-rag/sources"
    RAG_DEFAULT_SOURCE: str = "default"
    # Legacy default-source paths retained for backwards compatibility with local tooling.
    RAG_CORPUS_RAW_DIR: str = "app/data-rag/sources/default/corpus_raw"
    RAG_CORPUS_PROCESSED_DIR: str = "app/data-rag/sources/default/corpus_processed"
    RAG_BM25_INDEX_PATH: str = "app/data-rag/sources/default/indexes/bm25_index.json"
    RAG_DENSE_INDEX_DIR: str = "app/data-rag/sources/default/indexes/nomic_dense"
    RAG_FORCE_REBUILD_INDEXES: bool = False
    RAG_DENSE_MATRYOSHKA_DIM: int = 512
    RAG_DENSE_BATCH_SIZE: int = 16
    RAG_RRF_K: int = 60
    RAG_BM25_WEIGHT: float = 1.0
    RAG_DENSE_WEIGHT: float = 1.0
    RAG_CANDIDATE_K: int = 20

    # MinIO for parsed article chunks
    ARTICLES_MINIO_ENDPOINT: str = "articles-minio:9000"
    ARTICLES_MINIO_ACCESS_KEY: str = "minioadmin"
    ARTICLES_MINIO_SECRET_KEY: str = "minioadmin"
    ARTICLES_MINIO_PARSED_BUCKET: str = "parsed-chunks"
    ARTICLES_MINIO_SECURE: bool = False

    # Langfuse observability (optional)
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "http://langfuse-server:3000"


settings = Settings()  # type: ignore
