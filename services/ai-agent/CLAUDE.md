# AI Agent Service

LangGraph-based LLM orchestration service. Handles chat (SSE streaming), tool execution, RAG, and safety checks.

## Dev Commands

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload

uv run pytest tests/
uv run ruff check --fix app/
uv run mypy app/
```

## Project Structure

```
app/
├── main.py           # FastAPI app — /health, /api/v1/chat, /api/v1/chat/stream (SSE), /rag/ingest
├── agent.py          # LangGraph graph definition and execution logic
├── config.py         # Settings (LLM keys, URLs, RAG config)
├── schemas.py        # ChatRequest, ChatResponse Pydantic models
├── guard.py          # LLM Guard input/output safety scanners
├── hazard_checker.py # Chemical hazard detection
├── tracing.py        # Langfuse integration (wraps LangChain callbacks)
├── llm_providers/    # Provider-specific LLM configs (OpenAI, Anthropic)
└── tools/
    ├── rag.py            # RAG: embed, index, retrieve from MinIO
    ├── search.py         # Literature search
    ├── admet.py          # ADMET property prediction
    ├── nmr.py            # NMR spectra prediction
    ├── rdkit_tools.py    # RDKit chemistry utilities
    ├── reactions.py      # Reaction tools
    ├── safety.py         # Chemical safety checks
    ├── protocol_review.py
    ├── molecule_draw_rdkit.py
    └── chemspace.py      # ChemSpace database lookups
```

## Chat Endpoints

- `POST /api/v1/chat` — synchronous JSON response
- `POST /api/v1/chat/stream` — SSE streaming via `EventSourceResponse`; never return a plain `JSONResponse` from the stream endpoint

Request includes `conversation_id` — this is passed through the entire RAG pipeline for scope isolation. Don't drop it.

## Adding a Tool

1. Create `app/tools/mytool.py` — tool must be a `@tool`-decorated LangChain function
2. Register in `app/agent.py` tool list
3. Add tests in `tests/tools/test_mytool.py`

## RAG Pipeline

- Embeddings: Sentence Transformers (model downloaded at Docker build time — `app/models/`)
- Storage: MinIO bucket `parsed-chunks`
- Index is in-memory; rebuilt on `/rag/ingest`
- `conversation_id` scopes retrieval — each conversation only sees its own ingested docs
- Scoping is implemented via a `contextvars.ContextVar` (`_CURRENT_CONV_ID`) — don't replace with a global dict or module-level variable; it would break under concurrent requests

## LLM Provider

- Configured via `config.py` — reads `LLM_PROVIDER`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- Currently using polza.ai proxy (OpenAI-compatible): model `qwen/qwen3.5-9b`
- IMPORTANT: disable reasoning with `reasoning={"effort": "none"}` on `ChatOpenAI`
- Set `request_timeout=120` — do not lower this

## Langfuse Tracing

- All LLM calls traced via Langfuse callbacks in `app/tracing.py`
- Langfuse base URL must be the Docker internal hostname — never `localhost`
- Project: `pdf-parser`, credentials: see memory

## Safety & Guardrails

- Input scanned before agent runs (`app/guard.py`)
- Chemical hazard checked in `app/hazard_checker.py` — runs as a tool
- LLM Guard scanners are configured at startup — don't reinitialize per-request

## Async Pipeline

`literature_search` POSTs to `backend /internal/queue-background-tool` and returns "queued" immediately. The conversation_id comes from `_CURRENT_CONV_ID` ContextVar in `app/tools/rag.py`.

`POST /internal/s2-search` — blocking S2 search endpoint called by backend Celery task. No auth. Returns `{"papers": [...]}`.

`role="background"` in `convert_messages` (in `agent.py`) → `HumanMessage("[Background Update]\n{content}")`.

`BACKEND_INTERNAL_URL = "http://backend:8000"` in `config.py`.

## Gotchas

- PyTorch is CPU-only in the Docker image — don't add GPU-requiring dependencies without updating the Dockerfile
- Sentence Transformers model is pre-downloaded at build time; adding a new model requires Dockerfile change
- `uv.lock` is committed — run `uv lock` after changing `pyproject.toml`
- `import httpx` must be at module level in `app/tools/search.py` for `vi.mock("app.tools.search.httpx.post")` to work in tests
