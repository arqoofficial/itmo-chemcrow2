# Async Tool Pipeline Design

**Date:** 2026-04-02  
**Status:** Approved  
**Scope:** ChemCrow2 — multi-turn async agent responses for slow tools

---

## Problem

`literature_search` (Semantic Scholar API) blocks the entire LangGraph agent loop for up to 125 seconds due to rate-limit retries. The user sees nothing until all retries exhaust. Similarly, article parsing (Docling) takes tens of seconds — when it finishes and new RAG content is available, the agent is never told.

---

## Goal

Fast tools (RAG, RDKit, safety checks) produce an immediate agent response. Slow operations (S2 search, PDF parsing) run in the background and trigger follow-up agent responses automatically when they complete.

---

## User-Visible Flow

1. User sends a message asking for literature on topic X
2. Agent calls `rag_search` (fast), calls `literature_search` → returns **"Search queued"** immediately
3. Agent responds with initial answer using RAG results only (~5s)
4. *(background)* S2 search completes → follow-up agent message appears with abstract analysis
5. *(background)* PDF parsing completes → RAG index updated → follow-up agent message with deep document analysis

---

## New Concepts

### Background Messages (`role="background:{type}"`)

Messages injected into the conversation by the pipeline, not by the user. Stored in DB alongside regular messages. The role string encodes the variant: `background:s2_success`, `background:s2_failed`, `background:rag_result`, `background:rag_empty`. The agent sees them as `HumanMessage` with a `[Background Update]` prefix (role variant stripped). The frontend checks `role.startsWith("background")` and splits on `:` to pick the card style.

Examples:
```
role="background:s2_success"
[Background: Literature Search Results]
Found 5 papers on synthesis of X:
- Paper 1 ...

role="background:s2_failed"
[Background: Literature Search Failed]
Semantic Scholar returned a 429 after all retries.

role="background:rag_empty"
[Background: RAG Search - No Results]
No relevant content found in the newly parsed documents.
```

### `run_agent_continuation` Celery Task

Re-invokes the agent when background work completes. Loads full conversation history (which now includes the background message), calls the ai-agent SSE stream, forwards tokens to Redis pubsub (user sees tokens streaming), saves the assistant response to DB. Behaves identically to `process_chat_message` except it is triggered by the pipeline, not by a user message.

---

## Architecture

### Data Flow

```
── Fast path (unchanged except literature_search) ──────────────────────────

User → backend → process_chat_message Celery task
               → ai-agent SSE stream → LangGraph loop:
                   rag_search            (~1s, unchanged)
                   literature_search     → POST backend /internal/queue-background-tool
                                         ← "Search queued"
                   [other fast tools]
                   LLM final answer      → streamed to user

── S2 background path ──────────────────────────────────────────────────────

run_s2_search Celery task
  → POST ai-agent /internal/s2-search   (blocking, max ~15s)
  ← papers JSON
  → save role="background" message to DB
  → publish background_update SSE event
  → dispatch run_agent_continuation
      → load full conversation history
      → call ai-agent SSE stream
      → stream tokens to frontend
      → save assistant message to DB

── RAG ingest path (modified) ──────────────────────────────────────────────

pdf-parser → POST ai-agent /rag/ingest  (existing endpoint, modified)
  → build RAG index                     (existing)
  → fetch last user message from conversation history
  → call rag_search(query, conversation_id) programmatically
  → if results non-empty:
      POST backend /internal/queue-background-tool
          {type: "rag_result", conversation_id, content: rag_results}
      → backend saves role="background" message
      → dispatches run_agent_continuation
  → if results empty:
      POST backend /internal/queue-background-tool
          {type: "rag_no_results", conversation_id}
      → backend saves informational background message
      → no run_agent_continuation dispatched
```

---

## Component Changes

### ai-agent service

**`config.py`**
- Add `BACKEND_INTERNAL_URL: str = "http://backend:8000"`

**`tools/search.py`** — `literature_search` tool
- Remove blocking S2 logic from tool body
- Get `conversation_id` from `_CURRENT_CONV_ID` ContextVar
- POST to `BACKEND_INTERNAL_URL/internal/queue-background-tool` with `{type: "s2_search", conversation_id, query, max_results}`
- Return `"Literature search queued. Results will appear in this conversation shortly."`

**`main.py`** — new internal endpoint
- `POST /internal/s2-search` — runs the actual blocking S2 API call (logic extracted from old `literature_search`), returns raw papers JSON. Called only by the backend Celery task; not exposed externally.

