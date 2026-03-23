# PDF Parser → RAG Integration Design

**Date:** 2026-03-22

## Overview

Integrate the `pdf-parser` microservice output into the ai-agent's per-conversation RAG corpus. When the article-fetcher downloads a PDF, the pdf-parser processes it and stores parsed chunks in MinIO. The ai-agent then pulls those chunks into a conversation-scoped corpus directory and serves them via a `MultiScopeRetriever` that merges the conversation corpus with the shared default corpus.

## Architecture & Data Flow

```
User message with literature_search
          │
          ▼
Celery worker (chat.py)
  POST /fetch {"doi": "...", "conversation_id": "..."} → article-fetcher
          │
          ▼
article-fetcher: downloads PDF → articles-minio (bucket: articles)
  fires webhook → pdf-parser: POST /jobs {job_id, doi, object_key, conversation_id}
          │
          ▼
pdf-parser: downloads PDF from articles-minio
  → Docling + LLM cleaning → chunks
  → uploads to articles-minio (bucket: parsed-chunks)
    keys: {conversation_id}/{doc_key}/_chunks/chunk_*.md
          {conversation_id}/{doc_key}/_bm25_chunks/chunk_*.txt
  fires webhook → ai-agent: POST /rag/ingest {conversation_id, doc_key}
          │
          ▼
ai-agent /rag/ingest handler:
  downloads chunk files from articles-minio
  writes to data-rag/sources/{conversation_id}/corpus_processed/
  invalidates _RETRIEVER_REGISTRY[conversation_id]
          │
          ▼
Next rag_search call (with RunnableConfig {conversation_id: "..."}):
  MultiScopeRetriever → queries "default" + "{conversation_id}" → RRF merge
```

**Key design decisions:**
- `conversation_id` flows through every hop explicitly — no reverse-lookups in Redis
- `articles-minio` is the single MinIO for both PDFs and parsed chunks (avoids a second MinIO service)
- `POST /rag/ingest` is internal (no auth, only reachable inside Docker network)
- Scope injection uses LangGraph `RunnableConfig.configurable` — no global state, no context vars
- `doc_key` is derived from DOI: `doi.replace("/", "_").replace(".", "_")`

## Component Changes

### 1. `services/article-fetcher`

**`app/main.py`:**
- `FetchRequest` model gains `conversation_id: str = ""`
- Job dict stored in Redis gains `"conversation_id"` key (persisted alongside `doi`, `status`, etc.)
- `_run_fetch` background task receives `conversation_id` from the job record
- Webhook payload to pdf-parser gains `conversation_id`:
  ```python
  json={"job_id": job_id, "doi": doi, "object_key": object_key, "conversation_id": conversation_id, "status": "done"}
  ```

**Tests (`tests/test_main.py`):**
- Extend `test_post_fetch_returns_job_id`: pass `conversation_id` in request body, assert it is stored in Redis
- Add `test_webhook_includes_conversation_id`: verify the webhook POST body contains `conversation_id`

### 2. `services/pdf-parser`

**New config fields (`app/config.py`):**
```python
articles_minio_endpoint: str = "articles-minio:9000"
articles_minio_access_key: str = "minioadmin"
articles_minio_secret_key: str = "minioadmin"
articles_minio_input_bucket: str = "articles"      # where PDFs live
articles_minio_output_bucket: str = "parsed-chunks" # where chunks are written
ai_agent_ingest_url: str = "http://ai-agent:8000"
```

**`app/main.py` — job schema:**
- `POST /jobs` body: `{job_id: str, doi: str, object_key: str, conversation_id: str}`
- `doc_key = doi.replace("/", "_").replace(".", "_")`

**`app/minio_store.py`:**
- Download PDF from `articles_minio_input_bucket/{object_key}`
- Upload chunks to `articles_minio_output_bucket/{conversation_id}/{doc_key}/_chunks/chunk_*.md`
- Upload chunks to `articles_minio_output_bucket/{conversation_id}/{doc_key}/_bm25_chunks/chunk_*.txt`

**`app/main.py` — webhook on job done:**
```python
POST {ai_agent_ingest_url}/rag/ingest
Body: {"conversation_id": "...", "doc_key": "..."}
```
- Log WARNING on failure, retry once after 5 s, then give up

### 3. `services/ai-agent`

