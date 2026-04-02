# Async Tool Pipeline Design

**Date:** 2026-04-02
**Status:** Approved
**Branch:** osn-pre-main

## Problem

`literature_search` blocks the LangGraph agent for up to 125 seconds (5 × S2 retry waits). The user sees nothing until the entire ReAct loop completes. Article parsing (Docling) similarly produces RAG content that the agent never uses in its response because it arrives after the agent has already replied.

## Goal

Fast tools (RAG, chemistry tools) produce an immediate agent response. Slow operations (S2 search, article parsing) run in the background and trigger follow-up agent responses when they complete.

## User-visible Flow

```
1.  User sends request
2.  Agent calls literature_search → returns "Search queued" immediately
3.  Agent calls other tools (rag_search, chemistry tools)
4.  Agent responds with initial answer  ← user sees this fast
5.  [background] S2 search completes
6.  Background message injected: "Literature Search Results: ..."
7.  Agent re-invoked → responds with abstract-level analysis
8.  [background] Article parsing finishes, RAG index updated
9.  Background worker calls rag_search programmatically, injects result
10. Agent re-invoked → responds with document-level analysis
```

## New Concepts

### Background Messages (`role="background"`)

Messages injected into the conversation by the pipeline, not by the user. Stored in the `chat_message` table with `role="background"` and a `metadata` JSON field. The agent sees them as `HumanMessage` with a `[Background Update]` prefix. The frontend reads `metadata.variant` (`"info"` or `"error"`) to choose card style — avoids fragile string-prefix parsing.

### `run_agent_continuation` Celery Task

Re-invokes the agent when background work completes. Loads full conversation history (including the newly saved background message), calls ai-agent SSE stream, forwards tokens to Redis pubsub (same path as `process_chat_message`), saves the assistant response to DB.

Uses a per-conversation queue to prevent concurrent streaming to the same channel:
- Redis key `conv_processing:{conversation_id}` — set while a task is active (SETNX)
- Redis list `conv_pending:{conversation_id}` — queued continuation signals

If `conv_processing` is already set, the task pushes a signal to `conv_pending` and exits. When the active task finishes, it pops from `conv_pending` and dispatches a new `run_agent_continuation` if needed. The dispatched task always reads fresh history, so it picks up all background messages that arrived while waiting.

## Architecture

```
literature_search tool
  │ POST /internal/queue-background-tool
  ▼
backend /internal router
  │ dispatches Celery task
  ▼
run_s2_search (Celery, chat queue)
  │ POST ai-agent /internal/s2-search  ← blocking, ≤15s
  ├─ FAILURE/NO PAPERS → save error background message, publish event, STOP
  │                       user can retry via "Retry Search" button
  └─ SUCCESS → save S2 results background message
             │ publish background_update SSE event
             │ submit article downloads (_submit_article_jobs reuse)
             │ dispatch run_agent_continuation  ← abstract response
             └ dispatch monitor_ingestion(conversation_id, job_ids)
                      ↓
monitor_ingestion (Celery, retries every 10s, max 20 min)
  │ polls article-fetcher AND pdf-parser status for each job_id
  │
  │ STOP if ALL article-fetcher jobs failed (nothing downloaded)
  │       → error background message
  │
  │ STOP if ANY pdf-parser job failed (partial content untrustworthy)
  │       → error background message
  │       → user can retry parse via ArticleDownloadsCard
  │       → "Notify Agent" button appears on successful retry
  │
  │ continue while any article-fetcher job still running (wait for downloads)
  │ continue while any pdf-parser job still running  (wait for parsing)
  │
  └ when all pdf-parser jobs "completed" → save [Background: New Papers Available]
                                         → dispatch run_agent_continuation

run_agent_continuation (Celery, chat queue)
  │ acquire conv_processing lock (or queue if busy)
  │ load conversation history
  │ call ai-agent SSE stream (all tools available)
  │ forward tokens → Redis pubsub → frontend
  └ save assistant message to DB
```

## Component Changes

### ai-agent (`services/ai-agent/`)

| File | Change |
|---|---|
| `app/config.py` | Add `BACKEND_INTERNAL_URL = "http://backend:8000"` |
| `app/tools/search.py` | `literature_search` POSTs to backend internal endpoint with `{conversation_id, query}`, returns `"Literature search queued. Results will appear in this conversation shortly."` |
| `app/main.py` | New `POST /internal/s2-search` endpoint (blocking S2 search, returns raw JSON). `/rag/ingest` unchanged. |
| `app/agent.py` | `convert_messages`: `role="background"` → `HumanMessage(content=f"[Background Update]\n{content}")` |

### backend (`backend/`)

