# PDF Parser → RAG Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the article-fetcher → pdf-parser → ai-agent pipeline so that articles downloaded during a conversation are parsed and injected into a per-conversation RAG corpus that is merged with the default corpus on every `rag_search` call.

**Architecture:** `conversation_id` flows through the entire chain. article-fetcher fires a webhook to pdf-parser with `conversation_id`; pdf-parser stores chunks in articles-minio under `{conversation_id}/{doc_key}/` and calls `POST /rag/ingest` on the ai-agent; the ai-agent pulls the chunk files, writes them to `data-rag/sources/{conversation_id}/corpus_processed/`, invalidates the cached retriever, and serves merged `default + conversation` results via a `MultiScopeRetriever`.

**Tech Stack:** Python 3.11, FastAPI, boto3, LangGraph `RunnableConfig`, LangChain `InjectedToolArg`, pytest

**Design spec:** `.claude/plans/2026-03-22-pdf-parser-rag-integration-design.md`
**pdf-parser implementation plan:** `.claude/plans/2026-03-22-pdf-parser-microservice.md`

---

## File Map

| File | Action | Change |
|------|--------|--------|
| `services/article-fetcher/app/main.py` | Modify | `FetchRequest` + job record + `_run_fetch` + webhook body gain `conversation_id` |
| `services/article-fetcher/tests/test_main.py` | Modify | Update `_run_fetch` call sites; add `conversation_id` assertions |
| `backend/app/worker/tasks/chat.py` | Modify | `_submit_article_jobs` passes `conversation_id` in POST body |
| `backend/tests/worker/test_chat_article_helpers.py` | Modify | Assert `conversation_id` in article-fetcher POST body |
| `services/ai-agent/pyproject.toml` | Modify | Add `boto3` dependency |
| `services/ai-agent/app/config.py` | Modify | Add `ARTICLES_MINIO_*` settings |
| `services/ai-agent/app/tools/rag.py` | Modify | Add `MultiScopeRetriever`; add `_get_retriever_for_conversation`; update `_run_rag_query` to accept config; update `rag_search` with `InjectedToolArg` |
| `services/ai-agent/tests/test_rag.py` | Modify | Update monkeypatches; add `MultiScopeRetriever` and scope-injection tests |
| `services/ai-agent/app/agent.py` | Modify | `call_tools` receives and forwards `RunnableConfig` |
| `services/ai-agent/app/main.py` | Modify | Register `/rag/ingest` endpoint; pass `config` in both invoke paths |
| `services/ai-agent/tests/test_rag_ingest.py` | Create | Tests for `/rag/ingest` endpoint |
| `compose.yml` | Modify | Wire env vars for pdf-parser, ai-agent, article-fetcher |

---

## Task 1: article-fetcher — propagate `conversation_id`

**Files:**
- Modify: `services/article-fetcher/app/main.py`
- Modify: `services/article-fetcher/tests/test_main.py`

- [ ] **Step 1: Write the failing tests**

Add to `services/article-fetcher/tests/test_main.py`:

```python
def test_post_fetch_stores_conversation_id_in_redis(client, mock_deps):
    """conversation_id submitted with the request must be persisted in the job record."""
    mock_redis, _ = mock_deps
    mock_redis.set.return_value = True

    resp = client.post("/fetch", json={"doi": "10.1234/test", "conversation_id": "conv-abc"})
    assert resp.status_code == 202

    set_call = mock_redis.set.call_args
    stored = json.loads(set_call[0][1])
    assert stored["conversation_id"] == "conv-abc"


def test_run_fetch_webhook_includes_conversation_id(mock_redis, mock_s3):
    """Webhook payload sent to article processor must include conversation_id."""
    job_record = json.dumps({
        "job_id": "j-conv", "doi": "10.1/x", "status": "running",
        "object_key": None, "error": None, "created_at": "2026-01-01T00:00:00Z",
        "conversation_id": "conv-999",
    })
    mock_redis.get.return_value = job_record
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
        mock_s3.presign_url.return_value = "http://minio/j-conv.pdf"

        from app.main import _run_fetch
        _run_fetch("j-conv", "10.1/x", "conv-999")

        payload = mock_requests.post.call_args[1]["json"]
        assert payload["conversation_id"] == "conv-999"
```

Also update the three existing `_run_fetch` call sites in tests to pass a `conversation_id` arg (empty string is fine):

```python
# In test_run_fetch_fires_webhook_on_done, test_run_fetch_skips_webhook_when_url_empty,
# test_run_fetch_webhook_failure_does_not_raise:
_run_fetch("j1", "10.1/x", "")  # add empty string third arg
_run_fetch("j2", "10.1/y", "")
_run_fetch("j3", "10.1/z", "")
```

