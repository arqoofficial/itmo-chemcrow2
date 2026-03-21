# Langfuse Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add self-hosted Langfuse tracing to ChemCrow2 so every agent chat request produces a full trace with nested LLM and tool spans, with tracing optional via env vars.

**Architecture:** A `langfuse.callback.CallbackHandler` is created per request and injected into `agent.ainvoke()` / `agent.astream_events()` via LangChain's `config={"callbacks": [...]}`. The handler is never passed at graph-build time (the graph is cached). Langfuse server runs as a Docker Compose profile (`langfuse`) alongside a dedicated Postgres instance.

**Tech Stack:** `langfuse` (PyPI), `langfuse.callback.CallbackHandler`, Docker Compose profiles, `pydantic-settings`, `pytest`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `services/ai-agent/pyproject.toml` | Modify | Add `langfuse` dependency |
| `services/ai-agent/app/config.py` | Modify | Add `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST` settings |
| `services/ai-agent/app/tracing.py` | Create | `get_langfuse_handler()` — returns handler or None |
| `services/ai-agent/app/main.py` | Modify | Startup log; inject handler into both endpoints; flush on sync |
| `services/ai-agent/tests/test_tracing.py` | Create | Unit tests for `get_langfuse_handler()` |
| `compose.yml` | Modify | Add `langfuse-db` and `langfuse-server` under `langfuse` profile; add named volume |
| `.env.example` | Modify | Add Langfuse vars with comments |

---

### Task 1: Add `langfuse` dependency

**Files:**
- Modify: `services/ai-agent/pyproject.toml`

- [ ] **Step 1: Add the dependency**

In `services/ai-agent/pyproject.toml`, add `langfuse` to the `dependencies` list:

```toml
dependencies = [
    # ... existing deps ...
    "langfuse>=2.0.0",
]
```

- [ ] **Step 2: Install it**

```bash
cd services/ai-agent
uv add langfuse
```

Expected: `uv.lock` updated, no errors.

- [ ] **Step 3: Verify import works**

```bash
cd services/ai-agent
uv run python -c "from langfuse.callback import CallbackHandler; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add services/ai-agent/pyproject.toml services/ai-agent/uv.lock
git commit -m "feat: add langfuse dependency"
```

---

### Task 2: Add Langfuse settings to config

**Files:**
- Modify: `services/ai-agent/app/config.py`

- [ ] **Step 1: Add the three new fields to the `Settings` class**

Open `services/ai-agent/app/config.py`. After the existing `ANTHROPIC_BASE_URL` line, add:

```python
    # Langfuse tracing (optional)
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_HOST: str = "http://langfuse-server:3000"
```

The full updated `Settings` class should look like:

```python
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

    # Langfuse tracing (optional)
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_HOST: str = "http://langfuse-server:3000"
```

- [ ] **Step 2: Verify settings load**

```bash
cd services/ai-agent
uv run python -c "from app.config import settings; print(settings.LANGFUSE_HOST)"
```

Expected: `http://langfuse-server:3000`

- [ ] **Step 3: Commit**

```bash
git add services/ai-agent/app/config.py
git commit -m "feat: add Langfuse settings to config"
```

---

### Task 3: Create `tracing.py` and its tests

**Files:**
- Create: `services/ai-agent/app/tracing.py`
- Create: `services/ai-agent/tests/test_tracing.py`

- [ ] **Step 1: Write the failing tests first**

Create `services/ai-agent/tests/test_tracing.py`:

```python
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_get_langfuse_handler_returns_none_when_unconfigured(monkeypatch):
    """Returns None when any Langfuse env var is missing."""
    monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "")
    monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setattr("app.config.settings.LANGFUSE_HOST", "http://localhost:3000")

    from app.tracing import get_langfuse_handler
    assert get_langfuse_handler() is None


def test_get_langfuse_handler_returns_none_when_public_key_missing(monkeypatch):
    monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr("app.config.settings.LANGFUSE_HOST", "http://localhost:3000")

    from app.tracing import get_langfuse_handler
    assert get_langfuse_handler() is None


def test_get_langfuse_handler_returns_handler_when_configured(monkeypatch):
    """Returns a CallbackHandler when all three vars are set."""
    monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setattr("app.config.settings.LANGFUSE_HOST", "http://localhost:3000")

    from langfuse.callback import CallbackHandler

    with patch("langfuse.callback.CallbackHandler.__init__", return_value=None):
        from app.tracing import get_langfuse_handler
        handler = get_langfuse_handler()
        assert isinstance(handler, CallbackHandler)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/ai-agent
uv run pytest tests/test_tracing.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.tracing'`

