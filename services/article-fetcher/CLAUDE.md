# Article Fetcher Service

Queues and executes article downloads from Sci-Hub by DOI, stores PDFs in MinIO, then notifies PDF Parser.

## Dev Commands

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8200 --reload
```

## Data Flow

```
POST /fetch {doi, conversation_id}  ← backend API
    ↓
Redis queue (job tracking)
    ↓
curl-based Sci-Hub scraper (tries mirrors: sci-hub.ru, sci-hub.ee)
    ↓
MinIO articles bucket  →  POST http://pdf-parser:8300/jobs (webhook)
```

## Project Structure

```
app/
├── main.py     # FastAPI — POST /fetch, GET /jobs/{job_id}
├── fetcher.py  # curl subprocess scraper — downloads PDF by DOI from Sci-Hub mirrors
├── storage.py  # MinIO client (articles bucket)
├── config.py   # Settings
└── schemas.py  # Request/response models
```

## Gotchas

- **No scidownl** — `fetcher.py` uses `subprocess.run(["curl", ...])` directly against Sci-Hub mirrors. Don't add scidownl as a dependency.
- **`conversation_id` is required for RAG to work.** If omitted from `POST /fetch`, the pdf-parser webhook is silently skipped (logged as warning, no error returned). RAG ingestion will never fire. Always pass `conversation_id` when DOI is fetched in a conversation context.
- PDF Parser webhook URL must be `http://pdf-parser:8300/jobs` (Docker internal) — never localhost
- MinIO bucket is `articles` — must exist before service starts (created by MinIO init in compose)
- Job status is tracked in Redis — use the same Redis instance as backend (configured via `REDIS_URL`)
- Sci-Hub downloads can be slow or fail for some DOIs — `FetchError` is raised and the job status is set to FAILED