And update each job dict returned by `mock_redis.get.return_value` in those tests to include `"conversation_id": ""`.

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd services/article-fetcher
uv run pytest tests/test_main.py::test_post_fetch_stores_conversation_id_in_redis tests/test_main.py::test_run_fetch_webhook_includes_conversation_id -v
```
Expected: FAIL — `conversation_id` field missing

- [ ] **Step 3: Update `app/main.py`**

```python
class FetchRequest(BaseModel):
    doi: str
    conversation_id: str = ""
```

In `post_fetch`, add `"conversation_id": req.conversation_id` to the job dict:

```python
job = {
    "job_id": job_id,
    "doi": req.doi,
    "conversation_id": req.conversation_id,
    "status": "pending",
    "object_key": None,
    "error": None,
    "created_at": datetime.now(timezone.utc).isoformat(),
}
```

Change background task call to pass `conversation_id`:

```python
background_tasks.add_task(_run_fetch, job_id, req.doi, req.conversation_id)
```

Update `_run_fetch` signature and webhook payload:

```python
def _run_fetch(job_id: str, doi: str, conversation_id: str = "") -> None:
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
                    json={
                        "job_id": job_id,
                        "doi": doi,
                        "object_key": object_key,
                        "conversation_id": conversation_id,
                        "status": "done",
                    },
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

- [ ] **Step 4: Run all article-fetcher tests**

```bash
cd services/article-fetcher
uv run pytest tests/ -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add services/article-fetcher/app/main.py services/article-fetcher/tests/test_main.py
git commit -m "feat(article-fetcher): propagate conversation_id through job record and webhook"
```

---

## Task 2: backend — pass `conversation_id` to article-fetcher

**Files:**
- Modify: `backend/app/worker/tasks/chat.py`
- Modify: `backend/tests/worker/test_chat_article_helpers.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/worker/test_chat_article_helpers.py`:

```python
def test_submit_article_jobs_passes_conversation_id_to_fetcher():
    from app.worker.tasks.chat import _submit_article_jobs

    r = MagicMock()
    r.lrange.return_value = []

    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.json.return_value = {"job_id": "uuid-99", "status": "pending"}

    with patch("app.worker.tasks.chat.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        _submit_article_jobs(r, "conv-xyz", ["10.1/test"])

        call_json = mock_client.post.call_args[1]["json"]
        assert call_json["doi"] == "10.1/test"
        assert call_json["conversation_id"] == "conv-xyz"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend
uv run pytest tests/worker/test_chat_article_helpers.py::test_submit_article_jobs_passes_conversation_id_to_fetcher -v
```
Expected: FAIL — `conversation_id` not in POST body

- [ ] **Step 3: Update `_submit_article_jobs` in `backend/app/worker/tasks/chat.py`**

Find the POST call inside `_submit_article_jobs` (around line 106) and add `conversation_id`:

```python
resp = client.post(
    f"{settings.ARTICLE_FETCHER_URL}/fetch",
    json={"doi": doi, "conversation_id": conversation_id},
)
```

- [ ] **Step 4: Run all backend worker tests**

```bash
cd backend
uv run pytest tests/worker/ -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/worker/tasks/chat.py backend/tests/worker/test_chat_article_helpers.py
git commit -m "feat(backend): pass conversation_id to article-fetcher /fetch"
```

---

## Task 3: ai-agent — config and dependency

**Files:**
- Modify: `services/ai-agent/pyproject.toml`
- Modify: `services/ai-agent/app/config.py`

- [ ] **Step 1: Add `boto3` to ai-agent dependencies**

In `services/ai-agent/pyproject.toml`, add to the `dependencies` list:

```toml
"boto3>=1.28.0",
```

Install it:

```bash
cd services/ai-agent
uv add boto3
```

- [ ] **Step 2: Add MinIO settings to `app/config.py`**

Add these fields to the `Settings` class in `services/ai-agent/app/config.py`:

```python
# Articles MinIO (shared with article-fetcher and pdf-parser)
ARTICLES_MINIO_ENDPOINT: str = "articles-minio:9000"
ARTICLES_MINIO_ACCESS_KEY: str = "minioadmin"
ARTICLES_MINIO_SECRET_KEY: str = "minioadmin"
ARTICLES_MINIO_PARSED_BUCKET: str = "parsed-chunks"
```

- [ ] **Step 3: Verify config loads**

