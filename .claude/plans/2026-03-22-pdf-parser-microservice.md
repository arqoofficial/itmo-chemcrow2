# PDF Parser Microservice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone FastAPI microservice that receives a webhook from the article-fetcher when a PDF has been downloaded, downloads the PDF from MinIO (articles-minio), processes it asynchronously (Docling → LLM cleaning → BM25 chunks), stores the parsed chunk files back to the same MinIO under a conversation-scoped path, and notifies the ai-agent to pull those chunks into its RAG corpus.

**Architecture:** `POST /jobs` accepts a JSON webhook payload `{job_id, doi, object_key, conversation_id}` from the article-fetcher, creates a Redis job record, and spawns a FastAPI `BackgroundTask`. The background worker downloads the PDF from `articles-minio` (bucket `articles`), runs Docling + LLM cleaning in a thread executor + asyncio.gather, uploads the resulting chunk files to `articles-minio` (bucket `parsed-chunks`) under the path `{conversation_id}/{doc_key}/`, then POSTs `{conversation_id, doc_key}` to the ai-agent's `POST /rag/ingest` endpoint. Clients poll `GET /jobs/{job_id}` for status.

**Integration Design:** See `.claude/plans/2026-03-22-pdf-parser-rag-integration-design.md`

**Tech Stack:** FastAPI, Redis (`redis-py` async), MinIO (`minio` SDK), Docling, LangChain + LiteLLM, python-dotenv, pytest, uv

---

## File Map

```
services/pdf-parser/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI app, lifespan, routes
│   ├── config.py         # Pydantic settings (Redis, MinIO, LLM, ai-agent env vars)
│   ├── schemas.py        # IngestWebhookPayload, JobStatus, JobState, JobStatusResponse
│   ├── redis_store.py    # Async CRUD for job state in Redis
│   ├── minio_store.py    # MinIO upload/download helpers (articles-minio)
│   └── parser.py         # PDF processing pipeline (adapted from parse_pdfs.py)
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_schemas.py
│   ├── test_redis_store.py
│   ├── test_minio_store.py
│   ├── test_parser.py
│   └── test_api.py
├── pyproject.toml
└── Dockerfile
compose.yml               # Add pdf-parser service; reuse articles-minio (modify existing)
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `services/pdf-parser/pyproject.toml`
- Create: `services/pdf-parser/Dockerfile`
- Create: `services/pdf-parser/app/__init__.py`
- Create: `services/pdf-parser/tests/__init__.py`

- [ ] **Step 1: Create `services/pdf-parser/pyproject.toml`**

```toml
[project]
name = "pdf-parser"
version = "0.1.0"
description = "PDF parsing microservice — Docling + LLM cleaning + MinIO storage"
requires-python = ">=3.11,<4.0"
dependencies = [
    "fastapi[standard]>=0.114.2,<1.0.0",
    "uvicorn[standard]>=0.30.0,<1.0.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.2.0,<3.0.0",
    "redis>=5.0.0,<6.0.0",
    "minio>=7.2.0,<8.0.0",
    "httpx>=0.25.0",
    "langchain>=0.3.0",
    "langchain-openai>=0.3.0",
    "langchain-core>=0.3.0",
    "langdetect>=1.0.9",
    "docling>=2.0.0",
    "spacy>=3.7.0",
    "python-dotenv>=1.0.0",
    # langfuse is optional; install manually for LLM call tracing
    # "langfuse>=3.9.0",
]