**New config fields (`app/config.py`):**
```python
ARTICLES_MINIO_ENDPOINT: str = "articles-minio:9000"
ARTICLES_MINIO_ACCESS_KEY: str = "minioadmin"
ARTICLES_MINIO_SECRET_KEY: str = "minioadmin"
ARTICLES_MINIO_PARSED_BUCKET: str = "parsed-chunks"
```

**New endpoint `app/api/rag_ingest.py` (or added to `main.py`):**
```
POST /rag/ingest
Body: {conversation_id: str, doc_key: str}
```
- No authentication (internal endpoint)
- Downloads all files under `parsed-chunks/{conversation_id}/{doc_key}/` from articles-minio
- MinIO key → local path mapping (example for DOI `10.1234/test`, conversation `conv-abc`):
  | MinIO key | Local path |
  |---|---|
  | `conv-abc/10_1234_test/_chunks/chunk_000.md` | `data-rag/sources/conv-abc/corpus_processed/10_1234_test_chunks/chunk_000.md` |
  | `conv-abc/10_1234_test/_bm25_chunks/chunk_000.txt` | `data-rag/sources/conv-abc/corpus_processed/10_1234_test_bm25_chunks/chunk_000.txt` |
  Transformation rule: strip `{conversation_id}/{doc_key}/` prefix, then replace `_chunks/` → `{doc_key}_chunks/` and `_bm25_chunks/` → `{doc_key}_bm25_chunks/`
- Deletes `_RETRIEVER_REGISTRY[conversation_id]` under `_REGISTRY_LOCK` (forces lazy rebuild of the child scope retriever)
- Returns `{"status": "ok"}` on success, `500` on MinIO errors
- Log MinIO errors with `logging.exception` to capture full traceback

**`app/tools/rag.py` — new `MultiScopeRetriever`:**
```python
class MultiScopeRetriever:
    def __init__(self, retrievers: list[BM25DenseRankFusionRetriever], rrf_k: int = 60) -> None: ...
    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        # query all child retrievers, fuse with RRF, return top_k
```

**`app/tools/rag.py` — updated retriever resolution:**

`_RETRIEVER_REGISTRY` caches individual scope retrievers (`BM25DenseRankFusionRetriever`) only. The `MultiScopeRetriever` is constructed fresh on each call to `_get_retriever_for_conversation` — it is not cached — so that stale scope composition is never served. Invalidating `_RETRIEVER_REGISTRY[conversation_id]` under `_REGISTRY_LOCK` causes the next `_get_retriever_for_scope(conversation_id)` call to rebuild from the updated corpus files.

```python
def _get_retriever_for_conversation(
    conversation_id: str | None,
) -> BM25DenseRankFusionRetriever | MultiScopeRetriever:
    default = _get_retriever_for_scope("default")
    if not conversation_id:
        return default
    conv_dir = Path(settings.RAG_SOURCES_DIR) / conversation_id
    if not conv_dir.exists():
        return default
    conv = _get_retriever_for_scope(conversation_id)
    return MultiScopeRetriever([default, conv])
```

**`app/tools/rag.py` — `rag_search` scope injection:**

`config` must be annotated with `InjectedToolArg` so LangChain does not expose it to the LLM as a tool parameter:

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
    return _run_rag_query(query=query, top_k=top_k, config=config)
```

`_run_rag_query` is updated to accept an optional `config` and preserves all existing guards:

```python
def _run_rag_query(query: str, top_k: int, config: RunnableConfig | None = None) -> str:
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
        return f"RAG data is not initialized correctly. Missing path: {exc}."
    except ImportError as exc:
        logger.exception("Dense retriever dependency missing")
        return (
            "RAG dense retriever dependencies are missing. "
            f"Install sentence-transformers and numpy. Details: {exc}"
        )
    except Exception as exc:
        logger.exception("RAG search failed")
        return f"RAG search failed: {exc}"
```

All five existing guards (`RAG_ENABLED`, empty-query, `safe_top_k`, `FileNotFoundError`, `ImportError`) are preserved. The only change is replacing `_get_retriever_for_scope(settings.RAG_DEFAULT_SOURCE)` with `_get_retriever_for_conversation(conversation_id)` — when `conversation_id` is `None` or the scope dir does not exist, the behavior is identical to the current default-scope retrieval.

**`app/agent.py` — propagate `RunnableConfig` through `call_tools`:**

The current `call_tools` node calls `tool.invoke(tool_call["args"])` without passing a config, so `InjectedToolArg` fields are never populated. The node must be updated to receive and forward the config:

```python
from langchain_core.runnables import RunnableConfig

