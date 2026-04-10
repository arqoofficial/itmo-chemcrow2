# Article Fetcher Microservice — Design Spec

**Date:** 2026-03-22

## Overview

A new `article-fetcher` FastAPI microservice that asynchronously fetches academic PDFs from sci-hub by DOI and stores them in a dedicated MinIO instance. Callers submit a DOI via HTTP POST, receive a job ID, and poll for status. When complete, they receive a presigned MinIO URL to the PDF.

## Architecture

```
Caller (e.g. ai-agent)
    │
    │  POST /fetch {"doi": "10.xxxx/..."}
    ▼
article-fetcher (FastAPI, port 8200)
    │  ├── returns {"job_id": "<uuid>", "status": "pending"}
    │  └── spawns background task
    │
    ├── Redis (existing, job state as JSON blobs)
    │       key: job:{job_id}
    │       value: {status, doi, object_key, error, created_at}
    │
    └── articles-minio (new MinIO, port 9092:9000 / 9093:9001)
            bucket: articles
            object key: {job_id}.pdf
```

## Services

### `articles-minio`
- Image: `minio/minio`
- Ports: `9092:9000` (S3 API), `9093:9001` (web console)
- Volume: `articles-minio-data`
- Avoids conflict with existing `langfuse-minio` (ports 9090:9000)

### `article-fetcher`
- Port: `8200`
- Dependencies: `articles-minio` (healthy), `redis` (healthy)
- Source: `services/article-fetcher/`

## API

### `POST /fetch`
Request:
```json
{"doi": "10.1038/s41586-021-03819-2"}
```
Response `202 Accepted`:
```json
{"job_id": "550e8400-e29b-41d4-a716-446655440000", "status": "pending"}
```

### `GET /jobs/{job_id}`
Response when pending/running:
```json
{"job_id": "...", "status": "pending", "url": null, "error": null}
```
Response when done:
```json
{"job_id": "...", "status": "done", "url": "http://localhost:9092/articles/...?X-Amz-...", "error": null}
```
Response when failed:
```json
{"job_id": "...", "status": "failed", "url": null, "error": "Article not found on sci-hub"}
```

### `GET /health`
Returns `{"status": "ok"}`.

## Data Flow

1. `POST /fetch` → generate UUID job_id → store `{status: "pending", doi, created_at}` in Redis → spawn `BackgroundTask` → return job_id
2. Background task:
   - Update Redis: `status → "running"`
   - Call `scidownl` to download PDF to a temp file
   - Upload temp file to MinIO bucket `articles` with key `{job_id}.pdf`
   - Update Redis: `status → "done"`, `object_key → "{job_id}.pdf"`
   - On any exception: update Redis `status → "failed"`, `error → str(e)`
3. `GET /jobs/{job_id}`:
   - Read job from Redis
   - If `done`: generate presigned URL (1 hour TTL) via boto3, return it
   - Otherwise return current status

## Job State Schema (Redis)

Key: `job:{job_id}` (string, JSON-encoded), TTL: 7 days

```json
{
  "job_id": "...",
  "doi": "10.xxxx/...",
  "status": "pending | running | done | failed",
  "object_key": "550e8400....pdf",
  "error": null,
  "created_at": "2026-03-22T10:00:00Z"
}
```

## Dependencies

```
fastapi[standard]
uvicorn[standard]
redis
scidownl
boto3
pydantic-settings
```

## File Structure

```
services/article-fetcher/
├── Dockerfile
├── pyproject.toml
├── uv.lock          (generated)
└── app/
    ├── __init__.py
    ├── main.py       # FastAPI app, routes
    ├── config.py     # Settings (pydantic-settings)
    ├── storage.py    # MinIO client wrapper (upload, presign)
    └── fetcher.py    # scidownl wrapper (download to temp file)
```

## Error Handling

- If `job_id` not found in Redis: `404 Not Found`
- Fetch failures (sci-hub unavailable, article not found): job → `failed`, error stored
- No automatic retries (v1); caller may re-submit the same DOI

## Environment Variables

```
REDIS_URL=redis://redis:6379/0
MINIO_ENDPOINT=articles-minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=articles
MINIO_PUBLIC_ENDPOINT=http://localhost:9092   # for presigned URLs accessible from host
```
