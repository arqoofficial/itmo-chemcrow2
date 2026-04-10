# Async Pipeline Test Gap Coverage Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the 5 critical test gaps in the async tool pipeline identified in the audit.

**Architecture:** Tests-only plan — no production code changes. All new tests go into existing test files. No new files needed. Code under test already exists, so tests should pass on first run.

**Tech Stack:** pytest, `unittest.mock.patch`/`MagicMock`, FastAPI `TestClient`, `requests` mock

---

## File Map

| Test File | What to Add |
|-----------|-------------|
| `backend/tests/worker/test_continuation.py` | Tasks 1–4: formatter, trigger, failure callback, lock release |
| `services/ai-agent/tests/test_s2_search_endpoint.py` | Task 5: S2 500/403 errors, all-retries-exhausted |

---

## Task 1: `_format_s2_results` unit tests

**Files:**
- Modify: `backend/tests/worker/test_continuation.py`
- Source under test: `backend/app/worker/tasks/continuation.py:45-64` (`_format_s2_results`)
- Template used by source: `backend/app/worker/prompts.py` (`S2_RESULTS`)

- [ ] **Step 1: Add tests to the file**

Append to `backend/tests/worker/test_continuation.py`:

```python
# ── _format_s2_results ────────────────────────────────────────────────────────

def test_format_s2_results_happy_path():
    """Single paper with all fields → correct heading and content."""
    from app.worker.tasks.continuation import _format_s2_results
    papers = [{
        "title": "Aspirin Synthesis Review",
        "authors": "Alice, Bob",
        "year": 2023,
        "doi": "10.1234/asp",
        "abstract": "A review of aspirin synthesis.",
    }]
    result = _format_s2_results(papers, "aspirin")
    assert "[Background: Literature Search Results]" in result
    assert 'search for "aspirin" found 1 paper' in result
    assert "Aspirin Synthesis Review" in result
    assert "10.1234/asp" in result
    assert "2023" in result
    assert "A review of aspirin synthesis." in result


def test_format_s2_results_truncates_abstract_at_400_chars():
    """Abstract longer than 400 chars gets truncated with '...'."""
    from app.worker.tasks.continuation import _format_s2_results
    long_abstract = "x" * 500
    papers = [{"title": "T", "authors": "A", "year": 2024, "doi": "10.1/x", "abstract": long_abstract}]
    result = _format_s2_results(papers, "query")
    assert "x" * 400 + "..." in result
    assert "x" * 401 not in result


def test_format_s2_results_missing_optional_fields():
    """Paper with no doi, abstract, year → uses fallback strings, no crash."""
    from app.worker.tasks.continuation import _format_s2_results
    papers = [{"title": "Minimal Paper"}]
    result = _format_s2_results(papers, "query")
    assert "Minimal Paper" in result
    assert "N/A" in result          # doi and year fallbacks
    assert "No abstract." in result  # abstract fallback


def test_format_s2_results_multiple_papers():
    """Multiple papers are numbered sequentially."""
    from app.worker.tasks.continuation import _format_s2_results
    papers = [
        {"title": "Paper One", "doi": "10.1/1"},
        {"title": "Paper Two", "doi": "10.1/2"},
        {"title": "Paper Three", "doi": "10.1/3"},
    ]
    result = _format_s2_results(papers, "q")
    assert "1. **Paper One**" in result
    assert "2. **Paper Two**" in result
    assert "3. **Paper Three**" in result
```

- [ ] **Step 2: Run to verify they pass**

```bash
docker compose exec backend pytest tests/worker/test_continuation.py::test_format_s2_results_happy_path tests/worker/test_continuation.py::test_format_s2_results_truncates_abstract_at_400_chars tests/worker/test_continuation.py::test_format_s2_results_missing_optional_fields tests/worker/test_continuation.py::test_format_s2_results_multiple_papers -v
```