- [ ] **Step 3: Create `app/tracing.py`**

```python
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def get_langfuse_handler():
    """Return a Langfuse CallbackHandler if configured, else None.

    Tracing is optional. Returns None (disabling tracing) if any of
    LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, or LANGFUSE_HOST is unset.
    """
    if not (settings.LANGFUSE_SECRET_KEY and settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_HOST):
        return None

    from langfuse.callback import CallbackHandler

    return CallbackHandler(
        secret_key=settings.LANGFUSE_SECRET_KEY,
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        host=settings.LANGFUSE_HOST,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/ai-agent
uv run pytest tests/test_tracing.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/ai-agent/app/tracing.py services/ai-agent/tests/test_tracing.py
git commit -m "feat: add get_langfuse_handler helper with tests"
```

---

### Task 4: Inject handler in `main.py`

**Files:**
- Modify: `services/ai-agent/app/main.py`

- [ ] **Step 1: Add startup log in `lifespan`**

At the top of `main.py`, add the import:

```python
from app.tracing import get_langfuse_handler
```

Update the `lifespan` function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AI Agent service starting (env=%s)", settings.ENVIRONMENT)
    if settings.LANGFUSE_SECRET_KEY and settings.LANGFUSE_PUBLIC_KEY:
        logger.info("Langfuse tracing enabled — host=%s", settings.LANGFUSE_HOST)
    else:
        logger.warning(
            "Langfuse tracing is disabled — set LANGFUSE_SECRET_KEY, "
            "LANGFUSE_PUBLIC_KEY, and LANGFUSE_HOST to enable."
        )
    yield
    logger.info("AI Agent service shutting down")
```

- [ ] **Step 2: Update sync `/api/v1/chat` endpoint**

Replace the existing `chat` function body so the agent invocation becomes:

```python
@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    agent = get_agent(request.provider)
    langchain_messages = convert_messages([m.model_dump() for m in request.messages])

    handler = get_langfuse_handler()
    config = {"callbacks": [handler]} if handler else {}
    result = await agent.ainvoke({"messages": langchain_messages}, config=config)

    if handler:
        handler.flush()

    final_messages = result["messages"]
    last_ai = None
    for msg in reversed(final_messages):
        if isinstance(msg, AIMessage):
            last_ai = msg
            break

    if not last_ai:
        return ChatResponse(content="I could not generate a response.")

    tool_calls = None
    if last_ai.tool_calls:
        tool_calls = [
            {"name": tc["name"], "args": tc["args"]}
            for tc in last_ai.tool_calls
        ]

    return ChatResponse(
        content=last_ai.content or "",
        tool_calls=tool_calls,
    )
