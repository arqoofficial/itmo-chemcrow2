# Async Tool Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use **superpowers:subagent-driven-development** to implement this plan. Dispatch a fresh subagent per task. Do NOT execute inline. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **CLAUDE.md rule:** After every task that creates or modifies a file listed in the File Map, update the relevant `CLAUDE.md` (root, `backend/CLAUDE.md`, or `services/ai-agent/CLAUDE.md`) to reflect what was added. Do this as part of that task's commit — not as a separate cleanup step at the end. Task 14 is a final review pass only.

**Goal:** Make `literature_search` return immediately ("queued") while S2 search runs in background, triggering follow-up agent responses when results and parsed articles are ready.

**Architecture:** `literature_search` POSTs to backend `/internal/queue-background-tool` → Celery `run_s2_search` calls ai-agent blocking endpoint → saves `role="background"` DB message → dispatches `run_agent_continuation` for abstract analysis + `monitor_ingestion` which polls until parsing completes then dispatches another `run_agent_continuation` for RAG analysis. A per-conversation Redis lock (`conv_processing`) prevents concurrent streaming.

**Tech Stack:** Python/FastAPI (ai-agent + backend), Celery + Redis, SQLModel + Alembic, React/TypeScript (frontend), TanStack Query, shadcn/ui.

**Spec:** `docs/superpowers/specs/2026-04-02-async-tool-pipeline-design.md`

---

## File Map

### New files
- `backend/app/api/routes/internal.py` — `POST /internal/queue-background-tool` (no auth)
- `backend/app/worker/tasks/continuation.py` — `run_s2_search`, `monitor_ingestion`, `run_agent_continuation` Celery tasks
- `backend/app/worker/prompts.py` — `S2_RESULTS`, `PAPERS_INGESTED` string templates
- `frontend/src/components/Chat/BackgroundMessageCard.tsx` — info/error card for background messages
- `frontend/vitest.config.ts` — Vitest + jsdom configuration
- `frontend/src/test/setup.ts` — `@testing-library/jest-dom` global matchers
- `frontend/src/components/Chat/__tests__/BackgroundMessageCard.test.tsx`
- `frontend/src/components/Chat/__tests__/MessageBubble.test.tsx`
- `frontend/src/components/Chat/__tests__/ArticleDownloadsCard.test.tsx`
- `frontend/src/components/Chat/__tests__/ToolCallCard.test.tsx`
- `frontend/src/hooks/__tests__/useConversationSSE.test.ts`

### Modified files
- `backend/app/models.py` — add `metadata` JSON column to `ChatMessage` + `ChatMessagePublic`
- `backend/app/alembic/versions/<new>.py` — migration for `metadata` column
- `backend/app/main.py` — mount `/internal` router directly on `app`
- `backend/app/api/routes/articles.py` — add `retry-s2-search` + `trigger-rag-continuation` endpoints
- `backend/app/worker/celery_app.py` — register `app.worker.tasks.continuation`
- `backend/app/worker/tasks/chat.py` — add `conv_processing` lock + remove dead DOI-extraction branch
- `services/ai-agent/app/main.py` — add `POST /internal/s2-search` endpoint
- `services/ai-agent/app/tools/search.py` — make `literature_search` async (POST to backend)
- `services/ai-agent/app/agent.py` — handle `role="background"` in `convert_messages`
- `frontend/src/client/chatTypes.ts` — add `metadata` to `ChatMessagePublic`, add SSE event types
- `frontend/src/components/Chat/MessageBubble.tsx` — detect `role === "background"`, render card
- `frontend/src/components/Chat/ChatWindow.tsx` — handle `background_update` → re-enable SSE
- `frontend/src/components/Chat/ArticleDownloadsCard.tsx` — "Notify Agent" button
- `frontend/src/hooks/useConversationSSE.ts` — handle `background_update` + `background_error` events

---

## Task 1: DB model — add `metadata` JSON column to `ChatMessage`

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/app/alembic/versions/<hash>_add_metadata_to_chatmessage.py`

- [ ] **Step 1: Write a test confirming the column is missing today**

```python
# backend/tests/test_chatmessage_metadata.py
from app.models import ChatMessage
import uuid

def test_chatmessage_has_metadata_column():
    """ChatMessage must accept metadata kwarg (JSON nullable)."""
    msg = ChatMessage(
        conversation_id=uuid.uuid4(),
        role="background",
        content="test",
        metadata={"variant": "info"},
    )
    assert msg.metadata == {"variant": "info"}
```

Run: `cd backend && uv run pytest tests/test_chatmessage_metadata.py -v`
Expected: FAIL with `TypeError: unexpected keyword argument 'metadata'`

- [ ] **Step 2: Add `metadata` to `ChatMessage` and `ChatMessagePublic` in `backend/app/models.py`**

Add import at top (if not already present):
```python
from sqlalchemy import JSON
```

In the `ChatMessage` table model (after `tool_calls` field):
```python
    metadata: dict | None = Field(default=None, sa_type=JSON())  # type: ignore
```

In `ChatMessagePublic`:
```python
    metadata: dict | None = None
```

- [ ] **Step 3: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_chatmessage_metadata.py -v`
Expected: PASS

- [ ] **Step 4: Generate and apply the Alembic migration**

```bash
cd backend
uv run alembic revision --autogenerate -m "add_metadata_to_chatmessage"
# note the generated filename
uv run alembic upgrade head
```

Expected: migration file created at `app/alembic/versions/<hash>_add_metadata_to_chatmessage.py`. Verify it contains `op.add_column('chatmessage', sa.Column('metadata', sa.JSON(), nullable=True))`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/alembic/versions/ backend/tests/test_chatmessage_metadata.py
git commit -m "feat: add nullable metadata JSON column to ChatMessage"
```

---

## Task 2: ai-agent — `/internal/s2-search` endpoint (blocking S2 search)

**Files:**
- Modify: `services/ai-agent/app/main.py`
- Test: `services/ai-agent/tests/test_s2_search_endpoint.py`

The existing `literature_search` tool has the S2 blocking logic (lines 82–147 in `search.py`). Extract it into the new endpoint so the backend Celery task can call it directly.

- [ ] **Step 1: Write the failing test**

```python
# services/ai-agent/tests/test_s2_search_endpoint.py
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _make_s2_paper(title="Test Paper", doi="10.1234/test"):
    return {
        "title": title,
        "authors": [{"name": "Alice"}, {"name": "Bob"}],
        "abstract": "A test abstract.",
        "year": 2024,
        "citationCount": 10,
        "url": "https://semanticscholar.org/paper/abc",
        "externalIds": {"DOI": doi},
    }


def test_s2_search_returns_papers():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [_make_s2_paper()]}

    with patch("app.main.requests.get", return_value=mock_resp):
        resp = client.post("/internal/s2-search", json={"query": "aspirin synthesis", "max_results": 3})

    assert resp.status_code == 200
    body = resp.json()
    assert "papers" in body
    assert len(body["papers"]) == 1
    assert body["papers"][0]["title"] == "Test Paper"
    assert body["papers"][0]["doi"] == "10.1234/test"


def test_s2_search_empty_returns_empty_list():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}

    with patch("app.main.requests.get", return_value=mock_resp):
        resp = client.post("/internal/s2-search", json={"query": "nonexistent", "max_results": 5})

    assert resp.status_code == 200
    assert resp.json()["papers"] == []
```

Run: `cd services/ai-agent && uv run pytest tests/test_s2_search_endpoint.py -v`
Expected: FAIL (endpoint doesn't exist)

- [ ] **Step 2: Add the endpoint to `services/ai-agent/app/main.py`**

Add imports at the top of the file (after existing ones):
```python
import requests as _requests_lib
from app.tools.utils import _scrape_doi_from_url
```

Add the Pydantic model and endpoint near the end of the file (before the `rag_ingest` endpoint):
```python
_S2_API_BASE = "https://api.semanticscholar.org/graph/v1"


class S2SearchRequest(BaseModel):
    query: str
    max_results: int = 5


@app.post("/internal/s2-search")
def s2_search(payload: S2SearchRequest) -> dict:
    """Blocking S2 search called by backend Celery worker. No auth — Docker-internal only."""
    headers: dict[str, str] = {}
    if settings.SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = settings.SEMANTIC_SCHOLAR_API_KEY

    params = {
        "query": payload.query,
        "limit": min(payload.max_results, 10),
        "fields": "title,authors,abstract,year,citationCount,url,externalIds",
    }

    if settings.SEMANTIC_SCHOLAR_API_KEY:
        retry_waits = [1, 2, 3, 4, 5]
    else:
        retry_waits = [5, 10, 20, 30, 60]

    import time
    for attempt, wait in enumerate(retry_waits):
        r = _requests_lib.get(f"{_S2_API_BASE}/paper/search", params=params, headers=headers, timeout=15)
        if r.status_code != 429:
            break
        logger.warning("S2 429, retrying in %ds (attempt %d/%d)", wait, attempt + 1, len(retry_waits))
        time.sleep(wait)

    r.raise_for_status()
    raw_papers = r.json().get("data", [])

    papers = []
    for p in raw_papers:
        authors_list = p.get("authors") or []
        author_names = [a["name"] for a in authors_list[:3]]
        if len(authors_list) > 3:
            author_names.append("et al.")
        authors_str = ", ".join(author_names)

        ext_ids = p.get("externalIds") or {}
        doi = ext_ids.get("DOI")
        if not doi:
            paper_url = p.get("url")
            if paper_url and "semanticscholar.org" not in paper_url:
                doi = _scrape_doi_from_url(paper_url)

        abstract = p.get("abstract") or ""

        papers.append({
            "title": p.get("title", "Untitled"),
            "authors": authors_str,
            "year": p.get("year"),
            "doi": doi,
            "abstract": abstract,
            "citation_count": p.get("citationCount", 0),
            "url": p.get("url"),
        })

    return {"papers": papers, "query": payload.query}