[dependency-groups]
dev = [
    "pytest>=7.4.3",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.25.0",
    "fakeredis>=2.20.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create `services/pdf-parser/Dockerfile`**

```dockerfile
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY services/pdf-parser/pyproject.toml .
COPY services/pdf-parser/app ./app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .

# Pre-download spaCy models
RUN python -m spacy download en_core_web_sm && \
    python -m spacy download ru_core_news_sm

EXPOSE 8300

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8300"]
```

Note: port is **8300** (8200 is article-fetcher).

- [ ] **Step 3: Create empty `__init__.py` files**

Both files are empty.

- [ ] **Step 4: Commit**

```bash
git add services/pdf-parser/
git commit -m "chore(pdf-parser): scaffold project structure"
```

---

## Task 2: Config Module

**Files:**
- Create: `services/pdf-parser/app/config.py`
- Create: `services/pdf-parser/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
def test_settings_have_required_fields():
    from app.config import settings
    assert hasattr(settings, "REDIS_URL")
    assert hasattr(settings, "ARTICLES_MINIO_ENDPOINT")
    assert hasattr(settings, "ARTICLES_MINIO_ACCESS_KEY")
    assert hasattr(settings, "ARTICLES_MINIO_SECRET_KEY")
    assert hasattr(settings, "ARTICLES_MINIO_INPUT_BUCKET")
    assert hasattr(settings, "ARTICLES_MINIO_OUTPUT_BUCKET")
    assert hasattr(settings, "AI_AGENT_INGEST_URL")
    assert hasattr(settings, "OPENAI_API_KEY")

def test_settings_defaults():
    from app.config import settings
    assert settings.ARTICLES_MINIO_INPUT_BUCKET == "articles"
    assert settings.ARTICLES_MINIO_OUTPUT_BUCKET == "parsed-chunks"
    assert settings.REDIS_JOB_TTL == 86400
    assert settings.AI_AGENT_INGEST_URL == "http://ai-agent:8000"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/pdf-parser && uv run pytest tests/test_config.py -v
```
Expected: FAIL with `ImportError` or `AttributeError`

- [ ] **Step 3: Write `app/config.py`**

```python
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


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
    OPENAI_API_KEY: str = "sk-placeholder"
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str = "openai/gpt-3.5-turbo"

    # Langfuse (optional tracing)
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_BASE_URL: str | None = None

    ENVIRONMENT: str = "development"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd services/pdf-parser && uv run pytest tests/test_config.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/pdf-parser/app/config.py services/pdf-parser/tests/test_config.py
git commit -m "feat(pdf-parser): add config module with pydantic settings"
```

---

## Task 3: Pydantic Schemas

**Files:**
- Create: `services/pdf-parser/app/schemas.py`
- Create: `services/pdf-parser/tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schemas.py
from app.schemas import JobStatus, JobState, IngestWebhookPayload


def test_job_status_values():
    assert JobStatus.PENDING == "pending"
    assert JobStatus.RUNNING == "running"
    assert JobStatus.COMPLETED == "completed"
    assert JobStatus.FAILED == "failed"


def test_job_state_serialization():
    job = JobState(
        job_id="abc123",
        status=JobStatus.PENDING,
        doi="10.1234/test",
        doc_key="10_1234_test",
        conversation_id="conv-999",
    )
    data = job.model_dump()
    assert data["job_id"] == "abc123"
    assert data["status"] == "pending"
    assert data["error"] is None
    assert data["artifacts"] == {}
    assert data["conversation_id"] == "conv-999"
    assert data["doc_key"] == "10_1234_test"


def test_ingest_webhook_payload():
    payload = IngestWebhookPayload(
        job_id="j1",
        doi="10.1038/s41586-021-03819-2",
        object_key="j1.pdf",
        conversation_id="conv-001",
    )
    assert payload.doc_key == "10_1038_s41586-021-03819-2"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/pdf-parser && uv run pytest tests/test_schemas.py -v
```

- [ ] **Step 3: Write `app/schemas.py`**

```python
from enum import Enum
from pydantic import BaseModel, model_validator


def _doi_to_doc_key(doi: str) -> str:
    """Convert a DOI to a filesystem-safe doc key."""
    return doi.replace("/", "_").replace(".", "_")


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestWebhookPayload(BaseModel):
    """Payload sent by article-fetcher when a PDF download completes."""
    job_id: str
    doi: str
    object_key: str       # MinIO key of the PDF in the 'articles' bucket
    conversation_id: str

    @property
    def doc_key(self) -> str:
        return _doi_to_doc_key(self.doi)


class JobState(BaseModel):
    job_id: str
    status: JobStatus
    doi: str
    doc_key: str
    conversation_id: str
    error: str | None = None
    # Maps artifact name to MinIO object key
    artifacts: dict[str, str] = {}
    created_at: float | None = None
    updated_at: float | None = None


class JobSubmitResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    doi: str
    doc_key: str
    conversation_id: str
    error: str | None = None
    artifacts: dict[str, str] = {}

    @classmethod
    def from_job(cls, job: "JobState") -> "JobStatusResponse":
        return cls.model_validate(job.model_dump(exclude={"created_at", "updated_at"}))
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/pdf-parser && uv run pytest tests/test_schemas.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/pdf-parser/app/schemas.py services/pdf-parser/tests/test_schemas.py
git commit -m "feat(pdf-parser): add job schemas with IngestWebhookPayload"
```

---

## Task 4: Redis Job Store

**Files:**
- Create: `services/pdf-parser/app/redis_store.py`
- Create: `services/pdf-parser/tests/test_redis_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_redis_store.py
import time
import pytest
import fakeredis.aioredis
from app.redis_store import RedisJobStore
from app.schemas import JobState, JobStatus


@pytest.fixture
async def store():
    fake = fakeredis.aioredis.FakeRedis()
    return RedisJobStore(redis=fake, ttl=60)


async def test_create_and_get_job(store):
    job = JobState(
        job_id="j1", status=JobStatus.PENDING,
        doi="10.1234/test", doc_key="10_1234_test",
        conversation_id="conv-1",
        created_at=time.time(), updated_at=time.time(),
    )
    await store.save(job)
    fetched = await store.get("j1")
    assert fetched is not None
    assert fetched.status == JobStatus.PENDING
    assert fetched.conversation_id == "conv-1"


async def test_get_missing_job_returns_none(store):
    result = await store.get("nonexistent")
    assert result is None


async def test_update_status(store):
    job = JobState(
        job_id="j2", status=JobStatus.PENDING,
        doi="10.1234/test", doc_key="10_1234_test",
        conversation_id="conv-2",
        created_at=time.time(), updated_at=time.time(),
    )
    await store.save(job)
    await store.update("j2", status=JobStatus.COMPLETED, artifacts={"chunk_000": "parsed-chunks/conv-2/10_1234_test/_chunks/chunk_000.md"})
    fetched = await store.get("j2")
    assert fetched.status == JobStatus.COMPLETED
    assert "chunk_000" in fetched.artifacts


async def test_update_failure(store):
    job = JobState(
        job_id="j3", status=JobStatus.RUNNING,
        doi="10.1234/test", doc_key="10_1234_test",
        conversation_id="conv-3",
        created_at=time.time(), updated_at=time.time(),
    )
    await store.save(job)
    await store.update("j3", status=JobStatus.FAILED, error="Docling crashed")
    fetched = await store.get("j3")
    assert fetched.status == JobStatus.FAILED
    assert fetched.error == "Docling crashed"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/pdf-parser && uv run pytest tests/test_redis_store.py -v
```

- [ ] **Step 3: Write `app/redis_store.py`**

```python
import logging
import time

from redis.asyncio import Redis

from app.schemas import JobState, JobStatus

log = logging.getLogger(__name__)

_KEY_PREFIX = "pdf_parser:job:"


class RedisJobStore:
    def __init__(self, redis: Redis, ttl: int = 86400):
        self._r = redis
        self._ttl = ttl

    def _key(self, job_id: str) -> str:
        return f"{_KEY_PREFIX}{job_id}"

    async def save(self, job: JobState) -> None:
        await self._r.set(self._key(job.job_id), job.model_dump_json(), ex=self._ttl)
        log.info("redis_store: saved job %s status=%s", job.job_id, job.status)

    async def get(self, job_id: str) -> JobState | None:
        raw = await self._r.get(self._key(job_id))
        if raw is None:
            return None
        return JobState.model_validate_json(raw)

    async def update(self, job_id: str, **fields) -> None:
        job = await self.get(job_id)
        if job is None:
            log.warning("redis_store: update on missing job %s", job_id)
            return
        updated = job.model_copy(update={**fields, "updated_at": time.time()})
        await self.save(updated)
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/pdf-parser && uv run pytest tests/test_redis_store.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/pdf-parser/app/redis_store.py services/pdf-parser/tests/test_redis_store.py
git commit -m "feat(pdf-parser): add Redis job store with CRUD operations"
```

---

## Task 5: MinIO Store

**Files:**
- Create: `services/pdf-parser/app/minio_store.py`
- Create: `services/pdf-parser/tests/test_minio_store.py`

The store wraps a single `minio` client but is configured with two buckets: one for reading PDFs (`articles`) and one for writing parsed chunks (`parsed-chunks`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_minio_store.py
import io
import pytest
from unittest.mock import MagicMock
from app.minio_store import MinioStore


@pytest.fixture
def store():
    mock_client = MagicMock()
    mock_client.bucket_exists.return_value = True
    return MinioStore(
        client=mock_client,
        input_bucket="articles",
        output_bucket="parsed-chunks",
    )


def test_download_pdf(store):
    mock_response = MagicMock()
    mock_response.read.return_value = b"%PDF content"
    store._client.get_object.return_value = mock_response
    result = store.download_pdf("abc123.pdf")
    assert result == b"%PDF content"
    store._client.get_object.assert_called_once_with("articles", "abc123.pdf")


def test_upload_chunk(store):
    store.upload_chunk("conv-1", "10_1234_test", "_chunks", "chunk_000.md", "# Hello")
    store._client.put_object.assert_called_once()
    call_args = store._client.put_object.call_args
    assert call_args[0][0] == "parsed-chunks"
    assert call_args[0][1] == "conv-1/10_1234_test/_chunks/chunk_000.md"


def test_upload_chunk_bm25(store):
    store.upload_chunk("conv-1", "10_1234_test", "_bm25_chunks", "chunk_000.txt", "clean text")
    call_args = store._client.put_object.call_args
    assert call_args[0][1] == "conv-1/10_1234_test/_bm25_chunks/chunk_000.txt"


def test_list_chunk_keys(store):
    obj1 = MagicMock()
    obj1.object_name = "conv-1/10_1234_test/_chunks/chunk_000.md"
    obj2 = MagicMock()
    obj2.object_name = "conv-1/10_1234_test/_bm25_chunks/chunk_000.txt"
    store._client.list_objects.return_value = [obj1, obj2]
    keys = store.list_chunk_keys("conv-1", "10_1234_test")
    assert "conv-1/10_1234_test/_chunks/chunk_000.md" in keys
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/pdf-parser && uv run pytest tests/test_minio_store.py -v
```

- [ ] **Step 3: Write `app/minio_store.py`**

```python
import io
import logging
from minio import Minio

log = logging.getLogger(__name__)


class MinioStore:
    def __init__(self, client: Minio, input_bucket: str, output_bucket: str):
        self._client = client
        self._input_bucket = input_bucket
        self._output_bucket = output_bucket

    def ensure_buckets(self) -> None:
        for bucket in (self._input_bucket, self._output_bucket):
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)
                log.info("minio_store: created bucket %s", bucket)

    def download_pdf(self, object_key: str) -> bytes:
        """Download a PDF from the input bucket."""
        response = self._client.get_object(self._input_bucket, object_key)
        data = response.read()
        log.info("minio_store: downloaded %s (%d bytes)", object_key, len(data))
        return data

    def upload_chunk(
        self,
        conversation_id: str,
        doc_key: str,
        chunk_dir: str,   # "_chunks" or "_bm25_chunks"
        filename: str,
        text: str,
        encoding: str = "utf-8",
    ) -> str:
        """Upload a single chunk file. Returns the object key."""
        object_key = f"{conversation_id}/{doc_key}/{chunk_dir}/{filename}"
        data = text.encode(encoding)
        self._client.put_object(
            self._output_bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type="text/plain; charset=utf-8",
        )
        log.info("minio_store: uploaded chunk %s", object_key)
        return object_key

    def list_chunk_keys(self, conversation_id: str, doc_key: str) -> list[str]:
        """List all chunk object keys for a given conversation + doc."""
        prefix = f"{conversation_id}/{doc_key}/"
        objects = self._client.list_objects(self._output_bucket, prefix=prefix, recursive=True)
        return [obj.object_name for obj in objects]


def make_minio_store(
    endpoint: str,
    access_key: str,
    secret_key: str,
    input_bucket: str,
    output_bucket: str,
    secure: bool = False,
) -> MinioStore:
    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
    store = MinioStore(client=client, input_bucket=input_bucket, output_bucket=output_bucket)
    store.ensure_buckets()
    return store
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/pdf-parser && uv run pytest tests/test_minio_store.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/pdf-parser/app/minio_store.py services/pdf-parser/tests/test_minio_store.py
git commit -m "feat(pdf-parser): add MinIO store with conversation-scoped chunk upload"
```

---

## Task 6: Parser Worker

**Files:**
- Create: `services/pdf-parser/app/parser.py`
- Create: `services/pdf-parser/tests/test_parser.py`

The `parser.py` module is adapted from `../pdf-parser/parse_pdfs.py`. Copy the pure utility functions verbatim; replace the file-system output with MinIO uploads using conversation-scoped keys.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_parser.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.parser import detect_language, make_windows, make_bm25_chunk, Window


def test_make_windows_basic():
    windows = make_windows("abcdefghij", window_size=6, overlap=2)
    assert len(windows) == 2
    assert windows[0].text == "abcdef"
    assert windows[1].text == "efghij"


def test_make_windows_single_chunk():
    windows = make_windows("short", window_size=100, overlap=10)
    assert len(windows) == 1
    assert windows[0].text == "short"


def test_make_windows_empty():
    assert make_windows("") == []


def test_detect_language_english():
    text = "Chemistry is the scientific study of matter. " * 20
    assert detect_language(text) == "en"


def test_make_bm25_chunk_no_markdown():
    result = make_bm25_chunk("## Synthesis\n\nNaCl reacts.", lang="en")
    assert "##" not in result
    assert "NaCl" in result


async def test_process_pdf_uploads_conversation_scoped_chunks():
    """Chunk files must be uploaded under {conversation_id}/{doc_key}/."""
    from app.parser import process_pdf_to_minio

    mock_chain = MagicMock()
    mock_chain.ainvoke = AsyncMock(return_value="cleaned text")
    mock_minio = MagicMock()
    mock_minio.upload_chunk = MagicMock(return_value="parsed-chunks/conv-1/10_1234_test/_chunks/chunk_000.md")
    raw_md = "Word " * 2000  # long enough to produce multiple windows

    with patch("app.parser.asyncio.to_thread", new_callable=AsyncMock, return_value=raw_md), \
         patch("app.parser.build_chain", return_value=mock_chain):
        artifacts = await process_pdf_to_minio(
            b"%PDF fake",
            "job-001",
            "conv-1",
            "10_1234_test",
            mock_minio,
            MagicMock(),
        )

    assert mock_chain.ainvoke.call_count >= 1
    # upload_chunk must have been called with the conversation_id and doc_key
    calls = mock_minio.upload_chunk.call_args_list
    assert any(c.args[0] == "conv-1" and c.args[1] == "10_1234_test" for c in calls)
    assert "chunk_000" in artifacts
    assert "bm25_000" in artifacts
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/pdf-parser && uv run pytest tests/test_parser.py -v
```

- [ ] **Step 3: Write `app/parser.py`**

Copy the pure utility functions from `../pdf-parser/parse_pdfs.py` (`Window`, `make_windows`, `detect_language`, `strip_prompt_echo`, `duplicate_headers`, `lemmatize_strip`, `_is_special_token`, `make_bm25_chunk`, `build_chain`, `PROMPTS`, `DEFAULT_LANG`, `WINDOW_SIZE`, `OVERLAP`) verbatim. Then add the async processing function:

```python
# app/parser.py
# --- copy verbatim from parse_pdfs.py: Window, make_windows, detect_language,
#     strip_prompt_echo, duplicate_headers, lemmatize_strip, _is_special_token,
#     make_bm25_chunk, build_chain, PROMPTS, DEFAULT_LANG, WINDOW_SIZE, OVERLAP ---

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.minio_store import MinioStore

log = logging.getLogger(__name__)


async def _clean_window(chain, window, total: int, job_id: str, langfuse_handler) -> str:
    config = {"run_name": f"{job_id}_chunk_{window.i:03d}"}
    if langfuse_handler:
        config["callbacks"] = [langfuse_handler]
    result = await chain.ainvoke(
        {"part_idx": window.i + 1, "part_total": total, "text": window.text},
        config=config,
    )
    return result.strip()


async def process_pdf_to_minio(
    pdf_bytes: bytes,
    job_id: str,
    conversation_id: str,
    doc_key: str,
    minio: "MinioStore",
    llm,
    langfuse_handler=None,
) -> dict[str, str]:
    """Run Docling + LLM cleaning pipeline and store chunk files in MinIO.

    Chunk files are written under:
      parsed-chunks/{conversation_id}/{doc_key}/_chunks/chunk_NNN.md
      parsed-chunks/{conversation_id}/{doc_key}/_bm25_chunks/chunk_NNN.txt

    Returns a dict mapping artifact names to MinIO object keys.
    """
    artifacts: dict[str, str] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        pdf_path = tmp / f"{job_id}.pdf"
        pdf_path.write_bytes(pdf_bytes)

        # Stage 1: Docling (CPU-bound — run in thread to avoid blocking event loop)
        def _docling_convert() -> str:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = False
            converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
            )
            return converter.convert(pdf_path).document.export_to_markdown()

        raw_md = await asyncio.to_thread(_docling_convert)
        log.info("parser: job %s docling completed (%d chars)", job_id, len(raw_md))

        # Stage 2: LLM cleaning — all windows fired concurrently
        lang = detect_language(raw_md)
        windows = make_windows(raw_md)
        total = len(windows)
        chain = build_chain(llm, lang)

        cleaned_parts: list[str] = await asyncio.gather(*[
            _clean_window(chain, w, total, job_id, langfuse_handler)
            for w in windows
        ])
        cleaned_parts = [strip_prompt_echo(c, lang) for c in cleaned_parts]
        bm25_parts = [make_bm25_chunk(c, lang) for c in cleaned_parts]

        # Upload chunk files with conversation-scoped keys
        for i, (cleaned, bm25) in enumerate(zip(cleaned_parts, bm25_parts)):
            filename = f"chunk_{i:03d}"
            key = minio.upload_chunk(conversation_id, doc_key, "_chunks", f"{filename}.md", cleaned)
            artifacts[filename] = key

            bm25_key = minio.upload_chunk(conversation_id, doc_key, "_bm25_chunks", f"{filename}.txt", bm25)
            artifacts[f"bm25_{i:03d}"] = bm25_key

        log.info("parser: job %s completed, %d chunk artifacts", job_id, len(artifacts))
        return artifacts
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/pdf-parser && uv run pytest tests/test_parser.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/pdf-parser/app/parser.py services/pdf-parser/tests/test_parser.py
git commit -m "feat(pdf-parser): add parser worker with conversation-scoped MinIO output"
```

---

## Task 7: FastAPI App & Routes

**Files:**
- Create: `services/pdf-parser/app/main.py`
- Create: `services/pdf-parser/tests/test_api.py`

The `POST /jobs` endpoint accepts the article-fetcher's webhook payload (JSON body), not a file upload. On job completion it fires a webhook to the ai-agent's `POST /rag/ingest`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_submit_job_returns_job_id(client):
    with patch("app.main.job_store") as mock_store, \
         patch("app.main._run_parser", new_callable=AsyncMock):
        mock_store.save = AsyncMock()
        resp = await client.post("/jobs", json={
            "job_id": "fetcher-job-001",
            "doi": "10.1038/s41586-021-03819-2",
            "object_key": "fetcher-job-001.pdf",
            "conversation_id": "conv-abc",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert data["job_id"] == "fetcher-job-001"
        assert data["status"] == "pending"


async def test_get_job_status(client):
    from app.schemas import JobState, JobStatus
    import time
    mock_job = JobState(
        job_id="test-123",
        status=JobStatus.RUNNING,
        doi="10.1234/test",
        doc_key="10_1234_test",
        conversation_id="conv-xyz",
        created_at=time.time(),
        updated_at=time.time(),
    )
    with patch("app.main.job_store") as mock_store:
        mock_store.get = AsyncMock(return_value=mock_job)
        resp = await client.get("/jobs/test-123")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        assert resp.json()["conversation_id"] == "conv-xyz"


async def test_get_job_not_found(client):
    with patch("app.main.job_store") as mock_store:
        mock_store.get = AsyncMock(return_value=None)
        resp = await client.get("/jobs/missing-id")
        assert resp.status_code == 404


async def test_ingest_webhook_fired_on_completion(client):
    """After successful parsing, POST /rag/ingest is called on ai-agent."""
    from app.schemas import JobState, JobStatus
    import time

    mock_job = JobState(
        job_id="j-completed",
        status=JobStatus.COMPLETED,
        doi="10.1234/test",
        doc_key="10_1234_test",
        conversation_id="conv-fire",
        created_at=time.time(),
        updated_at=time.time(),
        artifacts={"chunk_000": "parsed-chunks/conv-fire/10_1234_test/_chunks/chunk_000.md"},
    )

    with patch("app.main.job_store") as mock_store, \
         patch("app.main._notify_ai_agent", new_callable=AsyncMock) as mock_notify:
        mock_store.get = AsyncMock(return_value=mock_job)
        mock_store.update = AsyncMock()
        # Simulate _run_parser calling _notify_ai_agent directly
        await mock_notify("conv-fire", "10_1234_test")
        mock_notify.assert_called_once_with("conv-fire", "10_1234_test")
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/pdf-parser && uv run pytest tests/test_api.py -v
```

- [ ] **Step 3: Write `app/main.py`**

```python
import asyncio
import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from redis.asyncio import Redis

from app.config import settings
from app.minio_store import make_minio_store
from app.parser import process_pdf_to_minio
from app.redis_store import RedisJobStore
from app.schemas import (
    IngestWebhookPayload,
    JobState,
    JobStatus,
    JobStatusResponse,
    JobSubmitResponse,
)

log = logging.getLogger(__name__)

job_store: RedisJobStore = None  # set in lifespan
minio = None                      # set in lifespan


@asynccontextmanager
async def lifespan(app: FastAPI):
    global job_store, minio
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    job_store = RedisJobStore(redis=redis, ttl=settings.REDIS_JOB_TTL)
    minio = make_minio_store(
        endpoint=settings.ARTICLES_MINIO_ENDPOINT,
        access_key=settings.ARTICLES_MINIO_ACCESS_KEY,
        secret_key=settings.ARTICLES_MINIO_SECRET_KEY,
        input_bucket=settings.ARTICLES_MINIO_INPUT_BUCKET,
        output_bucket=settings.ARTICLES_MINIO_OUTPUT_BUCKET,
        secure=settings.ARTICLES_MINIO_SECURE,
    )
    log.info("pdf-parser service starting (env=%s)", settings.ENVIRONMENT)
    yield
    await redis.aclose()
    log.info("pdf-parser service shutting down")


app = FastAPI(title="PDF Parser Service", version="0.1.0", lifespan=lifespan)


def _build_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=0,
    )


def _build_langfuse_handler():
    if not settings.LANGFUSE_PUBLIC_KEY:
        return None
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
        lf = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_BASE_URL,
        )
        return CallbackHandler() if lf.auth_check() else None
    except Exception:
        log.warning("Langfuse unavailable — tracing disabled")
        return None


async def _notify_ai_agent(conversation_id: str, doc_key: str) -> None:
    """POST /rag/ingest to ai-agent. Retries once after 5 s on failure."""
    url = f"{settings.AI_AGENT_INGEST_URL}/rag/ingest"
    payload = {"conversation_id": conversation_id, "doc_key": doc_key}
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                log.info("pdf-parser: notified ai-agent ingest for conv=%s doc=%s", conversation_id, doc_key)
                return
        except Exception:
            if attempt == 0:
                log.warning("pdf-parser: ingest webhook failed, retrying in 5s (conv=%s doc=%s)", conversation_id, doc_key)
                await asyncio.sleep(5)
            else:
                log.exception("pdf-parser: ingest webhook failed after retry (conv=%s doc=%s)", conversation_id, doc_key)


async def _run_parser(job_id: str, object_key: str, conversation_id: str, doc_key: str) -> None:
    await job_store.update(job_id, status=JobStatus.RUNNING)
    try:
        pdf_bytes = minio.download_pdf(object_key)
        llm = _build_llm()
        langfuse_handler = _build_langfuse_handler()
        artifacts = await process_pdf_to_minio(
            pdf_bytes, job_id, conversation_id, doc_key, minio, llm, langfuse_handler,
        )
        await job_store.update(job_id, status=JobStatus.COMPLETED, artifacts=artifacts)
        log.info("job %s completed with %d artifacts", job_id, len(artifacts))
        await _notify_ai_agent(conversation_id, doc_key)
    except Exception as exc:
        log.exception("job %s failed", job_id)
        await job_store.update(job_id, status=JobStatus.FAILED, error=str(exc))


@app.get("/health")
async def health():
    return {"status": "ok", "service": "pdf-parser"}


@app.post("/jobs", response_model=JobSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_job(payload: IngestWebhookPayload, background_tasks: BackgroundTasks) -> JobSubmitResponse:
    """Accept webhook from article-fetcher. PDF is already in articles-minio."""
    job = JobState(
        job_id=payload.job_id,
        status=JobStatus.PENDING,
        doi=payload.doi,
        doc_key=payload.doc_key,
        conversation_id=payload.conversation_id,
        created_at=time.time(),
        updated_at=time.time(),
    )
    await job_store.save(job)
    background_tasks.add_task(
        _run_parser,
        payload.job_id,
        payload.object_key,
        payload.conversation_id,
        payload.doc_key,
    )
    log.info("submitted job %s for DOI %s (conv=%s)", payload.job_id, payload.doi, payload.conversation_id)
    return JobSubmitResponse(job_id=payload.job_id, status=JobStatus.PENDING)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    job = await job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return JobStatusResponse.from_job(job)
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd services/pdf-parser && uv run pytest tests/test_api.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/pdf-parser/app/main.py services/pdf-parser/tests/test_api.py
git commit -m "feat(pdf-parser): add FastAPI app with webhook input and ai-agent ingest notification"
```

---

## Task 8: Compose Integration

**Files:**
- Modify: `compose.yml` — add `pdf-parser` service (reuses `articles-minio` — no new MinIO needed)

- [ ] **Step 1: Add `pdf-parser` service to `compose.yml`**

Add after the `article-fetcher:` block:

```yaml
  pdf-parser:
    build:
      context: .
      dockerfile: services/pdf-parser/Dockerfile
    restart: unless-stopped
    ports:
      - "8300:8300"
    depends_on:
      redis:
        condition: service_healthy
      articles-minio:
        condition: service_healthy
    env_file:
      - .env
    environment:
      - REDIS_URL=redis://redis:6379/1
      - ARTICLES_MINIO_ENDPOINT=articles-minio:9000
      - ARTICLES_MINIO_ACCESS_KEY=${ARTICLES_MINIO_ACCESS_KEY:-minioadmin}
      - ARTICLES_MINIO_SECRET_KEY=${ARTICLES_MINIO_SECRET_KEY:-minioadmin}
      - ARTICLES_MINIO_INPUT_BUCKET=articles
      - ARTICLES_MINIO_OUTPUT_BUCKET=parsed-chunks
      - AI_AGENT_INGEST_URL=http://ai-agent:8000
    develop:
      watch:
        - path: ./services/pdf-parser
          action: sync
          target: /app
          ignore:
            - .venv
        - path: ./services/pdf-parser/pyproject.toml
          action: rebuild
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8300/health"]
      interval: 10s
      timeout: 5s
      retries: 5
```

- [ ] **Step 2: Update `article-fetcher` service in `compose.yml`**

Add `ARTICLE_PROCESSOR_WEBHOOK_URL` to its environment:

```yaml
# under article-fetcher → environment:
- ARTICLE_PROCESSOR_WEBHOOK_URL=http://pdf-parser:8300/jobs
```

- [ ] **Step 3: Update `ai-agent` service in `compose.yml`**

Add MinIO config for pulling parsed chunks:

```yaml
# under ai-agent → environment:
- ARTICLES_MINIO_ENDPOINT=articles-minio:9000
- ARTICLES_MINIO_ACCESS_KEY=${ARTICLES_MINIO_ACCESS_KEY:-minioadmin}
- ARTICLES_MINIO_SECRET_KEY=${ARTICLES_MINIO_SECRET_KEY:-minioadmin}
- ARTICLES_MINIO_PARSED_BUCKET=parsed-chunks
```

- [ ] **Step 4: Add workspace member to root `pyproject.toml`**

In `[tool.uv.workspace]` members list, add `"services/pdf-parser"`.

- [ ] **Step 5: Validate compose file**

```bash
docker compose config --quiet
```
Expected: exits 0

- [ ] **Step 6: Smoke-test locally**

```bash
docker compose build pdf-parser
docker compose up redis articles-minio article-fetcher pdf-parser ai-agent -d
curl http://localhost:8300/health
# Expected: {"status":"ok","service":"pdf-parser"}
```

- [ ] **Step 7: Commit**

```bash
git add compose.yml pyproject.toml
git commit -m "feat(pdf-parser): wire up in Docker Compose, connect to articles-minio and ai-agent"
```

---

## Task 9: Run Full Test Suite

- [ ] **Step 1: Install dev deps and run all service tests**

```bash
cd services/pdf-parser && uv sync --dev && uv run pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Step 2: Commit if any fixes were needed**

```bash
git add -p
git commit -m "fix(pdf-parser): address test failures"
```

---

## Integration Notes

- **Redis DB**: Uses Redis DB `1` (the main app uses DB `0`) to avoid key collisions.
- **Input**: `POST /jobs` accepts JSON from the article-fetcher webhook — no file upload needed.
- **MinIO layout**:
  - Input: `articles/{job_id}.pdf` (written by article-fetcher)
  - Output: `parsed-chunks/{conversation_id}/{doc_key}/_chunks/chunk_NNN.md`
  - Output: `parsed-chunks/{conversation_id}/{doc_key}/_bm25_chunks/chunk_NNN.txt`
- **ai-agent notification**: After successful parsing, `POST /rag/ingest` is called with `{conversation_id, doc_key}`. The ai-agent downloads the chunks and updates the RAG index for that conversation.
- **Port**: `8300` (article-fetcher is on `8200`).
- **Env vars to add to `.env`**: `ARTICLES_MINIO_ACCESS_KEY`, `ARTICLES_MINIO_SECRET_KEY` (already present from article-fetcher setup), `OPENAI_API_KEY` (already present).
- **LLM credentials**: `OPENAI_API_KEY` and optionally `OPENAI_BASE_URL` are read from `.env` and forwarded to the container via `env_file`.
