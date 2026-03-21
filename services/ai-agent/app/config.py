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

    # ---------------------------------------------------------------------------
    # RAG settings
    # ---------------------------------------------------------------------------
    # Master switch.  Set to false to disable both rag_search and
    # literature_citation_search without removing them from the tool registry.
    RAG_ENABLED: bool = True

    # Root data directory.  Kept for backward-compatibility with evaluate_rag.py
    # which constructs benchmark paths relative to this value.
    RAG_DATA_DIR: str = "app/data-rag"           # kept: used by evaluate_rag.py for benchmarks

    # Parent directory for all named source scopes.  Each scope is a
    # subdirectory here (e.g. "app/data-rag/sources/default/").
    # The ai-agent service bind-mounts the host's ./services/ai-agent/app/data-rag
    # to /app/app/data-rag inside the container, so all relative paths in this
    # file resolve correctly relative to the service WORKDIR (/app).
    RAG_SOURCES_DIR: str = "app/data-rag/sources"

    # The scope name passed to _get_retriever_for_scope() at query time.
    # Changing this is the primary way to point the agent at a different corpus
    # without restarting.  The value must match an existing subdirectory under
    # RAG_SOURCES_DIR.
    RAG_DEFAULT_SOURCE: str = "default"

    # ---------------------------------------------------------------------------
    # Derived path settings for the default scope
    #
    # These were added during the initial migration so that legacy scripts could
    # reference individual directories without re-implementing the scope path
    # logic.  _build_hybrid_retriever() now derives all paths from
    # RAG_SOURCES_DIR + the scope name, so these settings are no longer read
    # by the retriever itself.
    #
    # TODO: remove once _build_hybrid_retriever is fully scope-driven and all
    #       callers (e.g. evaluate_rag.py) have been updated to use RAG_SOURCES_DIR.
    # ---------------------------------------------------------------------------
    RAG_CORPUS_RAW_DIR: str = "app/data-rag/sources/default/corpus_raw"
    RAG_CORPUS_PROCESSED_DIR: str = "app/data-rag/sources/default/corpus_processed"
    RAG_BM25_INDEX_PATH: str = "app/data-rag/sources/default/indexes/bm25_index.json"
    RAG_DENSE_INDEX_DIR: str = "app/data-rag/sources/default/indexes/nomic_dense"

    # When true, both BM25 and dense indexes are rebuilt from the corpus on
    # every startup, ignoring any cached index files on disk.  Useful after
    # manually editing corpus_processed/ without changing raw documents (which
    # would otherwise not trigger a fingerprint mismatch).
    RAG_FORCE_REBUILD_INDEXES: bool = False

    # Matryoshka truncation dimension for nomic-embed-text-v1.5.  The model
    # produces 768-dimensional embeddings; truncating to 512 reduces memory
    # and dot-product cost by ~33% with negligible retrieval quality loss.
    # Must match the value used when the dense index was built — a mismatch
    # triggers an automatic rebuild.
    RAG_DENSE_MATRYOSHKA_DIM: int = 512

    # Number of documents encoded per SentenceTransformer.encode() call.
    # Larger values improve throughput on GPU but increase peak VRAM usage.
    RAG_DENSE_BATCH_SIZE: int = 16

    # RRF smoothing constant (k in the formula weight / (k + rank)).
    # The value 60 comes from Cormack et al. (2009) and works well across
    # most IR benchmarks.  Increase to flatten score differences between
    # highly-ranked and mid-ranked results; decrease to amplify them.
    RAG_RRF_K: int = 60

    # Per-retriever multiplicative weights in the RRF fusion formula.
    # Setting bm25_weight=0 disables BM25's contribution (dense-only mode)
    # and vice versa.  Equal weights (1.0 / 1.0) are recommended as a
    # starting point; tune based on evaluate_rag.py benchmark results.
    RAG_BM25_WEIGHT: float = 1.0
    RAG_DENSE_WEIGHT: float = 1.0

    # How many candidates each sub-retriever (BM25 and dense) fetches before
    # the RRF fusion step.  A larger pool gives the fusion more documents to
    # re-rank at the cost of slightly more computation.  Must be >= the
    # largest top_k value you expect to request.
    RAG_CANDIDATE_K: int = 20

    # Langfuse observability (optional)
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"


settings = Settings()  # type: ignore