**`main.py`** — `/rag/ingest` (modified)
- After building RAG index, fetch last human message from conversation history via `GET BACKEND_INTERNAL_URL/internal/conversations/{id}/last-user-message`
- Call `rag_search(query=last_user_message, conversation_id=conversation_id)` directly (not via LLM)
- POST result (or no-result signal) to `BACKEND_INTERNAL_URL/internal/queue-background-tool`

**`agent.py`** — `convert_messages`
- Add case: `role="background"` → `HumanMessage(content=f"[Background Update]\n{content}")`

### backend service

**`app/api/routes/internal.py`** (new file)
- `POST /internal/queue-background-tool` — accepts `{type, conversation_id, ...}`, dispatches appropriate Celery task. No auth (Docker-internal only). Mount at `/internal`.
- `GET /internal/conversations/{id}/last-user-message` — returns last message with `role="user"` for a conversation.

**`app/worker/tasks/continuation.py`** (new file)
- `run_s2_search(conversation_id, query, max_results)` — stores `query` in Redis at `conversation:{id}:last_s2_query` (TTL 7d), calls `AI_AGENT_URL/internal/s2-search`, formats result, saves `role="background:s2_success"` message, dispatches `run_agent_continuation`. On failure: saves `role="background:s2_failed"` message, does NOT dispatch continuation.
- `run_agent_continuation(conversation_id)` — loads history, calls ai-agent SSE stream via `_process_streaming` (shared from `chat.py`), saves assistant message, publishes SSE events.

**`app/models.py`**
- `ChatMessage.role` — verify it's a plain `str` field (no enum constraint). No migration needed.

**`app/api/routes/conversations.py`** (or new file)
- `POST /api/v1/conversations/{id}/retry-s2-search` — frontend-facing proxy; reads original query from Redis key `conversation:{id}:last_s2_query`, dispatches a new `run_s2_search` task.

### frontend

**`MessageBubble.tsx`**
- Detect `message.role.startsWith("background")`, render as muted info card instead of chat bubble.
- Split role on `:` to get variant: `s2_success` (teal), `s2_failed` (red + Retry button), `rag_result` (teal), `rag_empty` (muted grey).

**`useConversationSSE.ts`**
- Handle new `background_update` SSE event — triggers scroll to bottom; no additional state change needed (content arrives via normal `token`/`message` events from `run_agent_continuation`).

---

## Error Handling

| Scenario | Action |
|---|---|
| S2 search fails (network / all retries exhausted) | Save error background message, publish SSE, show Retry button in UI. No continuation dispatched. |
| S2 returns 0 papers | Save "no papers found" background message. No continuation dispatched. |
| RAG search returns empty after ingest | Save "no results" background message. No continuation dispatched. |
| `run_agent_continuation` times out | Uses same `CHAT_TASK_SOFT_TIME_LIMIT` as `process_chat_message`. Initial response already visible; follow-up silently dropped. |
| Multiple PDFs parsed for same conversation | Each triggers its own `run_agent_continuation`. Accepted — each brings new content. |
| New user message arrives while continuation pending | Celery processes both independently; both responses saved. Acceptable race for now. |

---

## Testing

### Unit tests (no running stack)
- `run_s2_search`: mock S2 HTTP → assert background message saved, continuation dispatched; mock failure → assert error message saved, continuation NOT dispatched
- `run_agent_continuation`: mock ai-agent SSE → assert tokens forwarded to Redis, assistant message saved
- `convert_messages`: `role="background"` → `HumanMessage` with `[Background Update]` prefix
- `literature_search` tool: mock backend endpoint → assert returns "queued", assert POST sent with correct payload
- `/rag/ingest` modification: mock rag_search empty → assert no continuation; mock non-empty → assert background message + continuation dispatched

### Integration tests (running stack)
- Full S2 path: send literature query → assert initial response arrives → assert background message appears → assert follow-up response arrives
- RAG path: upload PDF → wait for parse → assert RAG background card appears → assert follow-up response

### Frontend
- Background message with `role="background"` renders as info card
- Error card shows Retry button; click POSTs to correct endpoint
- Playwright regression: existing chat flow unaffected

---

## Out of Scope

- Deduplication of concurrent `run_agent_continuation` tasks for the same conversation
- Cancelling a queued S2 search after the user sends a new message
- Async handling for tools other than `literature_search`