def call_tools(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    last_message = state["messages"][-1]
    results = []
    for tool_call in last_message.tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"], config=config)
        results.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))
    return {"messages": results}
```

LangGraph automatically passes the graph's `RunnableConfig` as the second argument to any node that declares it. No other changes to the graph wiring are needed.

**`app/main.py` / `app/agent.py`:**
- `ChatRequest` schema gains `conversation_id: str = ""`
- Pass `conversation_id` in **both** agent invocation paths (sync and streaming):
  ```python
  # sync chat endpoint
  agent_config = {"configurable": {"conversation_id": request.conversation_id}}
  result = await agent.ainvoke({"messages": langchain_messages}, config=agent_config)

  # streaming chat endpoint
  async for event in agent.astream_events(
      {"messages": langchain_messages},
      version="v2",
      config=agent_config,  # <-- required; omitting this means rag_search never sees conversation_id
  ):
  ```

### 4. `backend/app/worker/tasks/chat.py`
- `POST /fetch` body gains `conversation_id` field (already available in the Celery task context)

### 5. `compose.yml`
- `pdf-parser` service: add `ARTICLES_MINIO_*` env vars pointing at `articles-minio`
- `ai-agent` service: add `ARTICLES_MINIO_*` env vars pointing at `articles-minio`
- `pdf-parser` service: add `AI_AGENT_INGEST_URL=http://ai-agent:8000`

## Data Layout

```
data-rag/
  sources/
    default/                          ← shared base corpus (unchanged)
      corpus_processed/
      indexes/
    {conversation_id}/                ← created on first ingest for this conversation
      corpus_processed/
        {doc_key}_chunks/
          chunk_000.md
          chunk_001.md
          ...
        {doc_key}_bm25_chunks/
          chunk_000.txt
          chunk_001.txt
          ...
      indexes/                        ← built lazily on first rag_search
        bm25_index.json
        nomic_dense/
```

## Error Handling

| Failure point | Behavior |
|---|---|
| `POST /fetch` with `conversation_id` fails | Log WARNING in Celery worker, skip — chat unaffected |
| article-fetcher → pdf-parser webhook fails | Log WARNING in article-fetcher, job still marked `done` |
| pdf-parser MinIO upload fails | Job → `failed`, no webhook sent to ai-agent |
| pdf-parser → ai-agent ingest webhook fails | Log WARNING, retry once after 5 s, then give up |
| ai-agent MinIO download fails in `/rag/ingest` | Log ERROR, return `500` — pdf-parser retry will re-trigger |
| Partial chunk download | Incomplete dir → retriever build raises, caught in `_run_rag_query`, returns error string |
| `rag_search` before ingest completes | Conversation scope dir absent → falls back to `default` seamlessly |
| `conversation_id` absent in config | Falls back to `default` scope — existing behavior unchanged |

## Testing

- **article-fetcher**: extend tests for `conversation_id` in `FetchRequest`, job record, and webhook payload
- **pdf-parser**: `test_api.py` — ingest webhook fires with correct `conversation_id`; `test_minio_store.py` — conversation-scoped upload keys
- **ai-agent `/rag/ingest`**: unit tests with mocked MinIO and mocked registry invalidation
- **`MultiScopeRetriever`**: unit tests for merged results, fallback when one scope empty
- **`rag_search` scope injection**: test `RunnableConfig` routing, missing config fallback

## Files Changed

| File | Change |
|------|--------|
| `services/article-fetcher/app/main.py` | Add `conversation_id` to `FetchRequest`, job record, webhook payload |
| `services/pdf-parser/app/config.py` | Add MinIO + ai-agent ingest URL config |
| `services/pdf-parser/app/main.py` | Accept `conversation_id` in job schema; fire ingest webhook |
| `services/pdf-parser/app/minio_store.py` | Conversation-scoped upload/download keys; add `parsed-chunks` bucket |
| `services/ai-agent/app/config.py` | Add `ARTICLES_MINIO_*` settings |
| `services/ai-agent/app/main.py` | Register `/rag/ingest` route; pass `conversation_id` in agent config |
| `services/ai-agent/app/schemas.py` | Add `conversation_id` to `ChatRequest` |
| `services/ai-agent/app/tools/rag.py` | Add `MultiScopeRetriever`; update retriever resolution; inject scope via `RunnableConfig` |
| `backend/app/worker/tasks/chat.py` | Pass `conversation_id` in `POST /fetch` body |
| `compose.yml` | Add MinIO + ingest URL env vars to pdf-parser and ai-agent |
