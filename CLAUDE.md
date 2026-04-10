# ChemCrow2 — Monorepo Overview

AI-powered chemistry research assistant: molecule editing, literature RAG, retrosynthesis planning, hazard checking.

## Architecture

```
User → Frontend (React/Vite) → Backend (FastAPI + Celery) → AI Agent (LangGraph)
                                         ↓                        ↓
                               Retrosynthesis (8052)     Tools: RDKit, RAG, Safety
                               Article-Fetcher (8200)         ↓
                               PDF-Parser (8300)        MinIO (articles, parsed-chunks)
```

All services communicate over Docker internal network by service name (e.g. `http://ai-agent:8100`).

## Service Map

| Service | Port | Stack | Role |
|---|---|---|---|
| `backend` | 8000 | FastAPI + Celery + PostgreSQL | Auth, API, async tasks |
| `frontend` | 5173/80 | React 19 + Vite + Bun | SPA |
| `ai-agent` | 8100 | FastAPI + LangGraph | LLM orchestration, RAG |
| `retrosynthesis` | 8052 | FastAPI + AiZynthFinder | Retro pathway planning |
| `article-fetcher` | 8200 | FastAPI + scidownl | Sci-Hub download queue |
| `pdf-parser` | 8300 | FastAPI + Docling | PDF parse → RAG ingest |
| `db` | 5432 | PostgreSQL 17 | Main relational store |
| `redis` | 6379 | Redis 7 | Cache + Celery broker |
| `articles-minio` | 9092 | MinIO | Article/chunk object store |
| `langfuse-server` | 3000 | Langfuse | LLM tracing UI |

## Dev Commands

```bash
# Full stack
docker compose up --build -d

# Single service rebuild
docker compose up --build -d <service-name>

# View logs
docker compose logs -f <service-name>

# Backend tests (requires running stack)
bash scripts/test.sh

# Generate frontend OpenAPI client (requires running backend)
bash scripts/generate-client.sh
```

## Package Management

- **Python services:** `uv` — never use pip directly
- **Frontend:** `bun` — never use npm or yarn
- Root `pyproject.toml` is a uv workspace (`members = ["backend", "services/ai-agent", "services/pdf-parser"]`)

## Key Gotchas

- `compose.yml` is dev; `compose.production.yml` is prod — they differ in worker count, ports, and Adminer
- Backend API prefix is `/api/v1` — all routes mount under this
- Celery has 3 queues: `default`, `chat`, `gpu` — chat tasks go to `chat` queue; `gpu` queue is defined in code but **no worker consumes it** in either compose file — don't route tasks there without adding a gpu worker
- AI Agent streams via SSE — don't use standard JSON response in `/chat` endpoint
- `reaction-predict` service is optional and requires `--profile reaction` flag
- Retrosynthesis needs external data volume at `data/aizynthfinder/` — see `docs/data-aizynthfinder.md`
- `.env` is not committed — copy from `.env.example` and fill secrets

## Async Tool Pipeline

`literature_search` returns "queued" immediately; S2 search and article ingestion run via Celery background tasks.

Task chain: `run_s2_search` → `monitor_ingestion` (polls every 10s, max 20 min) → `run_agent_continuation` (all in `chat` queue, `backend/app/worker/tasks/continuation.py`)

- `/internal/*` router is mounted directly on the FastAPI `app` object (not under `/api/v1`) — no auth, Docker-internal only
- `role="background"` messages are saved to DB and rendered as info/error cards in the frontend
- `background_error` SSE is **transient** (NOT saved to DB) — frontend stores it in state and renders an error card
- `background_update` SSE tells the frontend to re-enable SSE before the continuation stream arrives
- Per-conversation Redis lock: `conv_processing:{id}` (atomic `SET NX EX 600`) + `conv_pending:{id}` list for queued continuations; both `process_chat_message` and `run_agent_continuation` acquire this lock