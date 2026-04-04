# Backend Service

FastAPI REST API with Celery background tasks. Handles auth, conversations, articles, retrosynthesis routing.

## Dev Commands

```bash
# Local dev (no Docker)
uv sync
uv run fastapi dev app/main.py

# Run tests (requires full Docker stack running)
bash ../scripts/test.sh
# Or inside container:
docker compose exec backend bash scripts/tests-start.sh

# Lint / type-check
uv run ruff check --fix app/
uv run ruff format app/
uv run mypy app/

# Database migrations
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head
```

## Project Structure

```
app/
├── main.py           # FastAPI app init, CORS, Sentry
├── models.py         # SQLModel schemas (User, Conversation, Article, TaskJob, ...)
├── crud.py           # DB helpers (typed CRUD per model)
├── core/
│   ├── config.py     # Settings (Pydantic BaseSettings, reads .env)
│   ├── db.py         # SQLModel engine + session dep
│   └── security.py   # JWT, password hashing
├── api/
│   ├── main.py       # Router aggregator — add new routers here
│   └── routes/       # One file per resource (login, users, conversations, ...)
├── worker/
│   ├── celery_app.py # Celery config — 3 queues: default, chat, gpu
│   └── tasks/        # Async task definitions (chat, retrosynthesis, ...)
└── alembic/          # Migration files + env.py
```

## Conventions

- All routes mount at `/api/v1` — defined in `app/api/main.py`
- Use `SessionDep` (from `app/core/db.py`) for DB sessions in routes
- Use `CurrentUser` dependency for auth-required endpoints
- Route files follow pattern: `router = APIRouter(prefix="/resource", tags=["resource"])`
- New Celery tasks go in `app/worker/tasks/`; assign to appropriate queue via `queue=` kwarg

## Common Tasks

**Add a new route:**
1. Create `app/api/routes/myresource.py` with `router = APIRouter(...)`
2. Import and include in `app/api/main.py`

**Add a new model:**
1. Define in `app/models.py` (SQLModel + table=True for DB models)
2. Add CRUD helpers in `app/crud.py`
3. Run `alembic revision --autogenerate`

**Add a Celery task:**
1. Create task in `app/worker/tasks/` decorated with `@celery_app.task`
2. Queue: use `chat` for LLM calls, `gpu` for GPU-intensive work, `default` otherwise

## Gotchas

- `ChatMessage.msg_metadata` — SQLAlchemy reserves `metadata` on `table=True` models; Python attr is `msg_metadata`, DB column is `metadata`. Use `msg_metadata=` when constructing ChatMessage objects.
- `get_sync_redis()` is the sync Redis helper in `app/core/redis.py`. Use for Celery tasks; use `get_async_redis()` in async FastAPI routes.
- Internal endpoint `/internal/*` is mounted directly on the FastAPI `app` (not under `/api/v1`). No auth — Docker-network only.
- Async pipeline tasks (`continuation.py`): `run_s2_search` → `monitor_ingestion` → `run_agent_continuation`. Per-conversation streaming lock: `conv_processing:{id}` (Redis SET NX EX 600) + `conv_pending:{id}` queue.
- `app/api/routes/private.py` routes only load when `ENVIRONMENT=local` — do not put production-required endpoints there
- Migrations run automatically via `scripts/prestart.sh` on container start — don't run them manually in prod
- `ENVIRONMENT=local` skips some security checks (HTTPS-only cookies, etc.)
- Sentry is optional — only initializes if `SENTRY_DSN` is set
- Email uses MJML templates in `app/email-templates/src/`; rebuild with `mjml` CLI if editing
- TaskJob model tracks Celery task status — poll via `/api/v1/tasks/{task_id}`
