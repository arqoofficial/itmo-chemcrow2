# Article Fetcher Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-implemented `article-fetcher` service into ChemCrow2 so that DOIs from literature searches are automatically downloaded, shown as inline status cards in chat, and fed back into the AI agent's context on each new message.

**Architecture:** The backend Celery chat task intercepts `tool_end` events from `literature_search`, submits DOIs to the article-fetcher via HTTP, stores job associations in Redis, and publishes an `article_downloads` SSE event. The frontend receives this event and renders live-updating download status cards. On every subsequent user message, the Celery task prepends a `user`-role status block to the AI agent's message payload.

**Tech Stack:** FastAPI, httpx, Redis (sync client in Celery, `get_sync_redis()`), pytest + unittest.mock, React 19, TanStack Query v5, `@microsoft/fetch-event-source`, Lucide icons, Radix/shadcn Card.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `backend/app/core/config.py` | Modify | Add `ARTICLE_FETCHER_URL` setting |
| `compose.yml` | Modify | Add `ARTICLE_FETCHER_URL` to celery-worker env |
| `services/article-fetcher/app/config.py` | Modify | Add `ARTICLE_PROCESSOR_WEBHOOK_URL` setting |
| `services/article-fetcher/app/main.py` | Modify | Fire webhook after job → done |
| `services/article-fetcher/tests/test_main.py` | Modify | Tests for webhook behaviour |
| `backend/app/worker/tasks/chat.py` | Modify | DOI extraction, fetcher submission, Redis storage, context injection |
| `backend/tests/worker/__init__.py` | Create | Package init |
| `backend/tests/worker/test_chat_article_helpers.py` | Create | Unit tests for new helper functions |
| `backend/app/api/routes/articles.py` | Create | Proxy `GET /api/v1/articles/jobs/{job_id}` |
| `backend/tests/api/routes/test_articles.py` | Create | Tests for the proxy route |
| `backend/app/api/main.py` | Modify | Register articles router |
| `frontend/src/client/chatTypes.ts` | Modify | Add `ArticleDownloadJob` type + `article_downloads` SSE event |
| `frontend/src/hooks/useConversationSSE.ts` | Modify | Handle `article_downloads` event |
| `frontend/src/components/Chat/ArticleDownloadsCard.tsx` | Create | Inline download status card with polling |
| `frontend/src/components/Chat/ChatWindow.tsx` | Modify | Add article download batches state + render cards |

---

## Task 1: Backend config + compose

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `compose.yml`

- [ ] **Step 1: Add `ARTICLE_FETCHER_URL` to backend config**

In `backend/app/core/config.py`, add after `RETROSYNTHESIS_URL`:
```python
ARTICLE_FETCHER_URL: str = "http://article-fetcher:8200"
```

- [ ] **Step 2: Add env var to celery-worker in compose.yml**

In `compose.yml`, in the `celery-worker` → `environment` block (after `AI_AGENT_URL`):
```yaml
      - ARTICLE_FETCHER_URL=http://article-fetcher:8200
```

- [ ] **Step 3: Commit**
```bash
git add backend/app/core/config.py compose.yml
git commit -m "feat: add ARTICLE_FETCHER_URL config"
```

---

## Task 2: Article-fetcher webhook on job completion

**Files:**
- Modify: `services/article-fetcher/app/config.py`
- Modify: `services/article-fetcher/app/main.py`
- Modify: `services/article-fetcher/tests/test_main.py`

Run all article-fetcher tests with:
```bash
cd services/article-fetcher && uv run pytest tests/ -v
```

- [ ] **Step 1: Write failing tests for webhook behaviour**