```

- [ ] **Step 3: Update streaming `/api/v1/chat/stream` endpoint**

Replace the `astream_events` call to pass the handler config:

```python
@app.post("/api/v1/chat/stream")
async def chat_stream(request: ChatRequest) -> EventSourceResponse:
    agent = get_agent(request.provider)
    langchain_messages = convert_messages([m.model_dump() for m in request.messages])
    handler = get_langfuse_handler()
    stream_config = {"callbacks": [handler]} if handler else {}

    async def event_generator():
        try:
            full_content: list[str] = []

            async for event in agent.astream_events(
                {"messages": langchain_messages},
                config=stream_config,
                version="v2",
            ):
                kind = event.get("event", "")

                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        full_content.append(chunk.content)
                        yield {
                            "event": "token",
                            "data": json.dumps({"content": chunk.content}),
                        }

                elif kind == "on_tool_start":
                    yield {
                        "event": "tool_start",
                        "data": json.dumps({
                            "tool": event.get("name", ""),
                            "input": event.get("data", {}).get("input", {}),
                        }),
                    }

                elif kind == "on_tool_end":
                    yield {
                        "event": "tool_end",
                        "data": json.dumps({
                            "tool": event.get("name", ""),
                            "output": str(event.get("data", {}).get("output", "")),
                        }),
                    }

            assembled = "".join(full_content)
            hazards = find_hazards(assembled)
            if hazards:
                yield {
                    "event": "hazards",
                    "data": json.dumps({"chemicals": hazards}),
                }

            yield {"event": "done", "data": json.dumps({"status": "completed"})}

        except Exception as exc:
            logger.exception("Streaming error")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc)}),
            }

    return EventSourceResponse(
        event_generator(),
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )
```

- [ ] **Step 4: Run full test suite**

```bash
cd services/ai-agent
uv run pytest tests/ -v
```

Expected: all existing tests pass (no regressions).

- [ ] **Step 5: Commit**

```bash
git add services/ai-agent/app/main.py
git commit -m "feat: inject Langfuse callback handler into agent endpoints"
```

---

### Task 5: Add Langfuse services to `compose.yml`

**Files:**
- Modify: `compose.yml`

- [ ] **Step 1: Add `langfuse-db` service**

Inside the `services:` block in `compose.yml`, add after the existing `db` service:

```yaml
  langfuse-db:
    image: postgres:17
    restart: unless-stopped
    profiles: ["langfuse"]
    environment:
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: ${LANGFUSE_POSTGRES_PASSWORD:-changeme}
      POSTGRES_DB: langfuse
    volumes:
      - langfuse-db-data:/var/lib/postgresql/data/pgdata
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse -d langfuse"]
      interval: 5s
      retries: 5
      start_period: 10s
      timeout: 5s
```

- [ ] **Step 2: Add `langfuse-server` service**

Still inside `services:`, add after `langfuse-db`:

```yaml
  langfuse-server:
    image: langfuse/langfuse:latest
    restart: unless-stopped
    profiles: ["langfuse"]
    depends_on:
      langfuse-db:
        condition: service_healthy
    ports:
      - "3000:3000"
    environment:
      DATABASE_URL: postgresql://langfuse:${LANGFUSE_POSTGRES_PASSWORD:-changeme}@langfuse-db:5432/langfuse
      NEXTAUTH_SECRET: ${NEXTAUTH_SECRET:-change-me-to-a-random-32-char-secret}
      NEXTAUTH_URL: ${NEXTAUTH_URL:-http://localhost:3000}
      LANGFUSE_SECRET_KEY: ${LANGFUSE_SECRET_KEY}
      LANGFUSE_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/public/health"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
```

- [ ] **Step 3: Add named volume**

In the top-level `volumes:` block at the bottom of `compose.yml`, add:

```yaml
volumes:
  app-db-data:
  redis-data:
  langfuse-db-data:
```

- [ ] **Step 4: Validate compose file syntax**

```bash
docker compose config --quiet
```

Expected: no errors printed.

- [ ] **Step 5: Commit**

```bash
git add compose.yml
git commit -m "feat: add self-hosted Langfuse services to compose (profile: langfuse)"
```

---

### Task 6: Update `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add Langfuse section**

At the end of `.env.example`, append:

```bash
# -- Langfuse трассировка (опционально) --
# Запуск с профилем: docker compose --profile langfuse up
# Сгенерируй ключи в UI Langfuse после первого запуска (Settings → API Keys)
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_HOST=http://langfuse-server:3000

# Внутренние настройки Langfuse сервера (нужны только при --profile langfuse)
# Сгенерируй: python3 -c "import secrets; print(secrets.token_hex(32))"
NEXTAUTH_SECRET=change-me-to-a-random-32-char-secret
NEXTAUTH_URL=http://localhost:3000
LANGFUSE_POSTGRES_PASSWORD=changeme
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add Langfuse env vars to .env.example"
```

---

### Task 7: Smoke test end-to-end

- [ ] **Step 1: Run the full ai-agent test suite one final time**

```bash
cd services/ai-agent
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 2: Verify compose config is valid**

```bash
docker compose config --quiet
docker compose --profile langfuse config --quiet
```

Expected: no errors.

- [ ] **Step 3: Verify Langfuse server starts (optional, requires Docker)**

```bash
# Copy env and set dummy Langfuse keys for smoke test
docker compose --profile langfuse up langfuse-db langfuse-server --wait
```

Expected: both containers reach healthy state. Langfuse UI accessible at http://localhost:3000.

- [ ] **Step 4: Final commit if any fixups needed, then confirm done**

```bash
git log --oneline -6
```

Expected to see commits for all 6 tasks above.