```bash
cd services/ai-agent
python -c "from app.config import settings; print(settings.ARTICLES_MINIO_ENDPOINT)"
```
Expected: `articles-minio:9000`

- [ ] **Step 4: Commit**

```bash
git add services/ai-agent/pyproject.toml services/ai-agent/app/config.py
git commit -m "feat(ai-agent): add boto3 dep and articles-minio config settings"
```

---

## Task 4: ai-agent — `MultiScopeRetriever` + scope injection in `rag.py`

**Files:**
- Modify: `services/ai-agent/app/tools/rag.py`
- Modify: `services/ai-agent/tests/test_rag.py`

This is the largest change. Work in three sub-steps.

### 4a: Add `MultiScopeRetriever`

- [ ] **Step 1: Write failing tests for `MultiScopeRetriever`**

Add to `services/ai-agent/tests/test_rag.py`:

```python
def test_multi_scope_retriever_merges_results():
    from app.tools.rag import MultiScopeRetriever, RetrievalResult

    class _Stub:
        def __init__(self, results):
            self._results = results
        def retrieve(self, query, top_k=5):
            return self._results

    r1 = _Stub([RetrievalResult(doc_id="a", score=0.9, text="text a")])
    r2 = _Stub([RetrievalResult(doc_id="b", score=0.8, text="text b")])

    merged = MultiScopeRetriever([r1, r2])
    results = merged.retrieve("query", top_k=5)

    doc_ids = [r.doc_id for r in results]
    assert "a" in doc_ids
    assert "b" in doc_ids


def test_multi_scope_retriever_respects_top_k():
    from app.tools.rag import MultiScopeRetriever, RetrievalResult

    class _Stub:
        def retrieve(self, query, top_k=5):
            return [RetrievalResult(doc_id=f"doc-{i}", score=1.0 / (i + 1), text="") for i in range(top_k)]

    merged = MultiScopeRetriever([_Stub(), _Stub()])
    results = merged.retrieve("query", top_k=3)
    assert len(results) == 3


def test_multi_scope_retriever_single_scope_passthrough():
    from app.tools.rag import MultiScopeRetriever, RetrievalResult

    class _Stub:
        def retrieve(self, query, top_k=5):
            return [RetrievalResult(doc_id="only", score=0.99, text="text")]

    merged = MultiScopeRetriever([_Stub()])
    results = merged.retrieve("query", top_k=5)
    assert results[0].doc_id == "only"
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd services/ai-agent
uv run pytest tests/test_rag.py::test_multi_scope_retriever_merges_results -v
```
Expected: FAIL — `MultiScopeRetriever` not defined

- [ ] **Step 3: Add `MultiScopeRetriever` to `app/tools/rag.py`**

Insert after the `BM25DenseRankFusionRetriever` class (before `_supported_chunk_files`):

```python
class MultiScopeRetriever:
    """Fuses results from multiple scope retrievers via reciprocal rank fusion."""

    def __init__(self, retrievers: list, rrf_k: int = 60) -> None:
        self._retrievers = retrievers
        self._rrf_k = rrf_k

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        scores: dict[str, float] = defaultdict(float)
        result_by_id: dict[str, RetrievalResult] = {}

        for retriever in self._retrievers:
            hits = retriever.retrieve(query, top_k=max(top_k, 20))
            for rank, hit in enumerate(hits, start=1):
                scores[hit.doc_id] += 1.0 / (self._rrf_k + rank)
                if hit.doc_id not in result_by_id:
                    result_by_id[hit.doc_id] = hit

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [
            RetrievalResult(
                doc_id=doc_id,
                score=score,
                text=result_by_id[doc_id].text,
                metadata=result_by_id[doc_id].metadata,
            )
            for doc_id, score in ranked[:top_k]
        ]
```

- [ ] **Step 4: Run tests**

```bash
cd services/ai-agent
uv run pytest tests/test_rag.py::test_multi_scope_retriever_merges_results tests/test_rag.py::test_multi_scope_retriever_respects_top_k tests/test_rag.py::test_multi_scope_retriever_single_scope_passthrough -v
```
Expected: all PASS

### 4b: Add `_get_retriever_for_conversation`

- [ ] **Step 5: Write failing tests**

Add to `services/ai-agent/tests/test_rag.py`:

```python
def test_get_retriever_for_conversation_returns_default_when_no_id(monkeypatch, tmp_path):
    from app.tools.rag import _get_retriever_for_conversation
    import app.tools.rag as rag_module

    fake_default = object()
    monkeypatch.setattr(rag_module, "_get_retriever_for_scope", lambda scope="default": fake_default)
    monkeypatch.setattr("app.config.settings.RAG_SOURCES_DIR", str(tmp_path))

    result = _get_retriever_for_conversation(None)
    assert result is fake_default


def test_get_retriever_for_conversation_returns_default_when_scope_dir_absent(monkeypatch, tmp_path):
    from app.tools.rag import _get_retriever_for_conversation
    import app.tools.rag as rag_module

    fake_default = object()
    monkeypatch.setattr(rag_module, "_get_retriever_for_scope", lambda scope="default": fake_default)
    monkeypatch.setattr("app.config.settings.RAG_SOURCES_DIR", str(tmp_path))

    result = _get_retriever_for_conversation("conv-missing")
    assert result is fake_default


def test_get_retriever_for_conversation_returns_multi_scope_when_dir_exists(monkeypatch, tmp_path):
    from app.tools.rag import _get_retriever_for_conversation, MultiScopeRetriever
    import app.tools.rag as rag_module

    (tmp_path / "conv-123").mkdir()
    fake_default = object()
    fake_conv = object()

    def _fake_get_scope(scope="default"):
        return fake_default if scope == "default" else fake_conv

    monkeypatch.setattr(rag_module, "_get_retriever_for_scope", _fake_get_scope)
    monkeypatch.setattr("app.config.settings.RAG_SOURCES_DIR", str(tmp_path))

    result = _get_retriever_for_conversation("conv-123")
    assert isinstance(result, MultiScopeRetriever)
```

- [ ] **Step 6: Run to confirm they fail**

```bash
cd services/ai-agent
uv run pytest tests/test_rag.py::test_get_retriever_for_conversation_returns_default_when_no_id -v
```
Expected: FAIL — `_get_retriever_for_conversation` not defined

- [ ] **Step 7: Add `_get_retriever_for_conversation` to `app/tools/rag.py`**

Add after the `_get_retriever_for_scope` function:

```python
def _get_retriever_for_conversation(
    conversation_id: str | None,
) -> BM25DenseRankFusionRetriever | MultiScopeRetriever:
    """Return a retriever for the given conversation.

    If a corpus directory exists for the conversation, returns a MultiScopeRetriever
    that merges the default corpus with the conversation-specific corpus.
    Falls back to the default-scope retriever when conversation_id is None or the
    directory does not exist yet.
    """
    from app.config import settings

    default = _get_retriever_for_scope("default")
    if not conversation_id:
        return default
    conv_dir = Path(settings.RAG_SOURCES_DIR) / conversation_id
    if not conv_dir.exists():
        return default
    conv = _get_retriever_for_scope(conversation_id)
    return MultiScopeRetriever([default, conv])
```

- [ ] **Step 8: Run tests**

```bash
cd services/ai-agent
uv run pytest tests/test_rag.py::test_get_retriever_for_conversation_returns_default_when_no_id tests/test_rag.py::test_get_retriever_for_conversation_returns_default_when_scope_dir_absent tests/test_rag.py::test_get_retriever_for_conversation_returns_multi_scope_when_dir_exists -v
```
Expected: all PASS

### 4c: Update `_run_rag_query` and `rag_search`

- [ ] **Step 9: Write failing tests**

Add to `services/ai-agent/tests/test_rag.py`:

```python
def test_rag_search_uses_conversation_scope(monkeypatch):
    """When RunnableConfig contains conversation_id, _get_retriever_for_conversation is called."""
    from app.tools.rag import RetrievalResult
    import app.tools.rag as rag_module

    monkeypatch.setattr("app.config.settings.RAG_ENABLED", True)

    called_with = {}

    class _FakeConvRetriever:
        def retrieve(self, query, top_k=5):
            called_with["query"] = query
            return [RetrievalResult(doc_id="conv-doc", score=0.9, text="conversation result")]

    monkeypatch.setattr(
        rag_module,
        "_get_retriever_for_conversation",
        lambda conv_id: _FakeConvRetriever(),
    )

    result = rag_module.rag_search.invoke(
        {"query": "some chemistry", "top_k": 2},
        config={"configurable": {"conversation_id": "conv-123"}},
    )
    assert "conv-doc" in result
    assert called_with["query"] == "some chemistry"


def test_rag_search_falls_back_to_default_without_config(monkeypatch):
    """rag_search with no config behaves exactly as before — uses default scope."""
    import app.tools.rag as rag_module
    from app.tools.rag import RetrievalResult

    monkeypatch.setattr("app.config.settings.RAG_ENABLED", True)

    class _FakeDefaultRetriever:
        def retrieve(self, query, top_k=5):
            return [RetrievalResult(doc_id="default-doc", score=0.8, text="default result")]

    monkeypatch.setattr(
        rag_module,
        "_get_retriever_for_conversation",
        lambda conv_id: _FakeDefaultRetriever(),
    )

    result = rag_module.rag_search.invoke({"query": "chemistry"})
    assert "default-doc" in result
```