```

- [ ] **Step 3: Run test to verify it passes**

Run: `cd services/ai-agent && uv run pytest tests/test_s2_search_endpoint.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add services/ai-agent/app/main.py services/ai-agent/tests/test_s2_search_endpoint.py
git commit -m "feat(ai-agent): add /internal/s2-search blocking endpoint"
```

---

## Task 3: ai-agent — async `literature_search` + `convert_messages` background role

**Files:**
- Modify: `services/ai-agent/app/config.py`
- Modify: `services/ai-agent/app/tools/search.py`
- Modify: `services/ai-agent/app/agent.py`
- Test: `services/ai-agent/tests/test_search.py` (existing — add new test)
- Test: `services/ai-agent/tests/test_agent.py` (existing — add new test)

- [ ] **Step 1: Write failing tests**

In `services/ai-agent/tests/test_search.py`, add:
```python
def test_literature_search_queues_and_returns_immediately():
    """literature_search should POST to backend and return 'queued' message without blocking."""
    with patch("app.tools.search.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=202)
        # Set conversation context
        from app.tools.rag import _CURRENT_CONV_ID
        _CURRENT_CONV_ID.set("test-conv-123")

        result = literature_search.invoke({"query": "aspirin synthesis", "max_results": 3})

    assert "queued" in result.lower()
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
    assert payload["type"] == "s2_search"
    assert payload["conversation_id"] == "test-conv-123"
    assert payload["query"] == "aspirin synthesis"
    assert payload["max_results"] == 3
```

In `services/ai-agent/tests/test_agent.py`, add:
```python
def test_convert_messages_background_role():
    """role='background' must become HumanMessage with [Background Update] prefix."""
    from app.agent import convert_messages
    from langchain_core.messages import HumanMessage

    msgs = [{"role": "background", "content": "Some background info"}]
    result = convert_messages(msgs)
    assert len(result) == 1
    assert isinstance(result[0], HumanMessage)
    assert result[0].content.startswith("[Background Update]")
    assert "Some background info" in result[0].content
```

Run: `cd services/ai-agent && uv run pytest tests/test_search.py tests/test_agent.py -v -k "queued or background_role"`
Expected: FAIL

- [ ] **Step 2: Add `BACKEND_INTERNAL_URL` to `services/ai-agent/app/config.py`**

Open `services/ai-agent/app/config.py` and add to the `Settings` class:
```python
BACKEND_INTERNAL_URL: str = "http://backend:8000"
```

This is the Docker-internal URL for reaching the backend from within the ai-agent container. Do not use `localhost` here — it won't resolve inside Docker.

- [ ] **Step 3: Update `literature_search` in `services/ai-agent/app/tools/search.py`**

Replace the entire `literature_search` function body with:
```python
@tool
def literature_search(query: str, max_results: int = 5) -> str:
    """Search scientific literature for chemistry-related papers.

    Results are delivered asynchronously — you will receive them as a background
    update in this conversation shortly after calling this tool.

    Args:
        query: Search query describing the topic of interest.
        max_results: Maximum number of results to return (default 5).
    """
    import httpx
    from app.config import settings
    from app.tools.rag import _CURRENT_CONV_ID

    conversation_id = _CURRENT_CONV_ID.get(None)
    if not conversation_id:
        return "Literature search unavailable: no conversation context."

    try:
        httpx.post(
            f"{settings.BACKEND_INTERNAL_URL}/internal/queue-background-tool",
            json={
                "type": "s2_search",
                "conversation_id": conversation_id,
                "query": query,
                "max_results": max_results,
            },
            timeout=5,
        )
        return "Literature search queued. Results will appear in this conversation shortly."
    except Exception:
        logger.exception("Failed to queue literature search")
        return "Literature search unavailable: could not reach the queue endpoint."
```

- [ ] **Step 4: Update `convert_messages` in `services/ai-agent/app/agent.py`**

In `convert_messages`, add the `background` role handler before the `else` fallback:
```python
        elif role == "background":
            result.append(HumanMessage(content=f"[Background Update]\n{content}"))
        else:
            result.append(HumanMessage(content=content))
```

(Remove the existing bare `else` line and replace with these two lines.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/ai-agent && uv run pytest tests/test_search.py tests/test_agent.py -v -k "queued or background_role"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/ai-agent/app/config.py services/ai-agent/app/tools/search.py services/ai-agent/app/agent.py services/ai-agent/tests/test_search.py services/ai-agent/tests/test_agent.py
git commit -m "feat(ai-agent): make literature_search async, handle background role in convert_messages"
```

---

## Task 4: Backend — prompt templates + `/internal` router

**Files:**
- Create: `backend/app/worker/prompts.py`
- Create: `backend/app/api/routes/internal.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write failing test for the internal endpoint**

```python
# backend/tests/api/test_internal.py
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app

client = TestClient(app)


def test_queue_background_tool_returns_202():
    with patch("app.api.routes.internal.run_s2_search") as mock_task:
        mock_task.delay.return_value = None
        resp = client.post("/internal/queue-background-tool", json={
            "type": "s2_search",
            "conversation_id": "00000000-0000-0000-0000-000000000001",
            "query": "aspirin synthesis",
            "max_results": 5,
        })
    assert resp.status_code == 202


def test_queue_background_tool_saves_query_to_redis():
    with patch("app.api.routes.internal.run_s2_search") as mock_task, \
         patch("app.api.routes.internal.get_sync_redis") as mock_redis:
        mock_task.delay.return_value = None
        mock_redis.return_value.set = lambda *a, **kw: None
        resp = client.post("/internal/queue-background-tool", json={
            "type": "s2_search",
            "conversation_id": "00000000-0000-0000-0000-000000000001",
            "query": "aspirin synthesis",
            "max_results": 5,
        })
    assert resp.status_code == 202
```

Run: `cd backend && uv run pytest tests/api/test_internal.py -v`
Expected: FAIL (route doesn't exist)

- [ ] **Step 2: Create `backend/app/worker/prompts.py`**

```python
"""Background message templates for the async tool pipeline.

Only two templates: S2 success and papers ingested.
Failures are communicated via background_error SSE events — never as background messages.
"""

S2_RESULTS = """\
[Background: Literature Search Results]
Your earlier search for "{query}" found {n} paper(s):

{papers_formatted}

Please analyze these results and provide relevant information to the conversation."""

PAPERS_INGESTED = """\
[Background: New Papers Available]
The following articles from your earlier search have been parsed and added to the knowledge base:

{papers_formatted}

Please search the RAG corpus for detailed information from these documents relevant to this conversation."""
```

- [ ] **Step 3: Create `backend/app/api/routes/internal.py`**

```python
"""Internal endpoints — no auth, Docker-network only. Never expose to public internet."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.redis import get_sync_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


class QueueBackgroundToolRequest(BaseModel):
    type: str  # only "s2_search" supported
    conversation_id: str
    query: str
    max_results: int = 5


@router.post("/queue-background-tool", status_code=202)
def queue_background_tool(payload: QueueBackgroundToolRequest) -> dict:
    """Queue a background tool call. Called by ai-agent literature_search tool."""
    if payload.type != "s2_search":
        return {"status": "ignored", "reason": f"unknown type: {payload.type}"}

    # Import here to avoid circular import at module load time
    from app.worker.tasks.continuation import run_s2_search

    # Persist query for retry support (24h TTL)
    r = get_sync_redis()
    r.set(
        f"s2_last_query:{payload.conversation_id}",
        payload.query,
        ex=24 * 3600,
    )

    run_s2_search.delay(payload.conversation_id, payload.query, payload.max_results)
    logger.info("Queued run_s2_search for conv=%s query=%r", payload.conversation_id, payload.query)
    return {"status": "queued"}
```

- [ ] **Step 4: Mount the internal router in `backend/app/main.py`**

Add import alongside the existing `api_router` import:
```python
from app.api.routes.internal import router as internal_router
```

Add after `app.include_router(api_router, ...)`:
```python
app.include_router(internal_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/api/test_internal.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/worker/prompts.py backend/app/api/routes/internal.py backend/app/main.py backend/tests/api/test_internal.py
git commit -m "feat(backend): add /internal router and prompt templates"
```

---

## Task 5: Backend — `run_s2_search` Celery task

**Files:**
- Create: `backend/app/worker/tasks/continuation.py` (initial version)
- Test: `backend/tests/worker/test_continuation.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/worker/test_continuation.py
from unittest.mock import MagicMock, patch, call
import json
import pytest


def _make_papers():
    return [
        {
            "title": "Aspirin Synthesis Review",
            "authors": "Alice, Bob",
            "year": 2023,
            "doi": "10.1234/asp",
            "abstract": "A review of aspirin synthesis routes.",
            "citation_count": 42,
            "url": "https://example.com/paper1",
        }
    ]


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.monitor_ingestion")
@patch("app.worker.tasks.continuation._submit_article_jobs")
@patch("app.worker.tasks.continuation.httpx.post")
@patch("app.worker.tasks.continuation.get_sync_redis")
@patch("app.worker.tasks.continuation.Session")
def test_run_s2_search_success_path(
    mock_session, mock_redis, mock_post, mock_submit, mock_monitor, mock_continuation
):
    """Success: saves background message, dispatches continuation and monitor_ingestion."""
    mock_post.return_value.__enter__ = mock_post.return_value
    mock_post.return_value.__exit__ = MagicMock(return_value=False)
    mock_post.return_value.json.return_value = {"papers": _make_papers(), "query": "aspirin"}
    mock_post.return_value.raise_for_status = MagicMock()

    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_submit.return_value = [{"doi": "10.1234/asp", "job_id": "job-uuid-1"}]

    mock_db = MagicMock()
    mock_session.return_value.__enter__ = lambda s: mock_db
    mock_session.return_value.__exit__ = MagicMock(return_value=False)

    from app.worker.tasks.continuation import run_s2_search
    run_s2_search("conv-123", "aspirin", 5)

    # Background message saved
    mock_db.add.assert_called_once()
    saved_msg = mock_db.add.call_args[0][0]
    assert saved_msg.role == "background"
    assert "[Background: Literature Search Results]" in saved_msg.content
    assert saved_msg.metadata == {"variant": "info"}

    # background_update SSE published
    mock_r.publish.assert_called()

    # Continuation and monitor dispatched
    mock_continuation.apply_async.assert_called_once()
    mock_monitor.delay.assert_called_once()


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.httpx.post")
@patch("app.worker.tasks.continuation.get_sync_redis")
@patch("app.worker.tasks.continuation.Session")
def test_run_s2_search_no_papers_publishes_error_event(
    mock_session, mock_redis, mock_post, mock_continuation
):
    """No papers: publish background_error SSE, do NOT dispatch continuation."""
    mock_post.return_value.__enter__ = mock_post.return_value
    mock_post.return_value.__exit__ = MagicMock(return_value=False)
    mock_post.return_value.json.return_value = {"papers": [], "query": "xyz"}
    mock_post.return_value.raise_for_status = MagicMock()

    mock_r = MagicMock()
    mock_redis.return_value = mock_r

    from app.worker.tasks.continuation import run_s2_search
    run_s2_search("conv-123", "xyz", 5)

    # background_error SSE published
    published = json.loads(mock_r.publish.call_args[0][1])
    assert published["event"] == "background_error"

    # No continuation dispatched
    mock_continuation.delay.assert_not_called()
```

Run: `cd backend && uv run pytest tests/worker/test_continuation.py -v -k "s2_search"`
Expected: FAIL (module doesn't exist)

- [ ] **Step 2: Create `backend/app/worker/tasks/continuation.py`** (with `run_s2_search` only)

```python
"""Async pipeline Celery tasks: run_s2_search, monitor_ingestion, run_agent_continuation."""
from __future__ import annotations

import json
import logging

import httpx
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.core.redis import get_sync_redis
from app.models import ChatMessage, Conversation, get_datetime_utc
from app.worker import prompts
from app.worker.celery_app import celery_app
from app.worker.tasks.chat import _submit_article_jobs

logger = logging.getLogger(__name__)

_AI_AGENT_URL = settings.AI_AGENT_URL


def _publish_sync(conversation_id: str, data: dict) -> None:
    r = get_sync_redis()
    r.publish(f"conversation:{conversation_id}", json.dumps(data, default=str))


def save_background_message(
    conversation_id: str,
    content: str,
    variant: str = "info",
) -> None:
    """Persist a background message. variant='info'|'error' controls frontend card style."""
    with Session(engine) as db:
        msg = ChatMessage(
            conversation_id=conversation_id,
            role="background",
            content=content,
            metadata={"variant": variant},
        )
        db.add(msg)
        db.commit()


def _format_s2_results(papers: list[dict], query: str) -> str:
    lines = []
    for i, p in enumerate(papers, 1):
        doi = p.get("doi") or "N/A"
        authors = p.get("authors") or "Unknown"
        year = p.get("year") or "N/A"
        title = p.get("title") or "Untitled"
        abstract = p.get("abstract") or "No abstract."
        if len(abstract) > 400:
            abstract = abstract[:400] + "..."
        lines.append(
            f"{i}. **{title}** — {authors} ({year}) — DOI: {doi}\n"
            f"   Abstract: {abstract}"
        )
    papers_formatted = "\n\n".join(lines)
    return prompts.S2_RESULTS.format(
        query=query,
        n=len(papers),
        papers_formatted=papers_formatted,
    )


@celery_app.task(queue="chat", ignore_result=True)
def run_s2_search(conversation_id: str, query: str, max_results: int = 5) -> None:
    """Call ai-agent blocking S2 search, save background message, dispatch continuation."""
    logger.info("run_s2_search started conv=%s query=%r", conversation_id, query)

    # 1. Call ai-agent blocking endpoint
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{_AI_AGENT_URL}/internal/s2-search",
                json={"query": query, "max_results": max_results},
            )
            resp.raise_for_status()
        papers = resp.json().get("papers", [])
    except Exception:
        logger.exception("S2 search failed for conv=%s", conversation_id)
        _publish_sync(conversation_id, {
            "event": "background_error",
            "detail": f"Literature search for \"{query}\" failed. Please try again.",
            "retry_available": True,
        })
        return

    # 2. No results
    if not papers:
        _publish_sync(conversation_id, {
            "event": "background_error",
            "detail": f"No papers found for \"{query}\".",
            "retry_available": False,
        })
        return

    # 3. Submit article downloads
    r = get_sync_redis()
    dois = [p["doi"] for p in papers if p.get("doi")]
    new_jobs = _submit_article_jobs(r, conversation_id, dois)

    # 4. Save paper metadata per job_id for PAPERS_INGESTED prompt
    paper_by_doi = {p["doi"]: p for p in papers if p.get("doi")}
    for job in new_jobs:
        meta_key = f"s2_paper_meta:{job['job_id']}"
        r.set(meta_key, json.dumps(paper_by_doi.get(job["doi"], {})), ex=48 * 3600)

    # 5. Save background message (S2 results)
    content = _format_s2_results(papers, query)
    save_background_message(conversation_id, content, variant="info")

    # 6. Publish background_update so frontend re-enables SSE
    _publish_sync(conversation_id, {"event": "background_update"})

    # 7. Dispatch continuation (abstract-level response) and ingestion monitor
    # countdown=1 gives frontend time to re-enable SSE before streaming starts
    run_agent_continuation.apply_async(args=[conversation_id], countdown=1)

    if new_jobs:
        job_ids = [j["job_id"] for j in new_jobs]
        monitor_ingestion.delay(conversation_id, job_ids)

    logger.info(
        "run_s2_search done conv=%s papers=%d jobs=%d",
        conversation_id, len(papers), len(new_jobs),
    )
```

Note: `monitor_ingestion` and `run_agent_continuation` are referenced before they are defined. Add forward stubs after this function and define them properly in Tasks 6 and 7.

Add these stubs immediately after `run_s2_search` (they will be replaced in Tasks 6 & 7):
```python
# Forward declarations — full implementations in Tasks 6 and 7
@celery_app.task(queue="chat", ignore_result=True)
def run_agent_continuation(conversation_id: str) -> None:
    raise NotImplementedError("Task 7")


@celery_app.task(bind=True, queue="chat", max_retries=120, default_retry_delay=10, ignore_result=True)
def monitor_ingestion(self, conversation_id: str, job_ids: list[str]) -> None:
    raise NotImplementedError("Task 6")
```

- [ ] **Step 3: Register the new module in `backend/app/worker/celery_app.py`**

In the `include` list, add:
```python
        "app.worker.tasks.continuation",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/worker/test_continuation.py -v -k "s2_search"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/worker/tasks/continuation.py backend/app/worker/celery_app.py backend/tests/worker/test_continuation.py
git commit -m "feat(backend): add run_s2_search Celery task"
```

---

## Task 6: Backend — `monitor_ingestion` Celery task

**Files:**
- Modify: `backend/app/worker/tasks/continuation.py`
- Modify: `backend/tests/worker/test_continuation.py` (add tests)

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/worker/test_continuation.py`:
```python
@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.get_sync_redis")
@patch("app.worker.tasks.continuation.httpx.Client")
def test_monitor_ingestion_success_all_done(mock_client_cls, mock_redis, mock_continuation):
    """All jobs fetched+parsed → save background message, dispatch continuation."""
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__ = lambda s: mock_client
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

    def _mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "/jobs/" in url and "/parse" not in url and "pdf-parser" not in url:
            # article-fetcher
            resp.json.return_value = {"status": "done"}
        else:
            # pdf-parser
            resp.json.return_value = {"status": "completed"}
        return resp

    mock_client.get.side_effect = _mock_get

    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.get.return_value = json.dumps({
        "title": "Paper A", "authors": "Alice", "year": 2023, "doi": "10.1/a"
    })

    with patch("app.worker.tasks.continuation.save_background_message") as mock_save, \
         patch("app.worker.tasks.continuation._publish_sync"):
        from app.worker.tasks.continuation import monitor_ingestion
        monitor_ingestion("conv-123", ["job-1"])

    mock_save.assert_called_once()
    args = mock_save.call_args[0]
    assert args[0] == "conv-123"
    assert "[Background: New Papers Available]" in args[1]
    mock_continuation.apply_async.assert_called_once()


@patch("app.worker.tasks.continuation.httpx.Client")
@patch("app.worker.tasks.continuation.get_sync_redis")
def test_monitor_ingestion_404_is_pending_not_failed(mock_redis, mock_client_cls):
    """pdf-parser 404 means 'not yet created' — treat as pending, not failed."""
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__ = lambda s: mock_client
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

    call_count = {"n": 0}

    def _mock_get(url, **kwargs):
        resp = MagicMock()
        call_count["n"] += 1
        if "article-fetcher" in url or "/fetch" in url:
            resp.status_code = 200
            resp.json.return_value = {"status": "done"}
        else:
            # pdf-parser returns 404 on first call
            resp.status_code = 404
        return resp

    mock_client.get.side_effect = _mock_get
    mock_redis.return_value = MagicMock()

    from celery.exceptions import Retry
    from app.worker.tasks.continuation import monitor_ingestion

    # Bind self mock for retry
    task = monitor_ingestion
    with patch.object(task, "retry", side_effect=Retry) as mock_retry:
        with pytest.raises(Retry):
            monitor_ingestion("conv-123", ["job-1"])
    mock_retry.assert_called_once()


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.httpx.Client")
@patch("app.worker.tasks.continuation.get_sync_redis")
def test_monitor_ingestion_all_fetch_failed_publishes_error(mock_redis, mock_client_cls, mock_continuation):
    """All article-fetcher jobs failed → publish background_error, stop pipeline."""
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__ = lambda s: mock_client
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"status": "failed"}
    mock_client.get.return_value = resp
    mock_redis.return_value = MagicMock()

    with patch("app.worker.tasks.continuation._publish_sync") as mock_pub:
        from app.worker.tasks.continuation import monitor_ingestion
        monitor_ingestion("conv-123", ["job-1"])

    published = json.loads(mock_pub.call_args[0][1])
    assert published["event"] == "background_error"
    mock_continuation.delay.assert_not_called()
```

Run: `cd backend && uv run pytest tests/worker/test_continuation.py -v -k "monitor"`
Expected: FAIL

- [ ] **Step 2: Replace the `monitor_ingestion` stub in `continuation.py`**

Replace the stub with the real implementation:
```python
def _get_fetch_status(client: httpx.Client, job_id: str) -> str:
    """Get article-fetcher status for a job_id. Returns 'pending'|'done'|'failed'."""
    try:
        resp = client.get(f"{settings.ARTICLE_FETCHER_URL}/jobs/{job_id}", timeout=5.0)
        if resp.status_code == 200:
            return resp.json().get("status", "pending")
        return "pending"
    except Exception:
        logger.warning("Failed to get fetch status for job %s", job_id, exc_info=True)
        return "pending"


def _get_parse_status(client: httpx.Client, job_id: str) -> str:
    """Get pdf-parser status for a job_id.
    Returns 'pending' on HTTP 404 — job not yet created by article-fetcher webhook.
    """
    try:
        resp = client.get(f"{settings.PDF_PARSER_URL}/jobs/{job_id}", timeout=5.0)
        if resp.status_code == 404:
            return "pending"  # not yet created — treat as pending, never as failed
        if resp.status_code == 200:
            return resp.json().get("status", "pending")
        return "pending"
    except Exception:
        logger.warning("Failed to get parse status for job %s", job_id, exc_info=True)
        return "pending"


def _trigger_rag_continuation(conversation_id: str, completed_job_ids: list[str] | None = None) -> None:
    """Build PAPERS_INGESTED message from Redis metadata and dispatch continuation.

    `completed_job_ids` is optional. When provided (by monitor_ingestion), paper titles/DOIs
    are listed in the message. When omitted (manual "Notify Agent" button), a generic message
    is sent — still tells the agent to search RAG, just without the paper list.
    """
    r = get_sync_redis()
    lines = []
    for i, job_id in enumerate(completed_job_ids or [], 1):
        raw = r.get(f"s2_paper_meta:{job_id}")
        if raw:
            p = json.loads(raw)
            doi = p.get("doi") or "N/A"
            title = p.get("title") or "Untitled"
            authors = p.get("authors") or "Unknown"
            year = p.get("year") or "N/A"
            lines.append(f"{i}. {title} — {authors} ({year}) — DOI: {doi}")
    papers_formatted = "\n".join(lines) if lines else "recently parsed articles"
    content = prompts.PAPERS_INGESTED.format(papers_formatted=papers_formatted)
    save_background_message(conversation_id, content, variant="info")
    _publish_sync(conversation_id, {"event": "background_update"})
    run_agent_continuation.apply_async(args=[conversation_id], countdown=1)


@celery_app.task(
    bind=True,
    queue="chat",
    max_retries=120,
    default_retry_delay=10,
    ignore_result=True,
)
def monitor_ingestion(self, conversation_id: str, job_ids: list[str]) -> None:
    """Poll article-fetcher and pdf-parser until all jobs complete, then trigger RAG continuation."""
    logger.debug("monitor_ingestion poll conv=%s job_ids=%s", conversation_id, job_ids)

    with httpx.Client(timeout=10.0) as client:
        fetch_statuses = {jid: _get_fetch_status(client, jid) for jid in job_ids}

        # STOP: all downloads failed — nothing to parse
        if all(s == "failed" for s in fetch_statuses.values()):
            logger.warning("All article downloads failed for conv=%s", conversation_id)
            _publish_sync(conversation_id, {
                "event": "background_error",
                "detail": "All article downloads failed.",
                "retry_available": False,
            })
            return

        # Only check pdf-parser for jobs where article-fetcher is done
        # (404 from pdf-parser = not yet created = pending)
        done_fetch = [jid for jid, s in fetch_statuses.items() if s == "done"]
        parse_statuses = {jid: _get_parse_status(client, jid) for jid in done_fetch}

        # STOP: any parse failed
        if any(s == "failed" for s in parse_statuses.values()):
            logger.warning("Parse failure detected for conv=%s", conversation_id)
            _publish_sync(conversation_id, {
                "event": "background_error",
                "detail": "One or more articles failed to parse.",
                "retry_available": False,
            })
            return

        # WAIT: any download still running
        if any(s not in ("done", "failed") for s in fetch_statuses.values()):
            raise self.retry()

        # WAIT: any parse not yet completed
        if any(s != "completed" for s in parse_statuses.values()):
            raise self.retry()

    # SUCCESS: all fetched + all parsed
    completed_jobs = [jid for jid, s in parse_statuses.items() if s == "completed"]
    _trigger_rag_continuation(conversation_id, completed_jobs)
    logger.info("monitor_ingestion complete conv=%s", conversation_id)


def _on_monitor_ingestion_failure(self, exc, task_id, args, kwargs, einfo):
    """Called when monitor_ingestion exhausts retries (20 min). Log as WARNING only."""
    conversation_id = args[0] if args else "unknown"
    logger.warning(
        "monitor_ingestion timed out after max retries for conv=%s — user already has initial response",
        conversation_id,
    )
```

Add the failure handler registration after the task definition:
```python
monitor_ingestion.on_failure = _on_monitor_ingestion_failure
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/worker/test_continuation.py -v -k "monitor"`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/worker/tasks/continuation.py backend/tests/worker/test_continuation.py
git commit -m "feat(backend): implement monitor_ingestion Celery task"
```

---

## Task 7: Backend — `run_agent_continuation` Celery task

**Files:**
- Modify: `backend/app/worker/tasks/continuation.py`
- Modify: `backend/tests/worker/test_continuation.py` (add tests)

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/worker/test_continuation.py`:
```python
@patch("app.worker.tasks.continuation.get_sync_redis")
@patch("app.worker.tasks.continuation.Session")
@patch("app.worker.tasks.continuation._process_streaming")
def test_run_agent_continuation_acquires_lock_streams_saves(
    mock_streaming, mock_session, mock_redis
):
    """Continuation acquires lock, loads history, streams, saves assistant message."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.set.return_value = True  # lock acquired

    mock_db = MagicMock()
    mock_session.return_value.__enter__ = lambda s: mock_db
    mock_session.return_value.__exit__ = MagicMock(return_value=False)

    # Simulate DB messages
    msg1 = MagicMock()
    msg1.role = "user"
    msg1.content = "What is aspirin?"
    msg2 = MagicMock()
    msg2.role = "background"
    msg2.content = "[Background: Literature Search Results]\n..."
    mock_db.exec.return_value.all.return_value = [msg1, msg2]
    mock_db.get.return_value = MagicMock()  # Conversation

    mock_streaming.return_value = ("Aspirin is an analgesic.", None)

    assistant_msg = MagicMock()
    assistant_msg.id = "msg-uuid"
    assistant_msg.created_at = "2026-04-02T12:00:00"

    def _refresh(obj):
        obj.id = "msg-uuid"
        obj.created_at = "2026-04-02T12:00:00"

    mock_db.refresh.side_effect = _refresh

    # No pending queue
    mock_r.llen.return_value = 0

    from app.worker.tasks.continuation import run_agent_continuation
    run_agent_continuation("conv-123")

    # Lock acquired and released
    mock_r.set.assert_called_with("conv_processing:conv-123", "1", nx=True, ex=600)
    mock_r.delete.assert_called_with("conv_processing:conv-123")

    # Streaming called
    mock_streaming.assert_called_once()

    # Assistant message saved
    mock_db.add.assert_called_once()
    saved = mock_db.add.call_args[0][0]
    assert saved.role == "assistant"
    assert saved.content == "Aspirin is an analgesic."


@patch("app.worker.tasks.continuation.get_sync_redis")
def test_run_agent_continuation_queues_if_locked(mock_redis):
    """If lock is taken, push to conv_pending and return without streaming."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.set.return_value = None  # lock NOT acquired

    with patch("app.worker.tasks.continuation._process_streaming") as mock_streaming:
        from app.worker.tasks.continuation import run_agent_continuation
        run_agent_continuation("conv-123")

    mock_r.rpush.assert_called_once_with("conv_pending:conv-123", "1")
    mock_streaming.assert_not_called()


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.get_sync_redis")
@patch("app.worker.tasks.continuation.Session")
@patch("app.worker.tasks.continuation._process_streaming")
def test_run_agent_continuation_drains_pending_queue(
    mock_streaming, mock_session, mock_redis, mock_self_delay
):
    """After finishing, drain conv_pending and dispatch one new continuation."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.set.return_value = True  # lock acquired
    mock_r.llen.return_value = 3   # 3 pending signals

    mock_db = MagicMock()
    mock_session.return_value.__enter__ = lambda s: mock_db
    mock_session.return_value.__exit__ = MagicMock(return_value=False)
    mock_db.exec.return_value.all.return_value = []
    mock_db.get.return_value = MagicMock()
    mock_db.refresh.side_effect = lambda obj: setattr(obj, "id", "x")
    mock_streaming.return_value = ("", None)

    from app.worker.tasks.continuation import run_agent_continuation
    run_agent_continuation("conv-123")

    # Full queue deleted, single continuation dispatched
    mock_r.delete.assert_any_call("conv_pending:conv-123")
    mock_self_delay.apply_async.assert_called_once_with(args=["conv-123"], countdown=0)
```

Run: `cd backend && uv run pytest tests/worker/test_continuation.py -v -k "continuation"`
Expected: FAIL

- [ ] **Step 2: Replace `run_agent_continuation` stub in `continuation.py`**

```python
@celery_app.task(queue="chat", ignore_result=True)
def run_agent_continuation(conversation_id: str) -> None:
    """Re-invoke the agent with fresh history (includes background messages).

    Uses per-conversation lock to prevent concurrent streaming:
    - conv_processing:{id} — SET NX EX 600 (atomic, avoids permanent lock on crash)
    - conv_pending:{id}    — Redis list for queued signals
    """
    # Import here to avoid circular import
    from app.worker.tasks.chat import _process_streaming

    r = get_sync_redis()
    lock_key = f"conv_processing:{conversation_id}"
    pending_key = f"conv_pending:{conversation_id}"

    # Atomic acquire — single command, avoids SETNX+EXPIRE race condition
    acquired = r.set(lock_key, "1", nx=True, ex=600)
    if not acquired:
        r.rpush(pending_key, "1")
        logger.info("run_agent_continuation queued for conv=%s (already processing)", conversation_id)
        return

    try:
        with Session(engine) as db:
            messages_db = db.exec(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(col(ChatMessage.created_at).asc())
            ).all()
            messages_payload = [
                {"role": msg.role, "content": msg.content}
                for msg in messages_db
            ]

        _publish_sync(conversation_id, {"event": "thinking", "conversation_id": conversation_id})

        try:
            assistant_content, tool_calls_raw = _process_streaming(
                conversation_id, messages_payload, r,
            )
        except Exception:
            logger.exception("Streaming failed in run_agent_continuation conv=%s", conversation_id)
            return

        tool_calls_json = json.dumps(tool_calls_raw) if tool_calls_raw else None

        with Session(engine) as db:
            assistant_message = ChatMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_content,
                tool_calls=tool_calls_json,
            )
            db.add(assistant_message)

            conv = db.get(Conversation, conversation_id)
            if conv:
                conv.updated_at = get_datetime_utc()
                db.add(conv)

            db.commit()
            db.refresh(assistant_message)
            msg_id = str(assistant_message.id)

        _publish_sync(conversation_id, {
            "event": "message",
            "id": msg_id,
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": tool_calls_json,
            "created_at": str(assistant_message.created_at),
        })

        logger.info("run_agent_continuation complete conv=%s msg=%s", conversation_id, msg_id)

    finally:
        r.delete(lock_key)
        # Drain entire pending queue into a single dispatch (multiple queued = one re-run)
        if r.llen(pending_key) > 0:
            r.delete(pending_key)
            run_agent_continuation.apply_async(args=[conversation_id], countdown=0)