Expected: 4 PASSes.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/worker/test_continuation.py
git commit -m "test: add _format_s2_results unit tests"
```

- [ ] **Step 4: Record learnings**

Record learnings to `.claude/learnings-format-s2-results-tests.md` using the surfacing-subagent-learnings skill.

---

## Task 2: `_trigger_rag_continuation` unit tests

**Files:**
- Modify: `backend/tests/worker/test_continuation.py`
- Source under test: `backend/app/worker/tasks/continuation.py:238-258` (`_trigger_rag_continuation`)
- Template used by source: `backend/app/worker/prompts.py` (`PAPERS_INGESTED`)

`_trigger_rag_continuation(conversation_id, completed_job_ids=None)`:
- Reads `s2_paper_meta:{job_id}` from Redis for each job_id
- Formats `PAPERS_INGESTED` prompt (from `app.worker.prompts`)
- Calls `save_background_message(conversation_id, content, variant="info")`
- Publishes `background_update` SSE via `_publish_sync`
- Dispatches `run_agent_continuation.apply_async(args=[conversation_id], countdown=1)`

- [ ] **Step 1: Add tests to the file**

Append to `backend/tests/worker/test_continuation.py`:

```python
# ── _trigger_rag_continuation ─────────────────────────────────────────────────

@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.save_background_message")
@patch("app.worker.tasks.continuation._publish_sync")
@patch("app.worker.tasks.continuation.get_sync_redis")
def test_trigger_rag_continuation_with_redis_metadata(
    mock_redis, mock_publish, mock_save, mock_continuation
):
    """Job IDs with Redis metadata → paper titles in PAPERS_INGESTED message."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.get.return_value = json.dumps({
        "title": "Aspirin Review", "authors": "Alice", "year": 2023, "doi": "10.1/asp"
    })

    from app.worker.tasks.continuation import _trigger_rag_continuation
    _trigger_rag_continuation("conv-abc", ["job-1"])

    # Background message saved with PAPERS_INGESTED content
    mock_save.assert_called_once()
    conv_id, content, variant = mock_save.call_args[0]
    assert conv_id == "conv-abc"
    assert "[Background: New Papers Available]" in content
    assert "Aspirin Review" in content
    assert variant == "info"

    # background_update SSE published
    mock_publish.assert_called_once_with("conv-abc", {"event": "background_update"})

    # Continuation dispatched with countdown=1
    mock_continuation.apply_async.assert_called_once_with(args=["conv-abc"], countdown=1)


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.save_background_message")
@patch("app.worker.tasks.continuation._publish_sync")
@patch("app.worker.tasks.continuation.get_sync_redis")
def test_trigger_rag_continuation_missing_redis_metadata(
    mock_redis, mock_publish, mock_save, mock_continuation
):
    """When Redis has no metadata for a job_id → uses fallback 'recently parsed articles'."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.get.return_value = None  # metadata expired or missing

    from app.worker.tasks.continuation import _trigger_rag_continuation
    _trigger_rag_continuation("conv-abc", ["job-orphan"])

    conv_id, content, variant = mock_save.call_args[0]
    assert "recently parsed articles" in content


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.save_background_message")
@patch("app.worker.tasks.continuation._publish_sync")
@patch("app.worker.tasks.continuation.get_sync_redis")
def test_trigger_rag_continuation_no_job_ids(
    mock_redis, mock_publish, mock_save, mock_continuation
):
    """Called with completed_job_ids=None (manual trigger) → generic fallback message."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r

    from app.worker.tasks.continuation import _trigger_rag_continuation
    _trigger_rag_continuation("conv-abc", None)

    conv_id, content, variant = mock_save.call_args[0]
    assert "[Background: New Papers Available]" in content
    assert "recently parsed articles" in content
    mock_continuation.apply_async.assert_called_once()
```

- [ ] **Step 2: Run to verify they pass**

```bash
docker compose exec backend pytest tests/worker/test_continuation.py::test_trigger_rag_continuation_with_redis_metadata tests/worker/test_continuation.py::test_trigger_rag_continuation_missing_redis_metadata tests/worker/test_continuation.py::test_trigger_rag_continuation_no_job_ids -v
```

Expected: 3 PASSes.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/worker/test_continuation.py
git commit -m "test: add _trigger_rag_continuation unit tests"
```

- [ ] **Step 4: Record learnings**

Record learnings to `.claude/learnings-trigger-rag-continuation-tests.md` using the surfacing-subagent-learnings skill.

---

## Task 3: `_on_monitor_ingestion_failure` callback test

**Files:**
- Modify: `backend/tests/worker/test_continuation.py`
- Source under test: `backend/app/worker/tasks/continuation.py:313-322` (`_on_monitor_ingestion_failure`)

`_on_monitor_ingestion_failure(self, exc, task_id, args, kwargs, einfo)` is a standalone function
assigned to `monitor_ingestion.on_failure`. It logs at WARNING with the conversation_id from `args[0]`.
It must not raise.

- [ ] **Step 1: Add tests to the file**

Append to `backend/tests/worker/test_continuation.py`:

```python
# ── _on_monitor_ingestion_failure ─────────────────────────────────────────────

def test_on_monitor_ingestion_failure_logs_warning_not_error(caplog):
    """Failure callback logs at WARNING level with conversation_id — must not raise."""
    import logging
    from app.worker.tasks.continuation import _on_monitor_ingestion_failure

    with caplog.at_level(logging.WARNING, logger="app.worker.tasks.continuation"):
        # Call as a plain function (not as bound Celery task method)
        _on_monitor_ingestion_failure(
            self=None,
            exc=TimeoutError("max retries"),
            task_id="task-uuid-123",
            args=["conv-timeout"],
            kwargs={},
            einfo=None,
        )

    assert any("conv-timeout" in r.message for r in caplog.records)
    assert all(r.levelno == logging.WARNING for r in caplog.records if "conv-timeout" in r.message)


def test_on_monitor_ingestion_failure_handles_missing_args(caplog):
    """If args is empty (shouldn't happen, but defensive) → logs 'unknown', no crash."""
    import logging
    from app.worker.tasks.continuation import _on_monitor_ingestion_failure

    # Should not raise even with empty args
    _on_monitor_ingestion_failure(
        self=None,
        exc=Exception("boom"),
        task_id="task-x",
        args=[],   # empty — conversation_id not extractable
        kwargs={},
        einfo=None,
    )
    # No assertion on message content — just verifying it doesn't raise
```

- [ ] **Step 2: Run to verify they pass**

```bash
docker compose exec backend pytest tests/worker/test_continuation.py::test_on_monitor_ingestion_failure_logs_warning_not_error tests/worker/test_continuation.py::test_on_monitor_ingestion_failure_handles_missing_args -v
```

Expected: 2 PASSes.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/worker/test_continuation.py
git commit -m "test: add _on_monitor_ingestion_failure callback tests"
```

- [ ] **Step 4: Record learnings**

Record learnings to `.claude/learnings-monitor-ingestion-failure-tests.md` using the surfacing-subagent-learnings skill.

---

## Task 4: Lock released when `_process_streaming` raises

**Files:**
- Modify: `backend/tests/worker/test_continuation.py`
- Source under test: `backend/app/worker/tasks/continuation.py:131-209` (`run_agent_continuation`)

The `run_agent_continuation` task has a `try/finally` that always deletes the Redis lock.
When `_process_streaming` raises, the inner `except` logs and returns — but the outer `finally`
still runs, releasing `conv_processing:{id}`. This behavior must be explicitly tested.

- [ ] **Step 1: Add test to the file**

Append to `backend/tests/worker/test_continuation.py`:

```python
# ── run_agent_continuation: lock released on streaming failure ─────────────────

@patch("app.worker.tasks.continuation.get_sync_redis")
@patch("app.worker.tasks.continuation.Session")
@patch("app.worker.tasks.continuation._process_streaming")
def test_run_agent_continuation_releases_lock_on_streaming_failure(
    mock_streaming, mock_session, mock_redis
):
    """If _process_streaming raises, the Redis lock must still be deleted."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.set.return_value = True   # lock acquired
    mock_r.llen.return_value = 0     # no pending

    mock_db = MagicMock()
    mock_session.return_value.__enter__ = lambda s: mock_db
    mock_session.return_value.__exit__ = MagicMock(return_value=False)
    mock_db.exec.return_value.all.return_value = []

    mock_streaming.side_effect = RuntimeError("SSE connection dropped")

    from app.worker.tasks.continuation import run_agent_continuation
    # Must not raise — inner except catches streaming errors
    run_agent_continuation("conv-crash")

    # Lock MUST be released despite the streaming failure
    mock_r.delete.assert_any_call("conv_processing:conv-crash")

    # No assistant message saved (streaming failed before DB write)
    mock_db.add.assert_not_called()
```

- [ ] **Step 2: Run to verify it passes**

```bash
docker compose exec backend pytest tests/worker/test_continuation.py::test_run_agent_continuation_releases_lock_on_streaming_failure -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/worker/test_continuation.py
git commit -m "test: verify Redis lock released when streaming fails in run_agent_continuation"
```

- [ ] **Step 4: Record learnings**

Record learnings to `.claude/learnings-lock-release-streaming-failure-tests.md` using the surfacing-subagent-learnings skill.

---

## Task 5: S2 non-429 HTTP errors in `/internal/s2-search`

**Files:**
- Modify: `services/ai-agent/tests/test_s2_search_endpoint.py`
- Source under test: `services/ai-agent/app/main.py:281-332` (`s2_search` endpoint)

The `/internal/s2-search` endpoint calls `r.raise_for_status()` after the retry loop.
- If S2 returns 500 or 403 (not 429), the loop breaks immediately and `raise_for_status()` raises `requests.HTTPError`.
- If all 5 retries return 429 (no API key → `retry_waits=[5,10,20,30,60]`), `raise_for_status()` also raises on the final 429.
- Both cases propagate as HTTP 500 from the FastAPI endpoint.

**Note:** FastAPI's `TestClient` with default `raise_server_exceptions=True` may re-raise the `requests.HTTPError` instead of returning a 500 response. If that happens, use `TestClient(app, raise_server_exceptions=False)` for these tests specifically.

- [ ] **Step 1: Add tests to the file**

Add `import requests as requests_lib` near the top of `services/ai-agent/tests/test_s2_search_endpoint.py` (below existing imports), then append:

```python
import requests as requests_lib

# Use a client that does NOT re-raise server exceptions — we want the HTTP 500 response
_error_client = TestClient(app, raise_server_exceptions=False)


def test_s2_search_500_propagates_as_error():
    """S2 returns 500 → raise_for_status raises → FastAPI endpoint returns 500."""
    error_resp = MagicMock()
    error_resp.status_code = 500
    error_resp.raise_for_status.side_effect = requests_lib.HTTPError("500 Server Error")

    with patch("app.main.requests.get", return_value=error_resp):
        resp = _error_client.post("/internal/s2-search", json={"query": "aspirin", "max_results": 3})

    assert resp.status_code == 500


def test_s2_search_403_propagates_as_error():
    """S2 returns 403 (bad API key) → raise_for_status raises → FastAPI endpoint returns 500."""
    error_resp = MagicMock()
    error_resp.status_code = 403
    error_resp.raise_for_status.side_effect = requests_lib.HTTPError("403 Forbidden")

    with patch("app.main.requests.get", return_value=error_resp):
        resp = _error_client.post("/internal/s2-search", json={"query": "aspirin", "max_results": 3})

    assert resp.status_code == 500


def test_s2_search_all_retries_exhausted_returns_error():
    """All 5 retry attempts return 429 (no API key path) → raise_for_status on last → 500."""
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.raise_for_status.side_effect = requests_lib.HTTPError("429 Too Many Requests")

    # retry_waits=[5,10,20,30,60] → 5 attempts when no API key
    with patch("app.main.requests.get", return_value=rate_limited), \
         patch("time.sleep"):
        resp = _error_client.post("/internal/s2-search", json={"query": "aspirin", "max_results": 3})

    assert resp.status_code == 500
```

- [ ] **Step 2: Run to verify they pass**

```bash
docker compose exec ai-agent pytest tests/test_s2_search_endpoint.py::test_s2_search_500_propagates_as_error tests/test_s2_search_endpoint.py::test_s2_search_403_propagates_as_error tests/test_s2_search_endpoint.py::test_s2_search_all_retries_exhausted_returns_error -v
```

Expected: 3 PASSes.

- [ ] **Step 3: Run full test suites to confirm no regressions**

```bash
docker compose exec backend pytest tests/worker/test_continuation.py -v
docker compose exec ai-agent pytest tests/test_s2_search_endpoint.py -v
```

Expected: All existing + new tests pass.

- [ ] **Step 4: Commit**

```bash
git add services/ai-agent/tests/test_s2_search_endpoint.py
git commit -m "test: add S2 HTTP error and retry-exhaustion tests for /internal/s2-search"
```

- [ ] **Step 5: Record learnings**

Record learnings to `.claude/learnings-s2-error-tests.md` using the surfacing-subagent-learnings skill.

---

## Self-Review

**Gap coverage:**

| Gap | Covered by Task |
|-----|----------------|
| `_format_s2_results` no direct test | Task 1 ✓ |
| `_trigger_rag_continuation` direct test | Task 2 ✓ |
| `_on_monitor_ingestion_failure` callback | Task 3 ✓ |
| Lock release on streaming failure | Task 4 ✓ |
| S2 non-429 errors + retry exhaustion | Task 5 ✓ |

**Placeholder scan:** None found.

**Type consistency:** All function imports reference exact names from `continuation.py` source. `_error_client` in Task 5 uses `raise_server_exceptions=False` to avoid TestClient re-raising unhandled exceptions.