- [ ] **Step 10: Update existing tests that patch `_get_retriever_for_scope`**

In `services/ai-agent/tests/test_rag.py`, find and update two tests that monkeypatch `_get_retriever_for_scope`:

```python
# test_rag_search_happy_path_and_top_k_clamp — change:
monkeypatch.setattr(rag, "_get_retriever_for_scope", lambda scope="default": fake)
# to:
monkeypatch.setattr(rag, "_get_retriever_for_conversation", lambda conv_id: fake)

# test_rag_search_missing_data — change:
monkeypatch.setattr(rag, "_get_retriever_for_scope", _raise_missing)
# to:
monkeypatch.setattr(rag, "_get_retriever_for_conversation", lambda conv_id: (_ for _ in ()).throw(FileNotFoundError("app/data-rag/sources/default")))
```

Actually for the missing-data test, the cleaner approach is:

```python
def test_rag_search_missing_data(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)

    def _raise_missing(conv_id):
        raise FileNotFoundError("app/data-rag/sources/default")

    monkeypatch.setattr(rag, "_get_retriever_for_conversation", _raise_missing)

    result = rag.rag_search.invoke({"query": "aldol condensation"})

    assert "RAG data is not initialized correctly." in result
```

- [ ] **Step 11: Update `_run_rag_query` and `rag_search` in `app/tools/rag.py`**

Replace the existing `_run_rag_query` function with:

```python
def _run_rag_query(query: str, top_k: int, config=None) -> str:
    from app.config import settings

    if not settings.RAG_ENABLED:
        return "RAG tool is disabled by configuration."
    if not query or not query.strip():
        return "Query must be a non-empty string."

    safe_top_k = min(max(int(top_k), 1), 10)
    conversation_id = (config or {}).get("configurable", {}).get("conversation_id") or None
    try:
        retriever = _get_retriever_for_conversation(conversation_id)
        results = retriever.retrieve(query.strip(), top_k=safe_top_k)
        return _format_retrieval_results(results)
    except FileNotFoundError as exc:
        logger.exception("RAG data is missing")
        return (
            "RAG data is not initialized correctly. "
            f"Missing path: {exc}."
        )
    except ImportError as exc:
        logger.exception("Dense retriever dependency missing")
        return (
            "RAG dense retriever dependencies are missing. "
            "Install sentence-transformers and numpy in ai-agent environment. "
            f"Details: {exc}"
        )
    except Exception as exc:
        logger.exception("RAG search failed")
        return f"RAG search failed: {exc}"
```

Replace the existing `rag_search` tool with:

```python
from typing import Annotated
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg


@tool
def rag_search(
    query: str,
    top_k: int = 4,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Search internal chemistry corpus with a hybrid BM25+dense retriever.

    Args:
        query: Natural-language chemistry question or retrieval query.
        top_k: Number of documents to return (default 4, max 10).
    """
    return _run_rag_query(query=query, top_k=top_k, config=config)
```

Add the two new imports near the top of `rag.py` (alongside existing imports):

```python
from typing import Annotated
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
```

- [ ] **Step 12: Run full test_rag.py**

```bash
cd services/ai-agent
uv run pytest tests/test_rag.py -v
```
Expected: all PASS

- [ ] **Step 13: Commit**

```bash
git add services/ai-agent/app/tools/rag.py services/ai-agent/tests/test_rag.py
git commit -m "feat(ai-agent): add MultiScopeRetriever, conversation scope injection in rag_search"
```

---

## Task 5: ai-agent — forward `RunnableConfig` through `call_tools`

**Files:**
- Modify: `services/ai-agent/app/agent.py`

- [ ] **Step 1: Write failing test**

Add to `services/ai-agent/tests/` a new file `tests/test_agent_config.py`:

```python
"""Test that RunnableConfig is forwarded to tools from the call_tools node."""
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, ToolMessage


def test_call_tools_forwards_config_to_tool():
    """Tools invoked inside call_tools must receive the active RunnableConfig."""
    from app.agent import _build_graph

    received_config = {}

    def _fake_tool_func(args, config=None):
        received_config["config"] = config
        return "tool result"

    fake_tool = MagicMock()
    fake_tool.name = "fake_tool"
    fake_tool.invoke = _fake_tool_func

    with patch("app.agent.ALL_TOOLS", [fake_tool]):
        graph = _build_graph(MagicMock())

    ai_msg = AIMessage(content="", tool_calls=[{"id": "call1", "name": "fake_tool", "args": {}}])
    config = {"configurable": {"conversation_id": "conv-test"}}

    result = graph.invoke(
        {"messages": [ai_msg]},
        config=config,
    )

    assert received_config.get("config") is not None
    assert received_config["config"].get("configurable", {}).get("conversation_id") == "conv-test"
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd services/ai-agent
uv run pytest tests/test_agent_config.py -v
```
Expected: FAIL — config not forwarded, `received_config["config"]` is `None`

- [ ] **Step 3: Update `call_tools` in `app/agent.py`**

Add `RunnableConfig` import at top of file:

```python
from langchain_core.runnables import RunnableConfig
```

Change the `call_tools` node signature to accept and forward config:

```python
def call_tools(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    last_message = state["messages"][-1]
    results = []
    for tool_call in last_message.tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"], config=config)
        results.append(
            ToolMessage(
                content=str(observation),
                tool_call_id=tool_call["id"],
            )
        )
    return {"messages": results}
```

- [ ] **Step 4: Run test**

```bash
cd services/ai-agent
uv run pytest tests/test_agent_config.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/ai-agent/app/agent.py services/ai-agent/tests/test_agent_config.py
git commit -m "feat(ai-agent): forward RunnableConfig from call_tools to tool.invoke"
```

---

## Task 6: ai-agent — `/rag/ingest` endpoint

**Files:**
- Modify: `services/ai-agent/app/main.py`
- Create: `services/ai-agent/tests/test_rag_ingest.py`

- [ ] **Step 1: Write failing tests**

Create `services/ai-agent/tests/test_rag_ingest.py`:

```python
"""Tests for POST /rag/ingest — pulls chunks from MinIO into conversation corpus."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_rag_ingest_writes_chunk_files(client, tmp_path):
    """Downloaded chunks must land in the correct local corpus directory."""
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()

    # Simulate MinIO returning two objects
    obj_md = MagicMock()
    obj_md.object_name = "conv-abc/10_1234_test/_chunks/chunk_000.md"
    obj_txt = MagicMock()
    obj_txt.object_name = "conv-abc/10_1234_test/_bm25_chunks/chunk_000.txt"

    mock_boto = MagicMock()
    mock_boto.list_objects_v2.return_value = {"Contents": [
        {"Key": obj_md.object_name},
        {"Key": obj_txt.object_name},
    ]}
    mock_boto.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=b"chunk content"))
    }

    with patch("app.main.boto3") as mock_boto3_mod, \
         patch("app.main.settings") as mock_settings, \
         patch("app.main._RETRIEVER_REGISTRY", {}), \
         patch("app.main._REGISTRY_LOCK"):
        mock_boto3_mod.client.return_value = mock_boto
        mock_settings.ARTICLES_MINIO_ENDPOINT = "minio:9000"
        mock_settings.ARTICLES_MINIO_ACCESS_KEY = "key"
        mock_settings.ARTICLES_MINIO_SECRET_KEY = "secret"
        mock_settings.ARTICLES_MINIO_PARSED_BUCKET = "parsed-chunks"
        mock_settings.RAG_SOURCES_DIR = str(sources_dir)

        resp = client.post("/rag/ingest", json={
            "conversation_id": "conv-abc",
            "doc_key": "10_1234_test",
        })

    assert resp.status_code == 200

    chunks_dir = sources_dir / "conv-abc" / "corpus_processed" / "10_1234_test_chunks"
    bm25_dir = sources_dir / "conv-abc" / "corpus_processed" / "10_1234_test_bm25_chunks"
    assert (chunks_dir / "chunk_000.md").exists()
    assert (bm25_dir / "chunk_000.txt").exists()


def test_rag_ingest_invalidates_registry(client, tmp_path):
    """After ingest, the conversation scope entry is removed from _RETRIEVER_REGISTRY."""
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()

    registry = {"conv-stale": object()}  # pre-existing stale entry

    mock_boto = MagicMock()
    mock_boto.list_objects_v2.return_value = {"Contents": []}

    with patch("app.main.boto3") as mock_boto3_mod, \
         patch("app.main.settings") as mock_settings, \
         patch("app.main._RETRIEVER_REGISTRY", registry), \
         patch("app.main._REGISTRY_LOCK"):
        mock_boto3_mod.client.return_value = mock_boto
        mock_settings.ARTICLES_MINIO_ENDPOINT = "minio:9000"
        mock_settings.ARTICLES_MINIO_ACCESS_KEY = "key"
        mock_settings.ARTICLES_MINIO_SECRET_KEY = "secret"
        mock_settings.ARTICLES_MINIO_PARSED_BUCKET = "parsed-chunks"
        mock_settings.RAG_SOURCES_DIR = str(sources_dir)

        client.post("/rag/ingest", json={
            "conversation_id": "conv-stale",
            "doc_key": "some_doc",
        })

    assert "conv-stale" not in registry
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd services/ai-agent
uv run pytest tests/test_rag_ingest.py -v
```
Expected: FAIL — `/rag/ingest` route not found