Add to `services/article-fetcher/tests/test_main.py`:
```python
from unittest.mock import patch, MagicMock


def test_run_fetch_fires_webhook_on_done(mock_redis, mock_s3):
    """When ARTICLE_PROCESSOR_WEBHOOK_URL is set, it is POSTed on job done."""
    mock_redis.get.return_value = '{"job_id":"j1","doi":"10.1/x","status":"running","object_key":null,"error":null,"created_at":"2026-01-01T00:00:00Z"}'
    mock_redis.set.return_value = True

    with (
        patch("app.main.redis_client", mock_redis),
        patch("app.main.storage", mock_s3),
        patch("app.main.fetch_article", return_value=b"%PDF"),
        patch("app.main.settings") as mock_settings,
        patch("app.main.requests") as mock_requests,
    ):
        mock_settings.article_processor_webhook_url = "http://processor/ingest"
        mock_s3.upload_pdf.return_value = None
        mock_s3.presign_url.return_value = "http://minio/j1.pdf"

        from app.main import _run_fetch
        _run_fetch("j1", "10.1/x")

        mock_requests.post.assert_called_once()
        call_kwargs = mock_requests.post.call_args
        assert call_kwargs[0][0] == "http://processor/ingest"


def test_run_fetch_skips_webhook_when_url_empty(mock_redis, mock_s3):
    """When ARTICLE_PROCESSOR_WEBHOOK_URL is empty, no POST is made."""
    mock_redis.get.return_value = '{"job_id":"j2","doi":"10.1/y","status":"running","object_key":null,"error":null,"created_at":"2026-01-01T00:00:00Z"}'
    mock_redis.set.return_value = True

    with (
        patch("app.main.redis_client", mock_redis),
        patch("app.main.storage", mock_s3),
        patch("app.main.fetch_article", return_value=b"%PDF"),
        patch("app.main.settings") as mock_settings,
        patch("app.main.requests") as mock_requests,
    ):
        mock_settings.article_processor_webhook_url = ""
        mock_s3.upload_pdf.return_value = None

        from app.main import _run_fetch
        _run_fetch("j2", "10.1/y")

        mock_requests.post.assert_not_called()


def test_run_fetch_webhook_failure_does_not_raise(mock_redis, mock_s3):
    """A webhook POST failure must not propagate — job remains done."""
    mock_redis.get.return_value = '{"job_id":"j3","doi":"10.1/z","status":"running","object_key":null,"error":null,"created_at":"2026-01-01T00:00:00Z"}'
    mock_redis.set.return_value = True

    with (
        patch("app.main.redis_client", mock_redis),
        patch("app.main.storage", mock_s3),
        patch("app.main.fetch_article", return_value=b"%PDF"),
        patch("app.main.settings") as mock_settings,
        patch("app.main.requests") as mock_requests,
    ):
        mock_settings.article_processor_webhook_url = "http://processor/ingest"
        mock_s3.upload_pdf.return_value = None
        mock_requests.post.side_effect = Exception("connection refused")

        from app.main import _run_fetch
        _run_fetch("j3", "10.1/z")  # must not raise

        # Job should still be marked done
        set_calls = mock_redis.set.call_args_list
        last_job = json.loads(set_calls[-1][0][1])
        assert last_job["status"] == "done"
```

- [ ] **Step 2: Run tests — expect failures**
```bash
cd services/article-fetcher && uv run pytest tests/test_main.py -v -k "webhook"
```
Expected: FAIL — `requests` not imported yet, `article_processor_webhook_url` not in config.

- [ ] **Step 3: Add `ARTICLE_PROCESSOR_WEBHOOK_URL` to config**

In `services/article-fetcher/app/config.py`:
```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://redis:6379/0"
    minio_endpoint: str = "articles-minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "articles"
    minio_public_endpoint: str = "http://localhost:9092"
    article_processor_webhook_url: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
```

- [ ] **Step 4: Add webhook call to `_run_fetch` in `services/article-fetcher/app/main.py`**

Add `import requests` at the top of the file (after existing imports). Then update `_run_fetch`:
```python
def _run_fetch(job_id: str, doi: str) -> None:
    _update_job(job_id, status="running")
    try:
        pdf_bytes = fetch_article(doi)
        object_key = f"{job_id}.pdf"
        storage.upload_pdf(object_key, pdf_bytes)
        _update_job(job_id, status="done", object_key=object_key)
        logger.info("Job %s completed for DOI %s", job_id, doi)
        if settings.article_processor_webhook_url:
            try:
                requests.post(
                    settings.article_processor_webhook_url,
                    json={"job_id": job_id, "doi": doi, "object_key": object_key, "status": "done"},
                    timeout=5,
                )
                logger.info("Webhook fired for job %s", job_id)
            except Exception:
                logger.warning("Webhook POST failed for job %s", job_id, exc_info=True)
    except FetchError as e:
        _update_job(job_id, status="failed", error=str(e))
        logger.warning("Job %s failed for DOI %s: %s", job_id, doi, e)
    except Exception as e:
        _update_job(job_id, status="failed", error=str(e))
        logger.exception("Unexpected error in job %s", job_id)
```

