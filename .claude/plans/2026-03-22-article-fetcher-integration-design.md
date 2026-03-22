# Article Fetcher Integration — Design Spec

**Date:** 2026-03-22

## Overview

Integrate the `article-fetcher` microservice into the ChemCrow2 app so that whenever the AI agent calls `literature_search`, all returned DOIs are automatically submitted to the fetcher. The UI displays inline download status cards in the chat. The article-fetcher is also wired to notify a future article processor via webhook when downloads complete.

## Architecture

```
literature_search tool_end event
    │
    ▼
chat.py (Celery task) — intercepts tool_end for "literature_search"
    │  ├── regex-extract DOIs from output text
    │  ├── POST /fetch to article-fetcher per DOI → job_id
    │  └── publish "article_downloads" SSE event to Redis
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
After processing `tool_end` for `literature_search`:
- Extract DOIs via regex: `DOI:\s*([^\s\n]+)` where value is not `N/A`
- For each DOI, call `POST {ARTICLE_FETCHER_URL}/fetch` with `{"doi": "..."}` (fire-and-forget, log failures, never raise)
- Collect `{doi, job_id}` pairs
- If any jobs created: publish `article_downloads` event to Redis conversation channel

Error handling: HTTP errors or connection failures are logged at WARNING level and skipped — a failed fetch submission must not break the chat response.

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
| article-fetcher unreachable | Log WARNING, skip — chat response unaffected |
| DOI fetch fails (sci-hub) | Job status → "failed", error shown in UI card |
| Job not found in Redis | Backend proxy returns 404 |
| Webhook POST fails | Log WARNING, job still marked done |

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