- [ ] **Step 3: Add `/rag/ingest` to `app/main.py`**

Add imports at the top of `app/main.py`:

```python
import boto3
from botocore.client import Config as BotocoreConfig
from pydantic import BaseModel
```

Add the ingest request model and endpoint after the existing routes:

```python
class RagIngestRequest(BaseModel):
    conversation_id: str
    doc_key: str


@app.post("/rag/ingest")
async def rag_ingest(req: RagIngestRequest):
    """Internal endpoint: pull parsed chunks from MinIO into the conversation RAG corpus.

    Called by pdf-parser when a document has been fully processed.
    Not authenticated — reachable only inside Docker network.
    """
    from app.tools.rag import _RETRIEVER_REGISTRY, _REGISTRY_LOCK
    from app.config import settings

    bucket = settings.ARTICLES_MINIO_PARSED_BUCKET
    prefix = f"{req.conversation_id}/{req.doc_key}/"
    sources_dir = Path(settings.RAG_SOURCES_DIR)

    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"http://{settings.ARTICLES_MINIO_ENDPOINT}",
            aws_access_key_id=settings.ARTICLES_MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.ARTICLES_MINIO_SECRET_KEY,
            config=BotocoreConfig(signature_version="s3v4"),
            region_name="us-east-1",
        )

        paginator = s3.get_paginator("list_objects_v2")
        object_keys: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                object_keys.append(obj["Key"])

        for key in object_keys:
            # key: {conversation_id}/{doc_key}/_chunks/chunk_000.md
            # strip prefix to get: _chunks/chunk_000.md
            relative = key[len(prefix):]

            # transform: _chunks/ → {doc_key}_chunks/,  _bm25_chunks/ → {doc_key}_bm25_chunks/
            if relative.startswith("_chunks/"):
                local_rel = f"{req.doc_key}_chunks/" + relative[len("_chunks/"):]
            elif relative.startswith("_bm25_chunks/"):
                local_rel = f"{req.doc_key}_bm25_chunks/" + relative[len("_bm25_chunks/"):]
            else:
                logger.warning("rag_ingest: unexpected key path %s, skipping", key)
                continue

            local_path = (
                sources_dir / req.conversation_id / "corpus_processed" / local_rel
            )
            local_path.parent.mkdir(parents=True, exist_ok=True)

            response = s3.get_object(Bucket=bucket, Key=key)
            local_path.write_bytes(response["Body"].read())
            logger.info("rag_ingest: wrote %s", local_path)

    except Exception:
        logger.exception("rag_ingest: failed for conv=%s doc=%s", req.conversation_id, req.doc_key)
        raise HTTPException(status_code=500, detail="RAG ingest failed")

    # Invalidate cached retriever for this conversation scope so the next
    # rag_search call rebuilds from the updated corpus directory.
    with _REGISTRY_LOCK:
        _RETRIEVER_REGISTRY.pop(req.conversation_id, None)

    logger.info(
        "rag_ingest: completed for conv=%s doc=%s (%d files)",
        req.conversation_id, req.doc_key, len(object_keys),
    )
    return {"status": "ok", "files_written": len(object_keys)}
```

Add missing import at the top of `app/main.py`:

```python
from pathlib import Path
from fastapi import FastAPI, HTTPException
```

(`HTTPException` may already be imported — check and add only if missing.)

- [ ] **Step 4: Run tests**

```bash
cd services/ai-agent
uv run pytest tests/test_rag_ingest.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add services/ai-agent/app/main.py services/ai-agent/tests/test_rag_ingest.py
git commit -m "feat(ai-agent): add POST /rag/ingest endpoint for conversation corpus update"
```

---

## Task 7: ai-agent — pass `config` in both agent invocation paths

**Files:**
- Modify: `services/ai-agent/app/main.py`

