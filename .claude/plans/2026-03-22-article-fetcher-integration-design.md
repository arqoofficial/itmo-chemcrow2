# Article Fetcher Integration — Design Spec

**Date:** 2026-03-22

## Overview

Integrate the `article-fetcher` microservice into the ChemCrow2 app so that whenever the AI agent calls `literature_search`, all returned DOIs are automatically submitted to the fetcher. The UI displays inline download status cards in the chat. On every subsequent user message, the current download status for all jobs in the conversation is injected into the AI agent's context so it can reference available articles. The article-fetcher is also wired to notify a future article processor via webhook when downloads complete.

## Architecture

```
literature_search tool_end event
    │
    ▼
chat.py (Celery task) — intercepts tool_end for "literature_search"
    │  ├── regex-extract DOIs from output text
    │  ├── POST /fetch to article-fetcher per DOI → job_id
    │  ├── store {doi, job_id} pairs in Redis: conversation:{conversation_id}:article_jobs (TTL 7d)
    │  └── publish "article_downloads" SSE event to Redis conversation channel
    │
    ▼
Redis pub/sub → backend events.py → frontend SSE
    │
    ▼
useConversationSSE hook → onArticleDownloads callback
    │
    ▼
ArticleDownloadsCard (React) — polls GET /api/v1/articles/jobs/{job_id} every 3s
    │                          until status is "done" or "failed"
    ▼
article-fetcher (job done) → optional webhook POST to ARTICLE_PROCESSOR_WEBHOOK_URL


User sends new chat message
    │
    ▼
chat.py — reads conversation:{conversation_id}:article_jobs from Redis
    │  ├── for each job: GET {ARTICLE_FETCHER_URL}/jobs/{job_id}
    │  └── builds status summary string
    │
    ▼
status summary injected as system message prepended to messages_payload
    │
    ▼
AI agent receives context: which articles are available, downloading, or failed
```

## SSE Event Shape

New event type emitted on the conversation Redis channel:

```json
{
  "event": "article_downloads",
  "jobs": [
    {"doi": "10.1038/s41586-021-03819-2", "job_id": "550e8400-..."},
    {"doi": "10.1021/acs.nanolett.1c02548", "job_id": "661f9511-..."}
  ]
}
```

Papers with `DOI: N/A` in the tool output are skipped.

## Components

### 1. `backend/app/core/config.py`
Add:
```
ARTICLE_FETCHER_URL: str = "http://article-fetcher:8200"
```

### 2. `backend/app/worker/tasks/chat.py`

**On `tool_end` for `literature_search`:**
- Extract DOIs via regex: `DOI:\s*([^\s\n]+)` where value is not `N/A`
- For each DOI, call `POST {ARTICLE_FETCHER_URL}/fetch` with `{"doi": "..."}` (fire-and-forget, log failures, never raise)
- Collect `{doi, job_id}` pairs
- Store collected pairs by appending to Redis list key `conversation:{conversation_id}:article_jobs` (JSON-encoded per element, TTL 7 days)
- If any jobs created: publish `article_downloads` event to Redis conversation channel

**Deduplication:** Before calling `POST /fetch` for a DOI, read `conversation:{conversation_id}:article_jobs` and skip any DOI already present. Reuse the existing job_id for those. This prevents duplicate fetch jobs when `literature_search` is called multiple times in the same conversation.

**On every new user message (before calling the AI agent):**
- Read `conversation:{conversation_id}:article_jobs` from Redis (empty list if key absent)
- For each stored job, call `GET {ARTICLE_FETCHER_URL}/jobs/{job_id}` (skip on error)
- Build a status block (only if there are any reachable jobs):
  ```
  [Article Download Status]
  - 10.1038/s41586-021-03819-2: available
  - 10.1021/acs.nanolett.1c02548: downloading
  - 10.1016/failed.doi: failed
  ```
  Labels: `available` (done), `downloading` (pending/running), `failed`.
- Inject by **prepending a `user` role message** to `messages_payload`. Do NOT use `system` role — the LangGraph agent's `call_model` silently drops the hardcoded `SYSTEM_PROMPT` if `messages[0]` is already a `SystemMessage`.