```

Add the missing imports at top of the file (after existing imports):
```python
from sqlmodel import col, select
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/worker/test_continuation.py -v`
Expected: All continuation tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/worker/tasks/continuation.py backend/tests/worker/test_continuation.py
git commit -m "feat(backend): implement run_agent_continuation Celery task with per-conv lock"
```

---

## Task 8: Backend — add `conv_processing` lock to `process_chat_message`, remove dead code

**Files:**
- Modify: `backend/app/worker/tasks/chat.py`
- Test: `backend/tests/worker/test_chat_article_helpers.py` (existing — verify no regression)

- [ ] **Step 1: Write a test asserting the DOI extraction branch for `literature_search` is gone**

Add to `backend/tests/worker/test_chat_article_helpers.py`:
```python
def test_literature_search_tool_end_does_not_submit_jobs():
    """literature_search now returns 'queued' — _process_streaming must not extract DOIs from it."""
    import inspect
    from app.worker.tasks import chat
    source = inspect.getsource(chat._process_streaming)
    # The dead code branch that submitted jobs on literature_search tool_end must be removed
    assert 'name == "literature_search"' not in source, (
        "Dead code: literature_search DOI extraction branch must be removed from _process_streaming"
    )
```

Run: `cd backend && uv run pytest tests/worker/test_chat_article_helpers.py -v -k "not_submit_jobs"`
Expected: FAIL (branch still present)