- [ ] **Step 5: Run tests — expect pass**
```bash
cd services/article-fetcher && uv run pytest tests/ -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**
```bash
git add services/article-fetcher/app/config.py services/article-fetcher/app/main.py services/article-fetcher/tests/test_main.py
git commit -m "feat(article-fetcher): add article processor webhook on job done"
```

---

## Task 3: Backend articles proxy route

**Files:**
- Create: `backend/app/api/routes/articles.py`
- Create: `backend/tests/api/routes/test_articles.py`
- Create: `backend/tests/worker/__init__.py`
- Modify: `backend/app/api/main.py`

Backend tests require a running DB. Use pytest with the existing conftest (which seeds the DB). Run with:
```bash
cd backend && uv run pytest tests/api/routes/test_articles.py -v
```

- [ ] **Step 1: Write failing tests for the proxy route**

Create `backend/tests/api/routes/test_articles.py`:
```python
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from tests.utils.utils import get_superuser_token_headers


def test_get_article_job_proxies_to_fetcher(client: TestClient, superuser_token_headers: dict):
    job_payload = {
        "job_id": "abc-123",
        "status": "done",
        "url": "http://localhost:9092/articles/abc-123.pdf?sig=x",
        "error": None,
    }
    with patch("app.api.routes.articles.httpx.AsyncClient") as mock_client_cls:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = job_payload
        mock_client_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        resp = client.get("/api/v1/articles/jobs/abc-123", headers=superuser_token_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "abc-123"
    assert data["status"] == "done"
    assert "abc-123.pdf" in data["url"]


def test_get_article_job_returns_404_when_not_found(client: TestClient, superuser_token_headers: dict):
    with patch("app.api.routes.articles.httpx.AsyncClient") as mock_client_cls:
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_client_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        resp = client.get("/api/v1/articles/jobs/nonexistent", headers=superuser_token_headers)

    assert resp.status_code == 404


def test_get_article_job_requires_auth(client: TestClient):
    resp = client.get("/api/v1/articles/jobs/abc-123")
    assert resp.status_code == 401
```

Add `superuser_token_headers` fixture to `backend/tests/conftest.py` if not already present. Check `tests/utils/utils.py` — it likely has `get_superuser_token_headers`. Add to conftest:
```python
@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)
```

- [ ] **Step 2: Run tests — expect failures**
```bash
cd backend && uv run pytest tests/api/routes/test_articles.py -v
```
Expected: FAIL — route doesn't exist yet.

- [ ] **Step 3: Create `backend/app/api/routes/articles.py`**
```python
"""Article jobs proxy — forwards job status requests to the article-fetcher service."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core.config import settings

router = APIRouter(prefix="/articles", tags=["articles"])


class ArticleJobResponse(BaseModel):
    job_id: str
    status: str
    url: str | None = None
    error: str | None = None


@router.get("/jobs/{job_id}", response_model=ArticleJobResponse)
async def get_article_job(
    job_id: str,
    current_user: CurrentUser,  # noqa: ARG001 — auth guard
) -> ArticleJobResponse:
    """Proxy job status from the article-fetcher service."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{settings.ARTICLE_FETCHER_URL}/jobs/{job_id}")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Article fetcher unreachable: {exc}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Job not found")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Article fetcher error")

    return ArticleJobResponse(**resp.json())
```

- [ ] **Step 4: Register the router in `backend/app/api/main.py`**

Add import and `include_router` call:
```python
from app.api.routes import (
    articles,
    conversations,
    events,
    items,
    login,
    private,
    retrosynthesis,
    tasks,
    users,
    utils,
)
# ...
api_router.include_router(articles.router)
```

- [ ] **Step 5: Create `backend/tests/worker/__init__.py`** (empty file — needed for next task)
```bash
touch backend/tests/worker/__init__.py
```

- [ ] **Step 6: Run tests — expect pass**
```bash
cd backend && uv run pytest tests/api/routes/test_articles.py -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**
```bash
git add backend/app/api/routes/articles.py backend/app/api/main.py backend/tests/api/routes/test_articles.py backend/tests/worker/__init__.py
git commit -m "feat(backend): add articles job proxy route"
```

---

## Task 4: Chat task — DOI extraction and fetch submission

Extract three pure helper functions from `chat.py` logic so they can be tested independently, then integrate them into `_process_streaming`.

**Files:**
- Modify: `backend/app/worker/tasks/chat.py`
- Create: `backend/tests/worker/test_chat_article_helpers.py`