Error handling: HTTP errors or connection failures are logged at WARNING level and skipped — a failed status check must not break the chat response. If all status fetches fail, omit the status block entirely.

### 3. `backend/app/api/routes/articles.py` (new)
Proxy route:
```
GET /api/v1/articles/jobs/{job_id}
```
- Requires authentication (CurrentUser)
- Calls `GET {ARTICLE_FETCHER_URL}/jobs/{job_id}`
- Returns the job response as-is (job_id, status, url, error)
- Returns 404 if article-fetcher returns 404

### 4. `backend/app/api/main.py`
Register the articles router under `/api/v1`.

### 5. `services/article-fetcher/app/config.py`
Add optional field:
```python
article_processor_webhook_url: str = ""
```

### 6. `services/article-fetcher/app/main.py`
In `_run_fetch`, after updating job status to "done":
- If `settings.article_processor_webhook_url` is set, POST `{job_id, doi, object_key, status: "done"}` to it
- Use the `doi` closure parameter already in scope (do not re-read from Redis)
- Log failures at WARNING, never raise

### 7. `frontend/src/client/chatTypes.ts`
Add:
```ts
export type ArticleDownloadJob = {
  doi: string
  job_id: string
}
```
Add to `SSEEvent` union:
```ts
| { event: "article_downloads"; data: { jobs: ArticleDownloadJob[] } }
```

### 8. `frontend/src/hooks/useConversationSSE.ts`
- Add `onArticleDownloads?: (jobs: ArticleDownloadJob[]) => void` to options
- Handle `article_downloads` event: call `onArticleDownloads?.(data.jobs)`

### 9. `frontend/src/components/Chat/ArticleDownloadsCard.tsx` (new)
Props: `jobs: ArticleDownloadJob[]`

- For each job, uses React Query with `refetchInterval: 3000` (stops when status is `done` or `failed`)
- Displays a card with header "Fetching PDFs..." and a row per job:
  - DOI (truncated)
  - Status badge: pending/running → spinner, done → ✓, failed → ✗
  - When done: DOI becomes a link to the presigned URL

### 10. Chat rendering
In `ChatWindow.tsx`, maintain a `useState<ArticleDownloadJob[][]>` array (a list of batches, one per `article_downloads` event). Each new `article_downloads` event appends a batch; this state is **never cleared** on message commit — it must outlive the streaming lifecycle. Render the `ArticleDownloadsCard` list (one per batch, keyed by index) below the last settled `MessageBubble` and above the streaming bubble / `bottomRef`, so the cards remain visible after the assistant message is committed and `pendingToolCalls` is cleared.

### 11. `compose.yml`
The `articles-minio` and `article-fetcher` services are **already present** in `compose.yml`. The only missing change is adding `ARTICLE_FETCHER_URL` to the `celery-worker` environment block:

```yaml
# under celery-worker → environment:
ARTICLE_FETCHER_URL: http://article-fetcher:8200
```

This ensures the Celery worker (the only process that calls the article-fetcher) can resolve the service by its Docker Compose name.

## Error Handling

| Failure | Behavior |
|---|---|
| article-fetcher unreachable on submit | Log WARNING, skip — chat response unaffected |
| article-fetcher unreachable on status check | Log WARNING, skip job from status block |
| DOI fetch fails (sci-hub) | Job status → "failed", shown as `failed` in status block and UI card |
| Job not found in Redis (expired) | Skip from status block; backend proxy returns 404 |
| Webhook POST fails | Log WARNING, job still marked done |
| All status checks fail | Omit status block from AI context entirely |

## Article Processor Readiness

`ARTICLE_PROCESSOR_WEBHOOK_URL` is empty by default — the webhook code path is a no-op until the processor is built. When the processor exists, set the env var to its ingest endpoint. No further changes to the fetcher are needed.

Webhook payload:
```json
{
  "job_id": "...",
  "doi": "10.xxx/yyy",
  "object_key": "uuid.pdf",
  "status": "done"
}
```