- [ ] **Step 2: Update `backend/app/worker/tasks/chat.py`**

**A) Add import** (near top with other imports):
```python
from app.core.redis import get_sync_redis as _get_sync_redis_core
```

**B) Remove the `literature_search` branch** from `_process_streaming`. Delete lines 216–224:
```python
                    if name == "literature_search":
                        dois = _extract_dois(output)
                        if dois:
                            new_jobs = _submit_article_jobs(r, conversation_id, dois)
                            if new_jobs:
                                _publish(r, conversation_id, {
                                    "event": "article_downloads",
                                    "jobs": new_jobs,
                                })
```

**C) Add lock acquisition to `process_chat_message`**. Replace the task body's try/except block with a lock-wrapping version:

Replace the `r = _get_redis()` line and everything after it until the end of the function with:

```python
    r = _get_redis()
    lock_key = f"conv_processing:{conversation_id}"
    pending_key = f"conv_pending:{conversation_id}"

    # Atomic SET NX EX — prevents concurrent streaming on the same conversation
    r.set(lock_key, "1", nx=True, ex=600)  # best-effort; don't block if already set

    _publish(r, conversation_id, {
        "event": "thinking",
        "conversation_id": conversation_id,
    })

    try:
        with Session(engine) as session:
            conv = session.get(Conversation, conversation_id)
            if not conv:
                raise ValueError(f"Conversation {conversation_id} not found")

            messages_db = session.exec(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(col(ChatMessage.created_at).asc())
            ).all()

            messages_payload = [
                {"role": msg.role, "content": msg.content}
                for msg in messages_db
            ]

        # Inject article download status context
        stored_jobs = _get_conversation_article_jobs(r, conversation_id)
        if stored_jobs:
            statuses = _fetch_article_statuses(stored_jobs)
            status_block = _build_article_status_block(statuses)
            if status_block:
                messages_payload = [{"role": "user", "content": status_block}] + messages_payload

        try:
            assistant_content, tool_calls_raw = _process_streaming(
                conversation_id, messages_payload, r,
            )
        except Exception:
            logger.warning(
                "Streaming failed for conversation %s, falling back to sync",
                conversation_id,
                exc_info=True,
            )
            assistant_content, tool_calls_raw = _process_sync(
                conversation_id, messages_payload,
            )

        tool_calls_json = json.dumps(tool_calls_raw) if tool_calls_raw else None

        with Session(engine) as session:
            assistant_message = ChatMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_content,
                tool_calls=tool_calls_json,
            )
            session.add(assistant_message)

            conv = session.get(Conversation, conversation_id)
            if conv:
                conv.updated_at = get_datetime_utc()
                session.add(conv)

            session.commit()
            session.refresh(assistant_message)
            msg_id = str(assistant_message.id)

        _publish(r, conversation_id, {
            "event": "message",
            "id": msg_id,
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": tool_calls_json,
            "created_at": str(assistant_message.created_at),
        })

        return {
            "status": "completed",
            "conversation_id": conversation_id,
            "message_id": msg_id,
        }

    except httpx.HTTPStatusError as exc:
        error_msg = f"AI Agent returned {exc.response.status_code}: {exc.response.text}"
        logger.exception("Chat task failed for conversation %s", conversation_id)
        _publish(r, conversation_id, {
            "event": "error",
            "conversation_id": conversation_id,
            "detail": error_msg,
        })
        raise

    except Exception as exc:
        error_msg = str(exc)
        logger.exception("Chat task failed for conversation %s", conversation_id)
        _publish(r, conversation_id, {
            "event": "error",
            "conversation_id": conversation_id,
            "detail": error_msg,
        })
        raise

    finally:
        # Always release lock — even on crash/timeout
        r.delete(lock_key)
        # If a continuation was queued while we were processing, dispatch it now
        if r.llen(pending_key) > 0:
            r.delete(pending_key)
            from app.worker.tasks.continuation import run_agent_continuation
            run_agent_continuation.apply_async(args=[conversation_id], countdown=0)
```

