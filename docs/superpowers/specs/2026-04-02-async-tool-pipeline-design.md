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

Messages injected into the conversation by the pipeline, not by the user. Stored in the `chat_message` table with `role="background"`. The agent sees them as `HumanMessage` with a `[Background Update]` prefix. The frontend renders them as info cards (not user/assistant bubbles).

### `run_agent_continuation` Celery Task

Re-invokes the agent when background work completes. Loads full conversation history (including the newly saved background message), calls ai-agent SSE stream, forwards tokens to Redis pubsub (same path as `process_chat_message`), saves the assistant response to DB.

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
  │ save role="background" message to DB
  │ publish background_update SSE event
  │ dispatch run_agent_continuation
  ▼
run_agent_continuation (Celery, chat queue)
  │ load conversation history
  │ call ai-agent SSE stream
  │ forward tokens → Redis pubsub → frontend
  └ save assistant message to DB

run_s2_search
  │ also submits article downloads (_submit_article_jobs reuse)
  │ saves article-fetcher job IDs → dispatches monitor_ingestion(conversation_id, job_ids)
  ▼
monitor_ingestion (Celery, retries every 10s, max 20 min)
  │ polls GET http://pdf-parser:8300/jobs/{job_id} for each job_id
  │ when all "completed" → save role="background" message
  │                      → dispatch run_agent_continuation
  │ /rag/ingest stays untouched — no notification logic inside it
  └ pdf-parser stays untouched
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
| `app/api/main.py` | Mount `/internal` router |
| `app/worker/tasks/continuation.py` | New file. `run_s2_search`, `monitor_ingestion`, and `run_agent_continuation` tasks. |
| `app/models.py` | Allow `"background"` as message role (string field, no migration needed if unconstrained) |

### frontend (`frontend/`)

| File | Change |
|---|---|
| `src/components/Chat/MessageBubble.tsx` | Detect `role="background"`, render as muted info card |
| `src/components/Chat/BackgroundMessageCard.tsx` | New component. Shows background update content. Error variant shows Retry button. |
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
| S2 fails | Save error background message, show to user with Retry button, do NOT dispatch continuation |
| S2 returns 0 papers | Info card (no Retry button — not an error), no continuation |
| Parsing fails | Error background message, no continuation |
| monitor_ingestion times out (20 min) | Task exhausts retries, silently dropped |
| Continuation task times out | Frontend already has initial response; follow-up silently dropped |
| New user message races with continuation | Both tasks run; conversation is append-only; both responses saved — acceptable for now |

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
