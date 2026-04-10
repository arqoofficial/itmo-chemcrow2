# PDF Parser Service

Receives PDFs from article-fetcher via webhook, parses them with Docling, cleans with LLM, chunks, stores in MinIO, then POSTs chunks to AI Agent for RAG ingestion.

## Dev Commands

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8300 --reload
uv run pytest tests/
```

## Data Flow

```
POST /jobs  ← article-fetcher webhook (PDF in MinIO articles bucket)
    ↓
Docling parse (layout-aware PDF → markdown, runs in thread pool)
    ↓
LLM cleaning (LangChain + OpenAI — all windows fired concurrently via asyncio.gather)
    ↓
character-level sliding window chunking (make_windows: 6000-char windows, 800-char overlap)
    ↓
MinIO parsed-chunks bucket  +  POST http://ai-agent:8100/rag/ingest
```

## Key Design Decisions

**`process_pdf_to_minio` returns `dict[str, str]`** — a mapping of artifact names to MinIO object keys (e.g. `{"chunk_000": "parsed-chunks/conv-id/doc/_chunks/chunk_000.md"}`).

**Each LLM window cleaning (`_clean_window`) returns `(text, bool)`** where the bool is `timed_out`. Results are gathered concurrently.

**IMPORTANT:** `process_pdf_to_minio` raises `RuntimeError` after the gather if any LLM windows timed out. This means a partially-cleaned document is never silently stored. Don't swallow this error — it must propagate to mark the job as FAILED and prevent corrupt chunks reaching RAG.

**Jobs are queued in Redis.** `POST /jobs` enqueues; a background worker processes. Use Redis job IDs to track status.

## Project Structure

```
app/
├── main.py        # FastAPI — POST /jobs, GET /jobs/{id}
├── parser.py      # Docling pipeline, LLM cleaning, (text, bool) return contract
├── minio_store.py # MinIO client (articles + parsed-chunks buckets)
├── redis_store.py # Job queue and status tracking
├── config.py      # Settings (MinIO URL, AI Agent URL, LLM keys, Langfuse)
└── schemas.py     # Job request/response models
```

## Gotchas

- Docling can be slow on large PDFs — the Docker container has a generous timeout; don't reduce it
- LLM cleaning uses the polza.ai proxy (OpenAI-compatible) — same config as ai-agent
- AI Agent URL must be the internal Docker hostname `http://ai-agent:8100` — never hardcode localhost
- Langfuse tracing is enabled — requires `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` in env
- `pyproject.toml` is part of the root uv workspace — run `uv sync` from repo root or this directory