- [ ] **Step 3: Run tests**

Run: `cd backend && uv run pytest tests/worker/ -v`
Expected: All pass including the new `not_submit_jobs` test.

- [ ] **Step 4: Commit**

```bash
git add backend/app/worker/tasks/chat.py backend/tests/worker/test_chat_article_helpers.py
git commit -m "feat(backend): add conv_processing lock to process_chat_message, remove dead literature_search DOI branch"
```

---

## Task 9: Backend — retry-s2-search + trigger-rag-continuation API endpoints

**Files:**
- Modify: `backend/app/api/routes/articles.py`
- Test: `backend/tests/api/test_articles_background.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/api/test_articles_background.py
import uuid
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
CONV_ID = str(uuid.uuid4())


def _auth_headers(client):
    from tests.utils.utils import get_superuser_token_headers
    return get_superuser_token_headers(client)


def test_retry_s2_search_returns_202_when_query_exists():
    headers = _auth_headers(client)
    with patch("app.api.routes.articles.get_async_redis") as mock_redis, \
         patch("app.api.routes.articles.run_s2_search") as mock_task:
        mock_r = MagicMock()
        mock_r.get = MagicMock(return_value="aspirin synthesis")
        mock_redis.return_value = mock_r
        mock_task.delay.return_value = None

        resp = client.post(
            f"/api/v1/articles/conversations/{CONV_ID}/retry-s2-search",
            headers=headers,
        )
    assert resp.status_code == 202


def test_retry_s2_search_returns_410_when_query_expired():
    headers = _auth_headers(client)
    with patch("app.api.routes.articles.get_async_redis") as mock_redis:
        mock_r = MagicMock()
        mock_r.get = MagicMock(return_value=None)
        mock_redis.return_value = mock_r

        resp = client.post(
            f"/api/v1/articles/conversations/{CONV_ID}/retry-s2-search",
            headers=headers,
        )
    assert resp.status_code == 410
    assert "expired" in resp.json()["detail"].lower()


def test_trigger_rag_continuation_returns_202():
    headers = _auth_headers(client)
    with patch("app.api.routes.articles._trigger_rag_continuation") as mock_trigger:
        resp = client.post(
            f"/api/v1/articles/conversations/{CONV_ID}/trigger-rag-continuation",
            headers=headers,
        )
    assert resp.status_code == 202
    mock_trigger.assert_called_once_with(str(CONV_ID))
```