- [ ] **Step 1: Write failing unit tests for the helpers**

Create `backend/tests/worker/test_chat_article_helpers.py`:
```python
"""Unit tests for article helper functions in the chat Celery task."""
import json
from unittest.mock import MagicMock, patch

import pytest


# ── _extract_dois ────────────────────────────────────────────────────────────

def test_extract_dois_finds_dois_in_tool_output():
    from app.worker.tasks.chat import _extract_dois

    output = (
        "- **Paper One** (2023)\n"
        "  DOI: 10.1038/s41586-021-03819-2\n"
        "- **Paper Two** (2022)\n"
        "  DOI: 10.1021/acs.nanolett.1c02548\n"
    )
    result = _extract_dois(output)
    assert result == ["10.1038/s41586-021-03819-2", "10.1021/acs.nanolett.1c02548"]


def test_extract_dois_skips_na():
    from app.worker.tasks.chat import _extract_dois

    output = "  DOI: N/A\n  DOI: 10.1234/test\n"
    result = _extract_dois(output)
    assert result == ["10.1234/test"]


def test_extract_dois_returns_empty_when_none():
    from app.worker.tasks.chat import _extract_dois

    result = _extract_dois("No DOIs here at all.")
    assert result == []


def test_extract_dois_deduplicates():
    from app.worker.tasks.chat import _extract_dois

    output = "  DOI: 10.1/a\n  DOI: 10.1/a\n"
    result = _extract_dois(output)
    assert result == ["10.1/a"]


# ── _get_conversation_article_jobs ──────────────────────────────────────────

def test_get_conversation_article_jobs_returns_parsed_list():
    from app.worker.tasks.chat import _get_conversation_article_jobs

    r = MagicMock()
    r.lrange.return_value = [
        json.dumps({"doi": "10.1/a", "job_id": "uuid-1"}),
        json.dumps({"doi": "10.1/b", "job_id": "uuid-2"}),
    ]
    result = _get_conversation_article_jobs(r, "conv-123")
    assert result == [
        {"doi": "10.1/a", "job_id": "uuid-1"},
        {"doi": "10.1/b", "job_id": "uuid-2"},
    ]
    r.lrange.assert_called_once_with("conversation:conv-123:article_jobs", 0, -1)


def test_get_conversation_article_jobs_returns_empty_when_key_absent():
    from app.worker.tasks.chat import _get_conversation_article_jobs

    r = MagicMock()
    r.lrange.return_value = []
    result = _get_conversation_article_jobs(r, "conv-empty")
    assert result == []


# ── _build_article_status_block ─────────────────────────────────────────────

def test_build_article_status_block_formats_statuses():
    from app.worker.tasks.chat import _build_article_status_block

    jobs = [
        {"doi": "10.1/a", "status": "done"},
        {"doi": "10.1/b", "status": "running"},
        {"doi": "10.1/c", "status": "failed"},
        {"doi": "10.1/d", "status": "pending"},
    ]
    block = _build_article_status_block(jobs)
    assert "[Article Download Status]" in block
    assert "10.1/a: available" in block
    assert "10.1/b: downloading" in block
    assert "10.1/c: failed" in block
    assert "10.1/d: downloading" in block


def test_build_article_status_block_returns_empty_for_no_jobs():
    from app.worker.tasks.chat import _build_article_status_block

    assert _build_article_status_block([]) == ""
```

- [ ] **Step 2: Run tests — expect failures**
```bash
cd backend && uv run pytest tests/worker/test_chat_article_helpers.py -v
```
Expected: FAIL — helpers not defined yet.

- [ ] **Step 3: Add helper functions to `backend/app/worker/tasks/chat.py`**

Add these imports at the top (alongside existing ones):
```python
import re
```