| File | Change |
|---|---|
| `app/api/routes/internal.py` | New file. `POST /internal/queue-background-tool` — no auth, Docker-internal only. Queues `run_s2_search` Celery task. |
| `app/api/routes/articles.py` | Add `POST /api/v1/conversations/{id}/retry-s2-search` proxy (exposed to frontend for retry button) |
| `app/api/routes/conversations.py` (or articles) | Add `POST /api/v1/conversations/{id}/trigger-rag-continuation` — saves `[Background: New Papers Available]` message + dispatches `run_agent_continuation`. Shares helper with `monitor_ingestion` success path. |
| `app/api/main.py` | Mount `/internal` router |
| `app/worker/tasks/continuation.py` | New file. `run_s2_search`, `monitor_ingestion`, and `run_agent_continuation` tasks. |
| `app/worker/prompts.py` | New file. Background message prompt templates: `S2_RESULTS`, `S2_NO_RESULTS`, `S2_FAILURE`, `PAPERS_INGESTED`, `PARSING_FAILED`. |
| `app/worker/tasks/chat.py` | `process_chat_message` acquires `conv_processing` in `try/finally` — always released even on timeout or crash. `run_s2_search` and `monitor_ingestion` never touch this lock. |
| `app/models.py` | Allow `"background"` as message role (string field, no migration needed if unconstrained) |

### frontend (`frontend/`)

| File | Change |
|---|---|
| `src/components/Chat/MessageBubble.tsx` | Detect `role="background"`, render as muted info card |
| `src/components/Chat/BackgroundMessageCard.tsx` | New component. Shows background update content. Error variant shows Retry button. |
| `src/components/Chat/ArticleDownloadsCard.tsx` | Show "Notify Agent" button when: all jobs terminal (completed or failed) AND ≥1 failed AND ≥1 succeeded. This is exactly when `monitor_ingestion` stopped and there's still something in RAG. Button calls `POST /api/v1/conversations/{id}/trigger-rag-continuation`. |
| `src/hooks/useConversationSSE.ts` | Handle `background_update` event (triggers scroll) |


## Internal Endpoint Contract

```
POST /internal/queue-background-tool
{
  "type": "s2_search",
  "conversation_id": "uuid",
  "query": "string",
  "max_results": 5
}
→ 202 Accepted

POST /internal/s2-search  (ai-agent)
{
  "query": "string",
  "max_results": 5
}
→ { "papers": [...] }
```

## Prompt Templates

All background message content is defined in `backend/app/worker/prompts.py` and imported by `run_s2_search` and `monitor_ingestion`. Templates use Python f-string interpolation.

## Background Message Formats

**S2 success:**
```
[Background: Literature Search Results]
Your earlier search for "{query}" found {n} papers:

1. Title — Authors (Year) — DOI
   Abstract: ...

2. ...

Please analyze these results and provide relevant information.
```

**S2 failure:**
```
[Background: Literature Search Failed]
Semantic Scholar returned an error: {reason}.
```

**Papers ingested (triggers RAG continuation):**
```
[Background: New Papers Available]
Articles from your earlier literature search have been parsed and added to the knowledge base.
Please search the RAG corpus for information relevant to this conversation.
```

**Parsing failed:**
```
[Background: Parsing Failed]
One or more articles could not be parsed.
```

## Error Handling

| Scenario | Behaviour |
|---|---|
| S2 fails | Error background message + Retry button. No article downloads, no monitor_ingestion, no continuation. User retries manually. |
| S2 returns 0 papers | Info card (no Retry button). No article downloads, no monitor_ingestion, no continuation. |
| All downloads fail | Error background message, pipeline stops. |
| ≥1 download succeeds | Pipeline continues with successfully downloaded articles only. |
| Any parse fails | Error background message, no RAG continuation. User retries via ArticleDownloadsCard → "Notify Agent" button on success. |
| monitor_ingestion times out (20 min) | Task exhausts retries, silently dropped |
| Continuation task times out | Frontend already has initial response; follow-up silently dropped |
| New user message races with continuation | `process_chat_message` sets `conv_processing`; continuation queues in `conv_pending` and runs after |
| `process_chat_message` crashes / times out | `try/finally` releases lock unconditionally — conversation unblocked |
| Background pipeline error (S2/parse failure) | Fully isolated — saves background message, returns normally, never touches `conv_processing` |

## Testing

### Unit tests (no running stack)

- `run_s2_search`: mock S2 call → assert background message saved, continuation dispatched; mock failure → assert error message saved, continuation NOT dispatched
- `run_agent_continuation`: mock ai-agent stream → assert tokens forwarded to pubsub, assistant message saved
- `convert_messages`: `role="background"` → `HumanMessage` with `[Background Update]` prefix
- `literature_search` tool: mock backend endpoint → assert returns "queued", assert POST made with correct payload

### Integration tests (running stack)

- Send literature query → assert initial response → assert background message → assert follow-up response
- Upload PDF → wait for parse → assert RAG background message → assert follow-up response

### Frontend

- `role="background"` message renders as info card, not chat bubble
- Error card shows Retry button; click POSTs to correct endpoint
- Existing E2E chat flow passes (regression)