Run: `cd backend && uv run pytest tests/api/test_articles_background.py -v`
Expected: FAIL (endpoints don't exist)

- [ ] **Step 2: Add endpoints to `backend/app/api/routes/articles.py`**

Add new imports at the top of the file:
```python
from app.core.redis import get_async_redis
```

Add new endpoints at the bottom of the file:
```python
@router.post("/conversations/{conversation_id}/retry-s2-search", status_code=202)
async def retry_s2_search(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
) -> dict:
    """Re-run the last S2 search for a conversation. Returns 410 if the query has expired (>24h)."""
    from app.worker.tasks.continuation import run_s2_search

    r = get_async_redis()
    query = await r.get(f"s2_last_query:{conversation_id}")
    if not query:
        raise HTTPException(
            status_code=410,
            detail="Search query expired. Please start a new search.",
        )
    run_s2_search.delay(str(conversation_id), query)
    return {"status": "queued"}


@router.post("/conversations/{conversation_id}/trigger-rag-continuation", status_code=202)
async def trigger_rag_continuation(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
) -> dict:
    """Manually trigger a RAG-based agent continuation (used by 'Notify Agent' button).

    Saves a [Background: New Papers Available] message then dispatches run_agent_continuation,
    sharing the same _trigger_rag_continuation helper used by monitor_ingestion on success.
    job_ids are not passed — the generic PAPERS_INGESTED message is used.
    """
    from app.worker.tasks.continuation import _trigger_rag_continuation

    # Run synchronously from the route handler — it's fast (Redis + DB write + task dispatch).
    # No need to offload to Celery here.
    _trigger_rag_continuation(str(conversation_id))
    return {"status": "queued"}
```

- [ ] **Step 3: Run tests**

Run: `cd backend && uv run pytest tests/api/test_articles_background.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes/articles.py backend/tests/api/test_articles_background.py
git commit -m "feat(backend): add retry-s2-search and trigger-rag-continuation API endpoints"
```

---

## Task 10: Frontend — update `chatTypes.ts` with metadata + new SSE event types

**Files:**
- Modify: `frontend/src/client/chatTypes.ts`

No automated test for this step — TypeScript compiler is the test.

- [ ] **Step 1: Update `ChatMessagePublic`** to include `metadata`

```typescript
export type ChatMessagePublic = {
  id: string
  conversation_id: string
  role: string
  content: string
  tool_calls: string | null
  created_at: string | null
  metadata: Record<string, unknown> | null
}
```

- [ ] **Step 2: Add new SSE event types** to `SSEEvent` union in `chatTypes.ts`

Replace the existing `SSEEvent` type definition with:
```typescript
export type SSEEvent =
  | { event: "connected"; data: { conversation_id: string } }
  | { event: "thinking"; data: Record<string, unknown> }
  | {
      event: "message"
      data: {
        id?: string
        role: string
        content: string
        tool_calls?: string | null
      }
    }
  | {
      event: "token"
      data: { content: string }
    }
  | { event: "tool_call"; data: ToolCallInfo }
  | { event: "hazards"; data: { chemicals: HazardChemical[] } }
  | { event: "article_downloads"; data: { jobs: ArticleDownloadJob[] } }
  | { event: "error"; data: { detail: string } }
  | { event: "background_update"; data: Record<string, unknown> }
  | {
      event: "background_error"
      data: { detail: string; retry_available: boolean }
    }
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && bun run build 2>&1 | head -30`
Expected: No TypeScript errors related to `chatTypes.ts`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/client/chatTypes.ts
git commit -m "feat(frontend): add metadata to ChatMessagePublic, add background SSE event types"
```

---

## Task 11: Frontend — unit test framework (Vitest + React Testing Library)

**Files:**
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/test/setup.ts`
- Modify: `frontend/package.json`

This task sets up Vitest so that Tasks 12–15 can add `*.test.tsx` files. Run once; all subsequent tasks build on it.

- [ ] **Step 1: Install dev dependencies**

```bash
cd frontend
bun add -d vitest @vitejs/plugin-react @testing-library/react @testing-library/user-event @testing-library/jest-dom jsdom
```

- [ ] **Step 2: Create `frontend/vitest.config.ts`**

```typescript
import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"
import path from "path"

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
})
```

- [ ] **Step 3: Create `frontend/src/test/setup.ts`**

```typescript
import "@testing-library/jest-dom"
```

- [ ] **Step 4: Add `test:unit` script to `frontend/package.json`**

In the `"scripts"` block, add:
```json
"test:unit": "vitest run",
"test:unit:watch": "vitest"
```

- [ ] **Step 5: Verify the setup works with a trivial test**

Create `frontend/src/test/smoke.test.ts`:
```typescript
import { describe, it, expect } from "vitest"

describe("vitest setup", () => {
  it("works", () => {
    expect(1 + 1).toBe(2)
  })
})
```

Run: `cd frontend && bun run test:unit`
Expected: 1 test passes.

- [ ] **Step 6: Delete the smoke test and commit**

```bash
rm frontend/src/test/smoke.test.ts
git add frontend/vitest.config.ts frontend/src/test/setup.ts frontend/package.json
git commit -m "feat(frontend): add Vitest + React Testing Library unit test framework"
```

---

## Task 12: Frontend — `BackgroundMessageCard` component

**Files:**
- Create: `frontend/src/components/Chat/BackgroundMessageCard.tsx`

- [ ] **Step 1: Create the component**

```typescript
// frontend/src/components/Chat/BackgroundMessageCard.tsx
import { AlertCircle, Info, RefreshCw } from "lucide-react"
import { useState } from "react"

import { OpenAPI } from "@/client"
import type { ChatMessagePublic } from "@/client/chatTypes"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface BackgroundMessageCardProps {
  message: ChatMessagePublic
}

async function apiFetch(path: string, options?: RequestInit) {
  const token =
    typeof OpenAPI.TOKEN === "function"
      ? await OpenAPI.TOKEN({} as never)
      : (OpenAPI.TOKEN ?? "")
  return fetch(path, {
    headers: { Authorization: `Bearer ${token}` },
    ...options,
  })
}

export function BackgroundMessageCard({ message }: BackgroundMessageCardProps) {
  const variant = (message.metadata?.variant as string) ?? "info"
  const isError = variant === "error"
  const [retrying, setRetrying] = useState(false)
  const [retryMessage, setRetryMessage] = useState<string | null>(null)

  const handleRetry = async () => {
    setRetrying(true)
    setRetryMessage(null)
    try {
      const resp = await apiFetch(
        `/api/v1/articles/conversations/${message.conversation_id}/retry-s2-search`,
        { method: "POST" },
      )
      if (resp.status === 410) {
        setRetryMessage("Search query expired — please start a new search.")
      } else if (resp.ok) {
        setRetryMessage("Search re-queued. Results will appear shortly.")
      } else {
        setRetryMessage("Retry failed. Please try again later.")
      }
    } catch {
      setRetryMessage("Retry failed. Please try again later.")
    } finally {
      setRetrying(false)
    }
  }

  return (
    <div className="flex gap-3 py-2">
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          isError ? "bg-destructive/10" : "bg-blue-500/10",
        )}
      >
        {isError ? (
          <AlertCircle className="h-4 w-4 text-destructive" />
        ) : (
          <Info className="h-4 w-4 text-blue-500" />
        )}
      </div>

      <Card
        className={cn(
          "max-w-[75%] border px-4 py-3 text-sm",
          isError
            ? "border-destructive/20 bg-destructive/5 text-destructive"
            : "border-blue-500/20 bg-blue-500/5 text-muted-foreground",
        )}
      >
        <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>

        {isError && !retryMessage && (
          <button
            type="button"
            onClick={handleRetry}
            disabled={retrying}
            className="mt-2 flex items-center gap-1 text-xs text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400"
          >
            <RefreshCw className={cn("h-3 w-3", retrying && "animate-spin")} />
            {retrying ? "Retrying…" : "Retry search"}
          </button>
        )}

        {retryMessage && (
          <p className="mt-2 text-xs text-muted-foreground">{retryMessage}</p>
        )}
      </Card>
    </div>
  )
}
```

- [ ] **Step 2: Write failing tests**

```typescript
// frontend/src/components/Chat/__tests__/BackgroundMessageCard.test.tsx
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { vi, describe, it, expect, beforeEach } from "vitest"
import { BackgroundMessageCard } from "../BackgroundMessageCard"

// Stub OpenAPI.TOKEN so apiFetch works without a real token
vi.mock("@/client", () => ({ OpenAPI: { TOKEN: "test-token" } }))

const infoMsg = {
  id: "m1", conversation_id: "conv-1", role: "background",
  content: "Found 3 papers on aspirin synthesis", tool_calls: null, created_at: null,
  metadata: { variant: "info" },
}
const errorMsg = {
  ...infoMsg,
  content: "Literature search failed. Please retry.",
  metadata: { variant: "error", retry_available: true },
}

describe("BackgroundMessageCard", () => {
  it("renders content for info variant", () => {
    render(<BackgroundMessageCard message={infoMsg} />)
    expect(screen.getByText("Found 3 papers on aspirin synthesis")).toBeInTheDocument()
  })

  it("does NOT show Retry button for info variant", () => {
    render(<BackgroundMessageCard message={infoMsg} />)
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument()
  })

  it("shows Retry button for error variant", () => {
    render(<BackgroundMessageCard message={errorMsg} />)
    expect(screen.getByRole("button", { name: /retry search/i })).toBeInTheDocument()
  })

  it("POSTs to retry-s2-search endpoint on retry click", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    vi.stubGlobal("fetch", fetchMock)

    render(<BackgroundMessageCard message={errorMsg} />)
    await userEvent.click(screen.getByRole("button", { name: /retry search/i }))

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/articles/conversations/conv-1/retry-s2-search",
      expect.objectContaining({ method: "POST" }),
    )
    await waitFor(() =>
      expect(screen.getByText(/queued|shortly/i)).toBeInTheDocument()
    )
  })

  it("shows 'expired' message on 410 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 410 }))

    render(<BackgroundMessageCard message={errorMsg} />)
    await userEvent.click(screen.getByRole("button", { name: /retry search/i }))

    await waitFor(() => expect(screen.getByText(/expired/i)).toBeInTheDocument())
    // Button disappears after message shown
    expect(screen.queryByRole("button", { name: /retry search/i })).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && bun run test:unit -- BackgroundMessageCard`
Expected: FAIL (component doesn't exist yet)

- [ ] **Step 4: Create the component** (Step 1 above)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && bun run test:unit -- BackgroundMessageCard`
Expected: 5 tests pass.

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd frontend && bun run build 2>&1 | grep -i error | head -10`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Chat/BackgroundMessageCard.tsx frontend/src/components/Chat/__tests__/BackgroundMessageCard.test.tsx
git commit -m "feat(frontend): add BackgroundMessageCard component with unit tests"
```

---

## Task 13: Frontend — `MessageBubble` background role + `ChatWindow` background_update

**Files:**
- Modify: `frontend/src/components/Chat/MessageBubble.tsx`
- Modify: `frontend/src/components/Chat/ChatWindow.tsx`
- Modify: `frontend/src/hooks/useConversationSSE.ts`

- [ ] **Step 1: Update `MessageBubble.tsx`** to render `BackgroundMessageCard` for `role === "background"`

Add import at the top of `MessageBubble.tsx`:
```typescript
import { BackgroundMessageCard } from "./BackgroundMessageCard"
```

At the very start of the `MessageBubble` function body (before `const isUser`), add:
```typescript
  if (message.role === "background") {
    return <BackgroundMessageCard message={message} />
  }
```

- [ ] **Step 2: Add `onBackgroundUpdate` and `onBackgroundError` callbacks to `useConversationSSE`**

In `frontend/src/hooks/useConversationSSE.ts`:

Add callbacks to the `UseConversationSSEOptions` interface:
```typescript
interface UseConversationSSEOptions {
  conversationId: string
  enabled?: boolean
  onMessage?: (msg: ChatMessagePublic) => void
  onToolCall?: (tc: ToolCallInfo) => void
  onHazards?: (chemicals: HazardChemical[]) => void
  onArticleDownloads?: (jobs: ArticleDownloadJob[]) => void
  onError?: (err: string) => void
  onBackgroundUpdate?: () => void
  onBackgroundError?: (detail: string, retryAvailable: boolean) => void
}
```

Add both to the destructured parameter list:
```typescript
export function useConversationSSE({
  conversationId,
  enabled = true,
  onMessage,
  onToolCall,
  onHazards,
  onArticleDownloads,
  onError,
  onBackgroundUpdate,
  onBackgroundError,
}: UseConversationSSEOptions) {
```

Update `callbacksRef`:
```typescript
  const callbacksRef = useRef({ onMessage, onToolCall, onHazards, onArticleDownloads, onError, onBackgroundUpdate, onBackgroundError })
  callbacksRef.current = { onMessage, onToolCall, onHazards, onArticleDownloads, onError, onBackgroundUpdate, onBackgroundError }
```

In the `switch (eventType)` block, add two cases after `article_downloads`:
```typescript
              case "background_update":
                callbacksRef.current.onBackgroundUpdate?.()
                break
              case "background_error": {
                const errData = parsedData as { detail: string; retry_available: boolean }
                callbacksRef.current.onBackgroundError?.(errData.detail, errData.retry_available)
                break
              }
```

- [ ] **Step 3: Update `ChatWindow.tsx`** to handle both `background_update` and `background_error`

`background_error` events are NOT stored in the DB — they are transient. Store them in local state and render them as error cards in the message list.

Add `backgroundErrors` state near the top of `ChatWindow`:
```typescript
  const [backgroundErrors, setBackgroundErrors] = useState<
    Array<{ id: string; detail: string; retryAvailable: boolean }>
  >([])
```

After the `handleArticleDownloads` callback definition in `ChatWindow.tsx`, add both handlers:
```typescript
  const handleBackgroundUpdate = useCallback(() => {
    // Re-enable SSE so the agent continuation stream is received
    setSseEnabled(true)
    queryClient.invalidateQueries({ queryKey: ["messages", conversationId] })
    scrollToBottom()
  }, [conversationId, queryClient, scrollToBottom])

  const handleBackgroundError = useCallback((detail: string, retryAvailable: boolean) => {
    setBackgroundErrors((prev) => [
      ...prev,
      { id: crypto.randomUUID(), detail, retryAvailable },
    ])
    scrollToBottom()
  }, [scrollToBottom])
```

In the JSX where messages are rendered, add background error cards after the message list and before the streaming bubble. Import `BackgroundMessageCard`:
```typescript
import { BackgroundMessageCard } from "./BackgroundMessageCard"
```

Render errors in the message list area:
```typescript
{backgroundErrors.map((err) => (
  <BackgroundMessageCard
    key={err.id}
    message={{
      id: err.id,
      role: "background",
      content: err.detail,
      tool_calls: null,
      metadata: { variant: "error", retry_available: err.retryAvailable },
      conversation_id: conversationId,
      created_at: new Date().toISOString(),
    }}
  />
))}
```

Pass both to `useConversationSSE`:
```typescript
  const { streamingState, streamingContent } = useConversationSSE({
    conversationId,
    enabled: sseEnabled,
    onMessage: handleSSEMessage,
    onToolCall: handleToolCall,
    onHazards: handleHazards,
    onArticleDownloads: handleArticleDownloads,
    onError: handleError,
    onBackgroundUpdate: handleBackgroundUpdate,
    onBackgroundError: handleBackgroundError,
  })
```

- [ ] **Step 4: Write failing tests**

```typescript
// frontend/src/components/Chat/__tests__/MessageBubble.test.tsx
import { render, screen } from "@testing-library/react"
import { vi, describe, it, expect } from "vitest"
import { MessageBubble } from "../MessageBubble"

vi.mock("../BackgroundMessageCard", () => ({
  BackgroundMessageCard: ({ message }: { message: { content: string } }) => (
    <div data-testid="background-card">{message.content}</div>
  ),
}))

const bgMsg = {
  id: "m1", conversation_id: "c1", role: "background",
  content: "Background update text", tool_calls: null, created_at: null,
  metadata: { variant: "info" },
}
const userMsg = { ...bgMsg, role: "user", content: "Hello", metadata: null }

describe("MessageBubble", () => {
  it("renders BackgroundMessageCard for role=background", () => {
    render(<MessageBubble message={bgMsg} />)
    expect(screen.getByTestId("background-card")).toBeInTheDocument()
    expect(screen.getByText("Background update text")).toBeInTheDocument()
  })

  it("does NOT render BackgroundMessageCard for regular role", () => {
    render(<MessageBubble message={userMsg} />)
    expect(screen.queryByTestId("background-card")).not.toBeInTheDocument()
  })
})
```

```typescript
// frontend/src/hooks/__tests__/useConversationSSE.test.ts
import { renderHook, act } from "@testing-library/react"
import { vi, describe, it, expect, beforeEach } from "vitest"
import { useConversationSSE } from "../useConversationSSE"

// The hook uses fetchEventSource from @microsoft/fetch-event-source — NOT native EventSource.
// Mock the module and capture the onmessage handler so we can fire synthetic events.
const mockFetchEventSource = vi.fn()
vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: mockFetchEventSource,
  EventStreamContentType: "text/event-stream",
}))