Add helper functions before `_process_streaming`:
```python
def _extract_dois(tool_output: str) -> list[str]:
    """Extract unique, non-N/A DOIs from a literature_search tool output string."""
    seen: set[str] = set()
    result: list[str] = []
    for match in re.finditer(r"DOI:\s*(\S+)", tool_output):
        doi = match.group(1)
        if doi != "N/A" and doi not in seen:
            seen.add(doi)
            result.append(doi)
    return result


def _get_conversation_article_jobs(r: redis_lib.Redis, conversation_id: str) -> list[dict]:
    """Return all stored {doi, job_id} pairs for a conversation from Redis."""
    raw = r.lrange(f"conversation:{conversation_id}:article_jobs", 0, -1)
    return [json.loads(item) for item in raw]


def _build_article_status_block(jobs: list[dict]) -> str:
    """Format a status summary string for injection into the AI agent context."""
    if not jobs:
        return ""
    label_map = {"done": "available", "failed": "failed"}
    lines = ["[Article Download Status]"]
    for job in jobs:
        label = label_map.get(job.get("status", ""), "downloading")
        lines.append(f"- {job['doi']}: {label}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests — expect pass**
```bash
cd backend && uv run pytest tests/worker/test_chat_article_helpers.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/app/worker/tasks/chat.py backend/tests/worker/test_chat_article_helpers.py
git commit -m "feat(backend): add DOI extraction and article status helper functions"
```

---

## Task 5: Chat task — fetch submission + Redis storage + SSE event

Integrate the helper functions into `_process_streaming`: submit DOIs to article-fetcher, store in Redis, publish `article_downloads` SSE event.

**Files:**
- Modify: `backend/app/worker/tasks/chat.py`
- Modify: `backend/tests/worker/test_chat_article_helpers.py`

- [ ] **Step 1: Write failing tests for fetch submission**

Add to `backend/tests/worker/test_chat_article_helpers.py`:
```python
# ── _submit_article_jobs ─────────────────────────────────────────────────────