The `ChatRequest` schema already has `conversation_id: str | None = None` (confirmed in `app/schemas.py`). Only the two `agent.invoke` call sites need updating.

- [ ] **Step 1: Update both call sites in `app/main.py`**

In the `chat` endpoint (around line 44):

```python
agent_config = {"configurable": {"conversation_id": request.conversation_id or ""}}
result = await agent.ainvoke({"messages": langchain_messages}, config=agent_config)
```

In the `chat_stream` endpoint (around line 83):

```python
agent_config = {"configurable": {"conversation_id": request.conversation_id or ""}}
async for event in agent.astream_events(
    {"messages": langchain_messages},
    version="v2",
    config=agent_config,
):
```

- [ ] **Step 2: Run full ai-agent test suite**

```bash
cd services/ai-agent
uv run pytest tests/ -v
```
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add services/ai-agent/app/main.py
git commit -m "feat(ai-agent): pass conversation_id via RunnableConfig in both chat endpoints"
```

---

## Task 8: Compose wiring

**Files:**
- Modify: `compose.yml`

- [ ] **Step 1: Update `article-fetcher` service**

Under `article-fetcher → environment`, add (the `articles-minio` service is already present):

```yaml
- ARTICLE_PROCESSOR_WEBHOOK_URL=http://pdf-parser:8300/jobs
```

- [ ] **Step 2: Add `pdf-parser` service** (if not already present from the pdf-parser plan)

If the pdf-parser service block does not exist yet, add it after `article-fetcher`:

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
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8300/health"]
      interval: 10s
      timeout: 5s
      retries: 5
```

- [ ] **Step 3: Update `ai-agent` service**

Under `ai-agent → environment`, add:

```yaml
- ARTICLES_MINIO_ENDPOINT=articles-minio:9000
- ARTICLES_MINIO_ACCESS_KEY=${ARTICLES_MINIO_ACCESS_KEY:-minioadmin}
- ARTICLES_MINIO_SECRET_KEY=${ARTICLES_MINIO_SECRET_KEY:-minioadmin}
- ARTICLES_MINIO_PARSED_BUCKET=parsed-chunks
```

- [ ] **Step 4: Validate compose file**

```bash
docker compose config --quiet
```
Expected: exits 0

- [ ] **Step 5: Commit**

```bash
git add compose.yml
git commit -m "feat(compose): wire pdf-parser, ai-agent, article-fetcher for RAG integration"
```

---

## Task 9: End-to-end smoke test

- [ ] **Step 1: Build and start all services**

```bash
docker compose up -d --build redis articles-minio article-fetcher pdf-parser ai-agent celery-worker
```

- [ ] **Step 2: Check health of all services**

```bash
docker compose ps
curl http://localhost:8200/health   # article-fetcher
curl http://localhost:8300/health   # pdf-parser
curl http://localhost:8000/health   # ai-agent
```
Expected: all return `{"status":"ok",...}`

- [ ] **Step 3: Submit a fetch job with a conversation_id**

```bash
curl -X POST http://localhost:8200/fetch \
  -H "Content-Type: application/json" \
  -d '{"doi":"10.1039/c9sc04589e","conversation_id":"test-conv-001"}'
```
Expected: `{"job_id":"<uuid>","status":"pending"}`

- [ ] **Step 4: Poll article-fetcher until done**

```bash
JOB_ID=<uuid from above>
curl http://localhost:8200/jobs/$JOB_ID
```
Poll until status is `done`. Then check that pdf-parser received the webhook:

```bash
docker compose logs pdf-parser | grep "submitted job"
```

- [ ] **Step 5: Poll pdf-parser until completed**

```bash
PARSER_JOB_ID=<from pdf-parser logs>
curl http://localhost:8300/jobs/$PARSER_JOB_ID
```
Poll until `status == "completed"`.

- [ ] **Step 6: Verify ai-agent received the ingest webhook**

```bash
docker compose logs ai-agent | grep "rag_ingest: completed"
```
Expected: log line showing `conv=test-conv-001`

- [ ] **Step 7: Verify corpus directory created**

```bash
ls services/ai-agent/app/data-rag/sources/test-conv-001/corpus_processed/
```
Expected: directories with `_chunks/` and `_bm25_chunks/` files

- [ ] **Step 8: Test rag_search with the conversation scope via ai-agent API**

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"search for synthesis information"}],"conversation_id":"test-conv-001"}'
```
Expected: response that references document content from the downloaded article

- [ ] **Step 9: Commit any remaining changes**

```bash
git add -p
git commit -m "feat: complete pdf-parser RAG integration e2e wiring"
```