// Helper: fire a synthetic SSE event via the captured onmessage handler
function dispatchSSE(eventType: string, data: object) {
  // fetchEventSource is called with (url, options) — grab the last call's options
  const options = mockFetchEventSource.mock.calls.at(-1)?.[1] ?? {}
  options.onmessage?.({ event: eventType, data: JSON.stringify(data), id: "", retry: undefined })
}

describe("useConversationSSE", () => {
  beforeEach(() => {
    mockFetchEventSource.mockReset()
    // Default: fetchEventSource returns a never-resolving promise (keeps connection "open")
    mockFetchEventSource.mockReturnValue(new Promise(() => {}))
  })

  it("calls onBackgroundUpdate when background_update event fires", async () => {
    const onBackgroundUpdate = vi.fn()
    renderHook(() =>
      useConversationSSE({ conversationId: "c1", enabled: true, onBackgroundUpdate }),
    )
    // Wait for fetchEventSource to be called (it's called in a useEffect)
    await vi.waitFor(() => expect(mockFetchEventSource).toHaveBeenCalled())
    act(() => dispatchSSE("background_update", {}))
    expect(onBackgroundUpdate).toHaveBeenCalledOnce()
  })

  it("calls onBackgroundError with detail and retry_available", async () => {
    const onBackgroundError = vi.fn()
    renderHook(() =>
      useConversationSSE({ conversationId: "c1", enabled: true, onBackgroundError }),
    )
    await vi.waitFor(() => expect(mockFetchEventSource).toHaveBeenCalled())
    act(() =>
      dispatchSSE("background_error", { detail: "Search failed", retry_available: true }),
    )
    expect(onBackgroundError).toHaveBeenCalledWith("Search failed", true)
  })

  it("does NOT call fetchEventSource when enabled=false", () => {
    renderHook(() =>
      useConversationSSE({ conversationId: "c1", enabled: false }),
    )
    expect(mockFetchEventSource).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd frontend && bun run test:unit -- MessageBubble useConversationSSE`
Expected: FAIL (component changes not applied yet)

- [ ] **Step 6: Apply the MessageBubble + useConversationSSE + ChatWindow changes** (Steps 1–3 above)

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && bun run test:unit -- MessageBubble useConversationSSE`
Expected: 5 tests pass.

- [ ] **Step 8: Verify TypeScript compiles**

Run: `cd frontend && bun run build 2>&1 | grep -i error | head -20`
Expected: No TypeScript errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/Chat/MessageBubble.tsx frontend/src/hooks/useConversationSSE.ts frontend/src/components/Chat/ChatWindow.tsx frontend/src/components/Chat/__tests__/MessageBubble.test.tsx frontend/src/hooks/__tests__/useConversationSSE.test.ts
git commit -m "feat(frontend): render background messages as cards, handle background SSE events, with unit tests"
```

---

## Task 14: Frontend — `ArticleDownloadsCard` "Notify Agent" button

**Files:**
- Modify: `frontend/src/components/Chat/ArticleDownloadsCard.tsx`

- [ ] **Step 1: Add "Notify Agent" button logic**

The button shows when:
- All jobs have terminal parse status (completed or failed) AND fetcher is done for all
- At least one parse failed
- At least one parse succeeded

To know all parse statuses at the card level, add `useQueries` at the `ArticleDownloadsCard` level. React Query deduplication means the same `queryKey: ["parse-status", jobId]` is shared with `ParseIndicator` — no extra network calls.

Add `conversationId` prop and implement the full component. Update the component signature and call sites:

```typescript
interface ArticleDownloadsCardProps {
  jobs: ArticleDownloadJob[]
  conversationId: string
}

export function ArticleDownloadsCard({ jobs, conversationId }: ArticleDownloadsCardProps) {
  if (jobs.length === 0) return null
  return <ArticleDownloadsCardInner jobs={jobs} conversationId={conversationId} />
}
```

Full `ArticleDownloadsCardInner` (replace the existing `ArticleDownloadsCard` body):
```typescript
function ArticleDownloadsCardInner({ jobs, conversationId }: ArticleDownloadsCardProps) {
  const fetcherQueries = useQueries({
    queries: jobs.map((job) => ({
      queryKey: ["article-job", job.job_id] as const,
      queryFn: (): Promise<JobStatus> => apiFetch(`/api/v1/articles/jobs/${job.job_id}`),
      refetchInterval: (query: { state: { data?: JobStatus } }) => {
        const s = query.state.data?.status
        return s === "done" || s === "failed" ? false : 3000
      },
      staleTime: 0,
    })),
  })

  const doneJobIds = jobs
    .map((job, i) => ({ job, status: fetcherQueries[i]?.data?.status }))
    .filter((x) => x.status === "done")
    .map((x) => x.job.job_id)

  const parseQueries = useQueries({
    queries: doneJobIds.map((jobId) => ({
      queryKey: ["parse-status", jobId] as const,
      queryFn: (): Promise<ParseStatus> => apiFetch(`/api/v1/articles/jobs/${jobId}/parse-status`),
      refetchInterval: (query: { state: { data?: ParseStatus } }) => {
        const s = query.state.data?.status
        return s === "completed" || s === "failed" ? false : 3000
      },
      staleTime: 0,
    })),
  })

  const allFetchTerminal = fetcherQueries.every(
    (q) => q.data?.status === "done" || q.data?.status === "failed",
  )
  const allParseTerminal =
    doneJobIds.length === 0
      ? false
      : parseQueries.every(
          (q) => q.data?.status === "completed" || q.data?.status === "failed",
        )
  const anyParseFailed = parseQueries.some((q) => q.data?.status === "failed")
  const anyParseSucceeded = parseQueries.some((q) => q.data?.status === "completed")
  const showNotifyAgent = allFetchTerminal && allParseTerminal && anyParseFailed && anyParseSucceeded

  const [notified, setNotified] = useState(false)
  const notifyMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/api/v1/articles/conversations/${conversationId}/trigger-rag-continuation`, {
        method: "POST",
      }),
    onSuccess: () => setNotified(true),
  })

  return (
    <Card className="my-2 overflow-hidden border-muted bg-muted/30 p-0">
      <div className="border-b border-muted px-3 py-2">
        <span className="text-xs font-medium text-muted-foreground">Fetching PDFs…</span>
      </div>
      <div className="px-3 py-2">
        {jobs.map((job) => (
          <ArticleJobRow key={job.job_id} job={job} />
        ))}
      </div>
      {showNotifyAgent && (
        <div className="border-t border-muted px-3 py-2">
          {notified ? (
            <span className="text-xs text-muted-foreground">Agent notified.</span>
          ) : (
            <button
              type="button"
              onClick={() => notifyMutation.mutate()}
              disabled={notifyMutation.isPending}
              className="flex items-center gap-1 text-xs text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400"
            >
              <RefreshCw className={cn("h-3 w-3", notifyMutation.isPending && "animate-spin")} />
              {notifyMutation.isPending ? "Notifying…" : "Notify Agent"}
            </button>
          )}
        </div>
      )}
    </Card>
  )
}
```

Add required imports to the top of `ArticleDownloadsCard.tsx`:
```typescript
import { useState } from "react"
import { useQueries, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react"
import { cn } from "@/lib/utils"
```

- [ ] **Step 2: Update `ChatWindow.tsx`** to pass `conversationId` to `ArticleDownloadsCard`

Replace:
```typescript
            {articleDownloadBatches.map((batch, i) => (
              <ArticleDownloadsCard key={i} jobs={batch} />
            ))}
```
With:
```typescript
            {articleDownloadBatches.map((batch, i) => (
              <ArticleDownloadsCard key={i} jobs={batch} conversationId={conversationId} />
            ))}
```

- [ ] **Step 3: Write failing tests**

The tests mock `useQueries` to return controlled job statuses — no real HTTP requests needed.

```typescript
// frontend/src/components/Chat/__tests__/ArticleDownloadsCard.test.tsx
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { vi, describe, it, expect, beforeEach } from "vitest"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ArticleDownloadsCard } from "../ArticleDownloadsCard"

vi.mock("@/client", () => ({ OpenAPI: { TOKEN: "test-token" } }))

// Mock apiFetch used inside the component
const mockApiFetch = vi.fn()
vi.mock("../ArticleDownloadsCard", async (importOriginal) => {
  // We need the real module — override apiFetch inside it via fetch mock instead
  return importOriginal()
})

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const jobs = [
  { doi: "10.1/a", job_id: "job-1" },
  { doi: "10.1/b", job_id: "job-2" },
]

function mockFetchStatuses(fetcherStatus: string, parseStatus: string) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      if (url.includes("/parse-status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ job_id: "job-1", status: parseStatus }) })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ job_id: url.split("/").at(-1), status: fetcherStatus }) })
    }),
  )
}

describe("ArticleDownloadsCard — Notify Agent button", () => {
  beforeEach(() => vi.restoreAllMocks())

  it("shows Notify Agent when fetcher done, one parse failed, one parse succeeded", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("job-1/parse-status"))
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ job_id: "job-1", status: "completed" }) })
      if (url.includes("job-2/parse-status"))
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ job_id: "job-2", status: "failed" }) })
      // fetcher status
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ job_id: url.split("/").at(-1), status: "done" }) })
    })
    vi.stubGlobal("fetch", fetchMock)

    wrap(<ArticleDownloadsCard jobs={jobs} conversationId="conv-1" />)
    await waitFor(() => expect(screen.getByRole("button", { name: /notify agent/i })).toBeInTheDocument())
  })

  it("does NOT show Notify Agent when all parse succeeded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        const status = url.includes("parse-status") ? "completed" : "done"
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ status }) })
      }),
    )

    wrap(<ArticleDownloadsCard jobs={jobs} conversationId="conv-1" />)
    // Wait for queries to settle, then confirm no button
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.queryByRole("button", { name: /notify agent/i })).not.toBeInTheDocument()
  })

  it("calls trigger-rag-continuation endpoint when Notify Agent clicked", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("trigger-rag-continuation"))
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: "queued" }) })
      if (url.includes("job-1/parse-status"))
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ job_id: "job-1", status: "completed" }) })
      if (url.includes("job-2/parse-status"))
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ job_id: "job-2", status: "failed" }) })
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: "done" }) })
    })
    vi.stubGlobal("fetch", fetchMock)

    wrap(<ArticleDownloadsCard jobs={jobs} conversationId="conv-1" />)
    await waitFor(() => screen.getByRole("button", { name: /notify agent/i }))
    await userEvent.click(screen.getByRole("button", { name: /notify agent/i }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/articles/conversations/conv-1/trigger-rag-continuation",
        expect.objectContaining({ method: "POST" }),
      ),
    )
    expect(screen.getByText(/agent notified/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd frontend && bun run test:unit -- ArticleDownloadsCard`
Expected: FAIL

- [ ] **Step 5: Implement the component changes** (Steps 1–2 above)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && bun run test:unit -- ArticleDownloadsCard`
Expected: 3 tests pass.

- [ ] **Step 7: Verify TypeScript compiles**

Run: `cd frontend && bun run build 2>&1 | grep -i error | head -20`
Expected: No TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Chat/ArticleDownloadsCard.tsx frontend/src/components/Chat/ChatWindow.tsx frontend/src/components/Chat/__tests__/ArticleDownloadsCard.test.tsx
git commit -m "feat(frontend): add Notify Agent button to ArticleDownloadsCard, with unit tests"
```

---

## Task 15: Frontend — `ToolCallCard` retry unit tests (existing behavior)

**Files:**
- Create: `frontend/src/components/Chat/__tests__/ToolCallCard.test.tsx`

These tests document and lock in the CURRENT `ToolCallCard` retry behavior. The tests explicitly assert that the retry is UI-only (results shown in card, agent never notified). This prevents regressions and makes the limitation visible to future contributors.

Note: after the async pipeline is live, `literature_search` returns `"queued"` — not a 429 string — so `isRateLimited` is always false and this retry path will never fire. These tests remain as documentation of what the old path did.

- [ ] **Step 1: Write the tests**

```typescript
// frontend/src/components/Chat/__tests__/ToolCallCard.test.tsx
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { vi, describe, it, expect, beforeEach } from "vitest"
import { ToolCallCard } from "../ToolCallCard"

const rateLimitedCall = {
  name: "literature_search",
  args: { query: "aspirin synthesis", max_results: 5 },
  result: "Error 429: rate limited by Semantic Scholar",
  status: "completed" as const,
}

const normalCall = {
  name: "literature_search",
  args: { query: "aspirin synthesis" },
  result: "Found 5 papers: ...",
  status: "completed" as const,
}

describe("ToolCallCard — literature_search retry (existing UI-only path)", () => {
  beforeEach(() => vi.restoreAllMocks())

  it("shows Retry button when result contains '429'", () => {
    render(<ToolCallCard toolCall={rateLimitedCall} />)
    expect(screen.getByRole("button", { name: /retry search/i })).toBeInTheDocument()
  })

  it("does NOT show Retry button for normal results", () => {
    render(<ToolCallCard toolCall={normalCall} />)
    expect(screen.queryByRole("button", { name: /retry search/i })).not.toBeInTheDocument()
  })

  it("calls /api/v1/search/literature on retry click", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ papers: [], query: "aspirin synthesis" }),
    })
    vi.stubGlobal("fetch", fetchMock)
    // localStorage.getItem used for auth token
    vi.spyOn(Storage.prototype, "getItem").mockReturnValue("fake-token")

    render(<ToolCallCard toolCall={rateLimitedCall} />)
    await userEvent.click(screen.getByRole("button", { name: /retry search/i }))

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/search/literature",
      expect.objectContaining({ method: "POST" }),
    )
  })

  it("shows results in card but does NOT call any agent/continuation endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          papers: [
            { title: "Aspirin paper", authors: ["A. Smith"], abstract: "...", year: 2023, citation_count: 10, url: null, doi: "10.1/x" },
          ],
          query: "aspirin synthesis",
        }),
    })
    vi.stubGlobal("fetch", fetchMock)
    vi.spyOn(Storage.prototype, "getItem").mockReturnValue("fake-token")

    render(<ToolCallCard toolCall={rateLimitedCall} />)
    await userEvent.click(screen.getByRole("button", { name: /retry search/i }))

    await waitFor(() => expect(screen.getByText("Aspirin paper")).toBeInTheDocument())

    // Only one fetch call — search only, no continuation/agent endpoint
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url] = fetchMock.mock.calls[0]
    expect(url).not.toContain("continuation")
    expect(url).not.toContain("agent")
    expect(url).not.toContain("background")
  })

  it("retry results are shown in card — rerender loses them (ephemeral state)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ papers: [{ title: "Some Paper", authors: [], abstract: null, year: null, citation_count: null, url: null, doi: null }], query: "" }),
    })
    vi.stubGlobal("fetch", fetchMock)
    vi.spyOn(Storage.prototype, "getItem").mockReturnValue("fake-token")

    const { unmount } = render(<ToolCallCard toolCall={rateLimitedCall} />)
    await userEvent.click(screen.getByRole("button", { name: /retry search/i }))
    await waitFor(() => expect(screen.getByText("Some Paper")).toBeInTheDocument())

    // Simulate page refresh by unmounting and remounting
    unmount()
    render(<ToolCallCard toolCall={rateLimitedCall} />)
    expect(screen.queryByText("Some Paper")).not.toBeInTheDocument()
    // Retry button is back
    expect(screen.getByRole("button", { name: /retry search/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd frontend && bun run test:unit -- ToolCallCard`
Expected: 5 tests pass. (No code changes needed — testing existing behavior.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Chat/__tests__/ToolCallCard.test.tsx
git commit -m "test(frontend): add ToolCallCard retry unit tests — documents UI-only behavior"
```

---

## Task 16: Update CLAUDE.md files

**Files:**
- Modify: `CLAUDE.md`
- Modify: `backend/CLAUDE.md`
- Modify: `services/ai-agent/CLAUDE.md`

- [ ] **Step 1: Update `CLAUDE.md`** — add Async Tool Pipeline section to the Architecture block and Celery queues note

After the `## Architecture` section, add:
```markdown
## Async Tool Pipeline

`literature_search` returns immediately; S2 search runs in background via Celery:
1. Tool POSTs to `backend /internal/queue-background-tool`
2. `run_s2_search` Celery task calls `ai-agent /internal/s2-search` (blocking ≤15s)
3. Results saved as `role="background"` DB message → `run_agent_continuation` dispatched
4. `monitor_ingestion` polls article-fetcher + pdf-parser every 10s (max 20 min)
5. When all parsed → `run_agent_continuation` dispatched again for RAG analysis

Per-conversation streaming lock: `conv_processing:{id}` (Redis SET NX EX 600).
Queued continuations: `conv_pending:{id}` (Redis list).
```

- [ ] **Step 2: Update `backend/CLAUDE.md`** — add new files to project structure

Add to the `app/worker/tasks/` section:
```
│   ├── tasks/
│   │   ├── chat.py         — process_chat_message (acquires conv_processing lock)
│   │   └── continuation.py — run_s2_search, monitor_ingestion, run_agent_continuation
```

Add to the Conventions section:
```markdown
**Background pipeline tasks** (`continuation.py`):
- `run_s2_search` — calls ai-agent `/internal/s2-search`, saves S2 results background message
- `monitor_ingestion` — polls article-fetcher + pdf-parser until done, saves ingestion background message
- `run_agent_continuation` — re-invokes agent with fresh history, acquires `conv_processing` lock

Internal endpoint (`/internal/*`) is mounted directly on the FastAPI `app` (not under `/api/v1`).
No auth middleware — Docker-network only. Verify nginx/compose does not expose port 8000 to internet.
```

- [ ] **Step 3: Update `services/ai-agent/CLAUDE.md`** — document new endpoints

In the `## Chat Endpoints` section, add:
```markdown
- `POST /internal/s2-search` — blocking Semantic Scholar search called by backend Celery worker. No auth. Returns `{"papers": [...], "query": str}`
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md backend/CLAUDE.md services/ai-agent/CLAUDE.md
git commit -m "docs: update CLAUDE.md files for async tool pipeline"
```

---

## Verification Checklist

After all tasks complete, manually verify end-to-end:

- [ ] Send a literature query in chat
- [ ] Verify initial assistant response arrives within ~5s (no 125s wait)
- [ ] Verify background card (blue info) appears ~15s later with S2 results
- [ ] Verify second assistant response appears streaming (abstract analysis)
- [ ] Wait for articles to parse (~2-5 min)
- [ ] Verify "New Papers Available" background card appears
- [ ] Verify third assistant response appears with RAG-based analysis
- [ ] Block S2 endpoint → verify error SSE event reaches frontend while SSE is connected
- [ ] Verify existing chat flow (no literature query) still works end-to-end
- [ ] Verify `GET /api/v1/conversations/{id}` still loads with background messages shown as info cards