def test_submit_article_jobs_skips_already_stored_dois():
    from app.worker.tasks.chat import _submit_article_jobs

    r = MagicMock()
    # One DOI already stored
    r.lrange.return_value = [json.dumps({"doi": "10.1/existing", "job_id": "old-uuid"})]

    with patch("app.worker.tasks.chat.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = _submit_article_jobs(r, "conv-1", ["10.1/existing", "10.1/new"])

        # Only "10.1/new" should be POSTed
        assert mock_client.post.call_count == 1
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["doi"] == "10.1/new"


def test_submit_article_jobs_stores_new_jobs_in_redis():
    from app.worker.tasks.chat import _submit_article_jobs

    r = MagicMock()
    r.lrange.return_value = []  # nothing stored yet

    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.json.return_value = {"job_id": "new-uuid", "status": "pending"}

    with patch("app.worker.tasks.chat.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = _submit_article_jobs(r, "conv-1", ["10.1/a"])

    assert result == [{"doi": "10.1/a", "job_id": "new-uuid"}]
    r.rpush.assert_called_once()
    stored = json.loads(r.rpush.call_args[0][1])
    assert stored == {"doi": "10.1/a", "job_id": "new-uuid"}
    r.expire.assert_called_once_with("conversation:conv-1:article_jobs", 7 * 24 * 3600)


def test_submit_article_jobs_handles_http_error_gracefully():
    from app.worker.tasks.chat import _submit_article_jobs

    r = MagicMock()
    r.lrange.return_value = []

    with patch("app.worker.tasks.chat.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("connection refused")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = _submit_article_jobs(r, "conv-1", ["10.1/a"])

    assert result == []  # failed gracefully, no jobs returned
    r.rpush.assert_not_called()
```

- [ ] **Step 2: Run tests — expect failures**
```bash
cd backend && uv run pytest tests/worker/test_chat_article_helpers.py -v -k "submit"
```
Expected: FAIL — `_submit_article_jobs` not defined.

- [ ] **Step 3: Add `_submit_article_jobs` to `chat.py`**

Add after the other helpers:
```python
def _submit_article_jobs(
    r: redis_lib.Redis,
    conversation_id: str,
    dois: list[str],
) -> list[dict]:
    """Submit new DOIs to article-fetcher, deduplicate against stored jobs, return new {doi, job_id} pairs."""
    existing = _get_conversation_article_jobs(r, conversation_id)
    existing_dois = {job["doi"] for job in existing}
    new_dois = [d for d in dois if d not in existing_dois]

    results: list[dict] = []
    redis_key = f"conversation:{conversation_id}:article_jobs"

    for doi in new_dois:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{settings.ARTICLE_FETCHER_URL}/fetch",
                    json={"doi": doi},
                )
            if resp.status_code != 202:
                logger.warning("article-fetcher returned %d for DOI %s", resp.status_code, doi)
                continue
            job_id = resp.json()["job_id"]
            entry = {"doi": doi, "job_id": job_id}
            r.rpush(redis_key, json.dumps(entry))
            r.expire(redis_key, 7 * 24 * 3600)
            results.append(entry)
            logger.info("Queued article fetch job %s for DOI %s", job_id, doi)
        except Exception:
            logger.warning("Failed to submit article fetch for DOI %s", doi, exc_info=True)

    return results
```

Also add `import httpx` to the imports at the top of `chat.py` (it is already there — verify).

- [ ] **Step 4: Run tests — expect pass**
```bash
cd backend && uv run pytest tests/worker/test_chat_article_helpers.py -v
```
Expected: all PASS.

- [ ] **Step 5: Integrate into `_process_streaming`**

In `_process_streaming`, update the `tool_end` branch to submit DOIs and publish the SSE event:

```python
elif event_type == "tool_end":
    tool_name = data.get("tool", "")
    tool_output = data.get("output", "")
    _publish(r, conversation_id, {
        "event": "tool_end",
        "tool": tool_name,
        "output": tool_output,
    })
    if tool_name == "literature_search":
        dois = _extract_dois(tool_output)
        if dois:
            new_jobs = _submit_article_jobs(r, conversation_id, dois)
            if new_jobs:
                _publish(r, conversation_id, {
                    "event": "article_downloads",
                    "jobs": new_jobs,
                })
```

- [ ] **Step 6: Commit**
```bash
git add backend/app/worker/tasks/chat.py backend/tests/worker/test_chat_article_helpers.py
git commit -m "feat(backend): submit DOI fetch jobs and publish article_downloads SSE event"
```

---

## Task 6: Chat task — agent context injection

On every new user message, read article job statuses and prepend a context block.

**Files:**
- Modify: `backend/app/worker/tasks/chat.py`
- Modify: `backend/tests/worker/test_chat_article_helpers.py`

- [ ] **Step 1: Write failing test for context injection**

Add to `backend/tests/worker/test_chat_article_helpers.py`:
```python
# ── _fetch_article_statuses ──────────────────────────────────────────────────

def test_fetch_article_statuses_returns_jobs_with_status():
    from app.worker.tasks.chat import _fetch_article_statuses

    stored_jobs = [
        {"doi": "10.1/a", "job_id": "uuid-1"},
        {"doi": "10.1/b", "job_id": "uuid-2"},
    ]
    responses = [
        {"job_id": "uuid-1", "status": "done", "url": "http://minio/uuid-1.pdf", "error": None},
        {"job_id": "uuid-2", "status": "running", "url": None, "error": None},
    ]

    with patch("app.worker.tasks.chat.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_get = MagicMock()
        mock_get.side_effect = [
            MagicMock(status_code=200, json=MagicMock(return_value=responses[0])),
            MagicMock(status_code=200, json=MagicMock(return_value=responses[1])),
        ]
        mock_client.get = mock_get
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = _fetch_article_statuses(stored_jobs)

    assert result == [
        {"doi": "10.1/a", "status": "done"},
        {"doi": "10.1/b", "status": "running"},
    ]


def test_fetch_article_statuses_skips_failed_requests():
    from app.worker.tasks.chat import _fetch_article_statuses

    stored_jobs = [{"doi": "10.1/a", "job_id": "uuid-1"}]

    with patch("app.worker.tasks.chat.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("timeout")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = _fetch_article_statuses(stored_jobs)

    assert result == []  # failed requests are skipped
```

- [ ] **Step 2: Run tests — expect failures**
```bash
cd backend && uv run pytest tests/worker/test_chat_article_helpers.py -v -k "statuses"
```
Expected: FAIL.

- [ ] **Step 3: Add `_fetch_article_statuses` to `chat.py`**

```python
def _fetch_article_statuses(stored_jobs: list[dict]) -> list[dict]:
    """Query article-fetcher for current status of each stored job. Skips on error."""
    results: list[dict] = []
    for job in stored_jobs:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{settings.ARTICLE_FETCHER_URL}/jobs/{job['job_id']}")
            if resp.status_code == 200:
                results.append({"doi": job["doi"], "status": resp.json()["status"]})
            else:
                logger.warning("article-fetcher returned %d for job %s", resp.status_code, job["job_id"])
        except Exception:
            logger.warning("Failed to fetch status for job %s", job.get("job_id"), exc_info=True)
    return results
```

- [ ] **Step 4: Run tests — expect pass**
```bash
cd backend && uv run pytest tests/worker/test_chat_article_helpers.py -v
```
Expected: all PASS.

- [ ] **Step 5: Integrate context injection into `process_chat_message`**

In `process_chat_message`, after loading `messages_payload` and before calling `_process_streaming`, add:

```python
        # Inject article download status context
        stored_jobs = _get_conversation_article_jobs(r, conversation_id)
        if stored_jobs:
            statuses = _fetch_article_statuses(stored_jobs)
            status_block = _build_article_status_block(statuses)
            if status_block:
                messages_payload = [{"role": "user", "content": status_block}] + messages_payload
```

- [ ] **Step 6: Run all chat helper tests**
```bash
cd backend && uv run pytest tests/worker/ -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**
```bash
git add backend/app/worker/tasks/chat.py backend/tests/worker/test_chat_article_helpers.py
git commit -m "feat(backend): inject article download status into AI agent context"
```

---

## Task 7: Frontend types + SSE hook

**Files:**
- Modify: `frontend/src/client/chatTypes.ts`
- Modify: `frontend/src/hooks/useConversationSSE.ts`

No automated tests for these (type-checked by TypeScript). Verify with:
```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 1: Add `ArticleDownloadJob` type and SSE event to `chatTypes.ts`**

Add after `HazardChemical`:
```ts
export type ArticleDownloadJob = {
  doi: string
  job_id: string
}
```

Add to the `SSEEvent` union:
```ts
| { event: "article_downloads"; data: { jobs: ArticleDownloadJob[] } }
```

- [ ] **Step 2: Update `useConversationSSE.ts`**

Add `ArticleDownloadJob` to the import:
```ts
import type { ArticleDownloadJob, ChatMessagePublic, HazardChemical, ToolCallInfo } from "@/client/chatTypes"
```

Add to `UseConversationSSEOptions`:
```ts
onArticleDownloads?: (jobs: ArticleDownloadJob[]) => void
```

Add to the destructured options in the function signature and update `callbacksRef`:
```ts
const callbacksRef = useRef({ onMessage, onToolCall, onHazards, onError, onArticleDownloads })
callbacksRef.current = { onMessage, onToolCall, onHazards, onError, onArticleDownloads }
```

Add case to the `switch` in `onmessage`:
```ts
case "article_downloads":
  callbacksRef.current.onArticleDownloads?.(
    (data as { jobs: ArticleDownloadJob[] }).jobs ?? [],
  )
  break
```

- [ ] **Step 3: Type-check**
```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Commit**
```bash
git add frontend/src/client/chatTypes.ts frontend/src/hooks/useConversationSSE.ts
git commit -m "feat(frontend): add ArticleDownloadJob type and article_downloads SSE event"
```

---

## Task 8: `ArticleDownloadsCard` component

**Files:**
- Create: `frontend/src/components/Chat/ArticleDownloadsCard.tsx`

- [ ] **Step 1: Create the component**

```tsx
import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, Loader2, XCircle } from "lucide-react"

import { Card } from "@/components/ui/card"
import type { ArticleDownloadJob } from "@/client/chatTypes"

interface JobStatus {
  job_id: string
  status: string
  url: string | null
  error: string | null
}

function ArticleJobRow({ job }: { job: ArticleDownloadJob }) {
  const { data } = useQuery<JobStatus>({
    queryKey: ["article-job", job.job_id],
    queryFn: async () => {
      const resp = await fetch(`/api/v1/articles/jobs/${job.job_id}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("access_token") ?? ""}` },
      })
      if (!resp.ok) throw new Error("fetch failed")
      return resp.json()
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === "done" || status === "failed") return false
      return 3000
    },
    staleTime: 0,
  })

  const status = data?.status ?? "pending"
  const truncatedDoi = job.doi.length > 40 ? `${job.doi.slice(0, 40)}…` : job.doi

  const icon =
    status === "done" ? (
      <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
    ) : status === "failed" ? (
      <XCircle className="h-3.5 w-3.5 shrink-0 text-destructive" />
    ) : (
      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500" />
    )

  return (
    <div className="flex items-center gap-2 py-1 text-xs">
      {icon}
      {status === "done" && data?.url ? (
        <a
          href={data.url}
          target="_blank"
          rel="noopener noreferrer"
          className="truncate text-blue-600 hover:underline dark:text-blue-400"
          title={job.doi}
        >
          {truncatedDoi}
        </a>
      ) : (
        <span className="truncate text-muted-foreground" title={job.doi}>
          {truncatedDoi}
        </span>
      )}
    </div>
  )
}

interface ArticleDownloadsCardProps {
  jobs: ArticleDownloadJob[]
}

export function ArticleDownloadsCard({ jobs }: ArticleDownloadsCardProps) {
  if (jobs.length === 0) return null

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
    </Card>
  )
}
```

**Note on auth:** The component uses `localStorage.getItem("access_token")`. Check how other fetch calls in the codebase pass auth tokens (look at the `OpenAPI` client config in `useConversationSSE.ts`). If `OpenAPI.TOKEN` is the source, use that pattern:

```tsx
import { OpenAPI } from "@/client"

// inside queryFn:
const token = typeof OpenAPI.TOKEN === "function"
  ? await OpenAPI.TOKEN({} as never)
  : (OpenAPI.TOKEN ?? "")
const resp = await fetch(`/api/v1/articles/jobs/${job.job_id}`, {
  headers: { Authorization: `Bearer ${token}` },
})
```

Replace the localStorage approach with the `OpenAPI.TOKEN` version.

- [ ] **Step 2: Type-check**
```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**
```bash
git add frontend/src/components/Chat/ArticleDownloadsCard.tsx
git commit -m "feat(frontend): add ArticleDownloadsCard component with polling"
```

---

## Task 9: Integrate into `ChatWindow`

**Files:**
- Modify: `frontend/src/components/Chat/ChatWindow.tsx`

- [ ] **Step 1: Add imports and state**

Add to imports at top of `ChatWindow.tsx`:
```tsx
import type { ArticleDownloadJob } from "@/client/chatTypes"
import { ArticleDownloadsCard } from "./ArticleDownloadsCard"
```

Add state inside `ChatWindow` (alongside `pendingToolCalls`):
```tsx
const [articleDownloadBatches, setArticleDownloadBatches] = useState<ArticleDownloadJob[][]>([])
```

Add reset in the `conversationId` change effect:
```tsx
useEffect(() => {
  setLocalMessages([])
  setPendingToolCalls([])
  setHazardChemicals([])
  setArticleDownloadBatches([])
  stopPolling()
}, [conversationId, stopPolling])
```

- [ ] **Step 2: Add `handleArticleDownloads` callback**

```tsx
const handleArticleDownloads = useCallback((jobs: ArticleDownloadJob[]) => {
  if (jobs.length > 0) {
    setArticleDownloadBatches((prev) => [...prev, jobs])
  }
}, [])
```

- [ ] **Step 3: Pass callback to `useConversationSSE`**

```tsx
const { streamingState, streamingContent } = useConversationSSE({
  conversationId,
  enabled: sseEnabled,
  onMessage: handleSSEMessage,
  onToolCall: handleToolCall,
  onHazards: handleHazards,
  onError: handleError,
  onArticleDownloads: handleArticleDownloads,
})
```

- [ ] **Step 4: Render cards in JSX**

In the message list section, add the article download cards between the settled messages and the streaming/thinking indicators:

```tsx
{localMessages.map((msg) => (
  <MessageBubble key={msg.id} message={msg} />
))}

{articleDownloadBatches.map((batch, i) => (
  <ArticleDownloadsCard key={i} jobs={batch} />
))}

{(streamingState === "thinking" || isRecovering) && (
  <ThinkingIndicator toolCalls={pendingToolCalls} />
)}
```

- [ ] **Step 5: Type-check**
```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 6: Commit**
```bash
git add frontend/src/components/Chat/ChatWindow.tsx
git commit -m "feat(frontend): render article download status cards in chat"
```

---

## Task 10: End-to-end smoke test

Verify the full integration works with a running stack.

- [ ] **Step 1: Start the stack**
```bash
docker compose up -d --build
```

- [ ] **Step 2: Send a chat message asking for literature**

Open the app, start a conversation, and send:
> "Find papers on retrosynthetic planning with neural networks"

- [ ] **Step 3: Verify download cards appear**

After the `literature_search` tool completes, one or more `ArticleDownloadsCard` components should appear in the chat showing DOI rows with spinning loaders.

- [ ] **Step 4: Verify agent context injection**

Send a follow-up message (e.g., "What papers are available?"). The agent's response should reference article download status.

- [ ] **Step 5: Check article-fetcher logs**
```bash
docker compose logs article-fetcher --tail=30
```
Expected: log lines showing `Queued fetch job <uuid> for DOI <doi>`.

- [ ] **Step 6: Final commit (if any cleanup)**
```bash
git add -p
git commit -m "fix: address any issues found during smoke testing"
```
