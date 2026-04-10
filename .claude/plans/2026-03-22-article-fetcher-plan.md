# Article Fetcher Microservice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI microservice that asynchronously fetches academic PDFs from sci-hub by DOI, stores them in MinIO, and exposes job status via HTTP.

**Architecture:** `POST /fetch` creates a job in Redis and spawns a FastAPI `BackgroundTask` that downloads the PDF via `scidownl` and uploads it to a dedicated MinIO instance. `GET /jobs/{job_id}` returns status and a presigned URL when done.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, redis-py, scidownl, boto3, pydantic-settings, uv, MinIO (Docker), pytest

---

## File Map

| Path | Action | Responsibility |
|------|--------|----------------|
| `services/article-fetcher/pyproject.toml` | Create | Project metadata + dependencies |
| `services/article-fetcher/Dockerfile` | Create | Container build (mirrors ai-agent pattern) |
| `services/article-fetcher/app/__init__.py` | Create | Empty package marker |
| `services/article-fetcher/app/config.py` | Create | Pydantic-settings for env vars |
| `services/article-fetcher/app/storage.py` | Create | MinIO client: upload PDF, generate presigned URL |
| `services/article-fetcher/app/fetcher.py` | Create | scidownl wrapper: download DOI to temp file |
| `services/article-fetcher/app/main.py` | Create | FastAPI app: routes, background task, Redis job CRUD |
| `services/article-fetcher/tests/__init__.py` | Create | Empty package marker |
| `services/article-fetcher/tests/conftest.py` | Create | Shared pytest fixtures (mock Redis, mock MinIO) |
| `services/article-fetcher/tests/test_main.py` | Create | Tests for HTTP endpoints |
| `services/article-fetcher/tests/test_storage.py` | Create | Tests for MinIO upload/presign |
| `services/article-fetcher/tests/test_fetcher.py` | Create | Tests for scidownl wrapper |
| `compose.yml` | Modify | Add `articles-minio` and `article-fetcher` services |
| `.env` | Modify | Add MinIO credentials for articles service |

---

## Task 1: Project scaffold and config

**Files:**
- Create: `services/article-fetcher/pyproject.toml`
- Create: `services/article-fetcher/app/__init__.py`
- Create: `services/article-fetcher/app/config.py`
- Create: `services/article-fetcher/tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "article-fetcher"
version = "0.1.0"
description = "Async sci-hub article fetcher microservice"
requires-python = ">=3.11,<4.0"
dependencies = [
    "fastapi[standard]>=0.114.2,<1.0.0",
    "uvicorn[standard]>=0.30.0,<1.0.0",
    "redis>=5.0.0,<6.0.0",
    "scidownl>=1.0.2",
    "boto3>=1.28.0",
    "pydantic-settings>=2.2.0,<3.0.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty `app/__init__.py` and `tests/__init__.py`**

Both files are empty.

- [ ] **Step 3: Write failing test for config**

Create `services/article-fetcher/tests/conftest.py`:

```python
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_redis():
    return MagicMock()


@pytest.fixture
def mock_s3():
    return MagicMock()
```

Create `services/article-fetcher/tests/test_config.py`:

```python
import os
import pytest
from unittest.mock import patch


def test_config_loads_defaults():
    with patch.dict(os.environ, {
        "REDIS_URL": "redis://localhost:6379/0",
        "MINIO_ENDPOINT": "localhost:9092",
        "MINIO_ACCESS_KEY": "minioadmin",
        "MINIO_SECRET_KEY": "minioadmin",
        "MINIO_BUCKET": "articles",
        "MINIO_PUBLIC_ENDPOINT": "http://localhost:9092",
    }):
        from app.config import Settings
        s = Settings()
        assert s.redis_url == "redis://localhost:6379/0"
        assert s.minio_bucket == "articles"
```

- [ ] **Step 4: Run test to verify it fails**

```bash
cd services/article-fetcher
uv run pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 5: Create `app/config.py`**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://redis:6379/0"
    minio_endpoint: str = "articles-minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "articles"
    minio_public_endpoint: str = "http://localhost:9092"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
```

- [ ] **Step 6: Install dependencies and run test**

```bash
cd services/article-fetcher
uv sync
uv run pytest tests/test_config.py -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add services/article-fetcher/
git commit -m "feat(article-fetcher): scaffold project with config"
```

---

## Task 2: Storage module (MinIO upload + presign)

**Files:**
- Create: `services/article-fetcher/app/storage.py`
- Create: `services/article-fetcher/tests/test_storage.py`

- [ ] **Step 1: Write failing tests**

Create `services/article-fetcher/tests/test_storage.py`:

```python
import io
import pytest
from unittest.mock import MagicMock, patch, call


def test_upload_pdf_calls_put_object():
    mock_client = MagicMock()
    with patch("app.storage.boto3.client", return_value=mock_client):
        from app.storage import StorageClient
        client = StorageClient(
            endpoint="localhost:9000",
            access_key="key",
            secret_key="secret",
            bucket="articles",
            public_endpoint="http://localhost:9000",
        )
        client.upload_pdf("job123.pdf", b"%PDF-1.4 test content")
        mock_client.put_object.assert_called_once_with(
            Bucket="articles",
            Key="job123.pdf",
            Body=b"%PDF-1.4 test content",
            ContentType="application/pdf",
        )


def test_presign_url_calls_generate_presigned_url():
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "http://localhost:9000/articles/job123.pdf?sig=abc"
    with patch("app.storage.boto3.client", return_value=mock_client):
        from app.storage import StorageClient
        client = StorageClient(
            endpoint="localhost:9000",
            access_key="key",
            secret_key="secret",
            bucket="articles",
            public_endpoint="http://localhost:9000",
        )
        url = client.presign_url("job123.pdf", expires_in=3600)
        assert "job123.pdf" in url
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "articles", "Key": "job123.pdf"},
            ExpiresIn=3600,
        )


def test_ensure_bucket_creates_if_missing():
    mock_client = MagicMock()
    mock_client.head_bucket.side_effect = Exception("NoSuchBucket")
    with patch("app.storage.boto3.client", return_value=mock_client):
        from app.storage import StorageClient
        client = StorageClient(
            endpoint="localhost:9000",
            access_key="key",
            secret_key="secret",
            bucket="articles",
            public_endpoint="http://localhost:9000",
        )
        client.ensure_bucket()
        mock_client.create_bucket.assert_called_once_with(Bucket="articles")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/article-fetcher
uv run pytest tests/test_storage.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.storage'`

- [ ] **Step 3: Create `app/storage.py`**

```python
import logging
import boto3
from botocore.client import Config

logger = logging.getLogger(__name__)


class StorageClient:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        public_endpoint: str,
    ):
        self._bucket = bucket
        self._public_endpoint = public_endpoint
        self._client = boto3.client(
            "s3",
            endpoint_url=f"http://{endpoint}",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            logger.warning("Bucket %s not found, creating", self._bucket)
            self._client.create_bucket(Bucket=self._bucket)

    def upload_pdf(self, key: str, data: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType="application/pdf",
        )
        logger.info("Uploaded %s to bucket %s", key, self._bucket)

    def presign_url(self, key: str, expires_in: int = 3600) -> str:
        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        # Rewrite internal endpoint to public endpoint for external access
        if self._public_endpoint and self._public_endpoint not in url:
            internal = self._client.meta.endpoint_url
            url = url.replace(internal, self._public_endpoint)
        return url
```

- [ ] **Step 4: Run tests**

```bash
cd services/article-fetcher
uv run pytest tests/test_storage.py -v
```

Expected: all 3 PASS

- [ ] **Step 5: Commit**

```bash
git add services/article-fetcher/app/storage.py services/article-fetcher/tests/test_storage.py
git commit -m "feat(article-fetcher): add MinIO storage client"
```

---

## Task 3: Fetcher module (scidownl wrapper)

**Files:**
- Create: `services/article-fetcher/app/fetcher.py`
- Create: `services/article-fetcher/tests/test_fetcher.py`

- [ ] **Step 1: Write failing tests**

Create `services/article-fetcher/tests/test_fetcher.py`:

```python
import os
import pytest
from unittest.mock import patch, MagicMock


def test_fetch_returns_pdf_bytes_on_success(tmp_path):
    fake_pdf = b"%PDF-1.4 fake content"

    def fake_download(doi, output_path, **kwargs):
        # scidownl writes to the given path
        with open(output_path, "wb") as f:
            f.write(fake_pdf)

    with patch("app.fetcher.scihub_download", side_effect=fake_download):
        from app.fetcher import fetch_article
        result = fetch_article("10.1234/test")
        assert result == fake_pdf


def test_fetch_raises_on_empty_file(tmp_path):
    def fake_download_empty(doi, output_path, **kwargs):
        open(output_path, "wb").close()  # empty file

    with patch("app.fetcher.scihub_download", side_effect=fake_download_empty):
        from app.fetcher import fetch_article, FetchError
        with pytest.raises(FetchError, match="empty"):
            fetch_article("10.1234/notfound")


def test_fetch_raises_on_download_exception():
    with patch("app.fetcher.scihub_download", side_effect=Exception("Connection refused")):
        from app.fetcher import fetch_article, FetchError
        with pytest.raises(FetchError, match="Connection refused"):
            fetch_article("10.1234/broken")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/article-fetcher
uv run pytest tests/test_fetcher.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.fetcher'`

- [ ] **Step 3: Create `app/fetcher.py`**

```python
import logging
import os
import tempfile

from scidownl import scihub_download

logger = logging.getLogger(__name__)


class FetchError(Exception):
    pass


def fetch_article(doi: str) -> bytes:
    """Download a PDF for the given DOI from sci-hub. Returns raw PDF bytes."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        logger.info("Fetching DOI %s via sci-hub", doi)
        scihub_download(doi, paper_type="doi", out=tmp_path)

        size = os.path.getsize(tmp_path)
        if size == 0:
            raise FetchError("Downloaded file is empty — article not found on sci-hub")

        with open(tmp_path, "rb") as f:
            data = f.read()

        logger.info("Fetched %d bytes for DOI %s", len(data), doi)
        return data

    except FetchError:
        raise
    except Exception as e:
        logger.exception("Failed to fetch DOI %s", doi)
        raise FetchError(str(e)) from e
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
```

- [ ] **Step 4: Run tests**

```bash
cd services/article-fetcher
uv run pytest tests/test_fetcher.py -v
```

Expected: all 3 PASS

- [ ] **Step 5: Commit**

```bash
git add services/article-fetcher/app/fetcher.py services/article-fetcher/tests/test_fetcher.py
git commit -m "feat(article-fetcher): add scidownl fetcher wrapper"
```

---

## Task 4: FastAPI app (routes + background task)

**Files:**
- Create: `services/article-fetcher/app/main.py`
- Create: `services/article-fetcher/tests/test_main.py`

- [ ] **Step 1: Write failing tests**

Create `services/article-fetcher/tests/test_main.py`:

```python
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_deps(mock_redis, mock_s3):
    """Patch Redis and StorageClient for all route tests."""
    with (
        patch("app.main.redis_client", mock_redis),
        patch("app.main.storage", mock_s3),
    ):
        yield mock_redis, mock_s3


@pytest.fixture
def client(mock_deps):
    from app.main import app
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_post_fetch_returns_job_id(client, mock_deps):
    mock_redis, _ = mock_deps
    mock_redis.set.return_value = True

    resp = client.post("/fetch", json={"doi": "10.1234/test"})
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "pending"
    mock_redis.set.assert_called_once()


def test_get_job_pending(client, mock_deps):
    mock_redis, _ = mock_deps
    job = {
        "job_id": "abc123",
        "doi": "10.1234/test",
        "status": "pending",
        "object_key": None,
        "error": None,
        "created_at": "2026-03-22T10:00:00Z",
    }
    mock_redis.get.return_value = json.dumps(job)

    resp = client.get("/jobs/abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["url"] is None


def test_get_job_done_returns_presigned_url(client, mock_deps):
    mock_redis, mock_s3 = mock_deps
    job = {
        "job_id": "abc123",
        "doi": "10.1234/test",
        "status": "done",
        "object_key": "abc123.pdf",
        "error": None,
        "created_at": "2026-03-22T10:00:00Z",
    }
    mock_redis.get.return_value = json.dumps(job)
    mock_s3.presign_url.return_value = "http://localhost:9092/articles/abc123.pdf?sig=x"

    resp = client.get("/jobs/abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert "abc123.pdf" in data["url"]


def test_get_job_failed(client, mock_deps):
    mock_redis, _ = mock_deps
    job = {
        "job_id": "abc123",
        "doi": "10.1234/test",
        "status": "failed",
        "object_key": None,
        "error": "Article not found",
        "created_at": "2026-03-22T10:00:00Z",
    }
    mock_redis.get.return_value = json.dumps(job)

    resp = client.get("/jobs/abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error"] == "Article not found"


def test_get_job_not_found(client, mock_deps):
    mock_redis, _ = mock_deps
    mock_redis.get.return_value = None

    resp = client.get("/jobs/doesnotexist")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/article-fetcher
uv run pytest tests/test_main.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Create `app/main.py`**

```python
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis as redis_lib
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.fetcher import FetchError, fetch_article
from app.storage import StorageClient

logger = logging.getLogger(__name__)

app = FastAPI(title="article-fetcher")

redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
storage = StorageClient(
    endpoint=settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    bucket=settings.minio_bucket,
    public_endpoint=settings.minio_public_endpoint,
)

JOB_TTL = 7 * 24 * 3600  # 7 days in seconds


class FetchRequest(BaseModel):
    doi: str


class JobResponse(BaseModel):
    job_id: str
    status: str
    url: Optional[str] = None
    error: Optional[str] = None


@app.on_event("startup")
def on_startup():
    storage.ensure_bucket()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/fetch", status_code=202, response_model=JobResponse)
def post_fetch(req: FetchRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "doi": req.doi,
        "status": "pending",
        "object_key": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    redis_client.set(f"job:{job_id}", json.dumps(job), ex=JOB_TTL)
    background_tasks.add_task(_run_fetch, job_id, req.doi)
    logger.info("Queued fetch job %s for DOI %s", job_id, req.doi)
    return JobResponse(job_id=job_id, status="pending")


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str):
    raw = redis_client.get(f"job:{job_id}")
    if raw is None:
        raise HTTPException(status_code=404, detail="Job not found")

    job = json.loads(raw)
    url = None
    if job["status"] == "done" and job.get("object_key"):
        url = storage.presign_url(job["object_key"])

    return JobResponse(
        job_id=job["job_id"],
        status=job["status"],
        url=url,
        error=job.get("error"),
    )


def _update_job(job_id: str, **kwargs) -> None:
    raw = redis_client.get(f"job:{job_id}")
    if raw is None:
        return
    job = json.loads(raw)
    job.update(kwargs)
    redis_client.set(f"job:{job_id}", json.dumps(job), ex=JOB_TTL)


def _run_fetch(job_id: str, doi: str) -> None:
    _update_job(job_id, status="running")
    try:
        pdf_bytes = fetch_article(doi)
        object_key = f"{job_id}.pdf"
        storage.upload_pdf(object_key, pdf_bytes)
        _update_job(job_id, status="done", object_key=object_key)
        logger.info("Job %s completed for DOI %s", job_id, doi)
    except FetchError as e:
        _update_job(job_id, status="failed", error=str(e))
        logger.warning("Job %s failed for DOI %s: %s", job_id, doi, e)
    except Exception as e:
        _update_job(job_id, status="failed", error=str(e))
        logger.exception("Unexpected error in job %s", job_id)
```

- [ ] **Step 4: Run tests**

```bash
cd services/article-fetcher
uv run pytest tests/test_main.py -v
```

Expected: all 6 PASS

- [ ] **Step 5: Run full test suite**

```bash
cd services/article-fetcher
uv run pytest -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add services/article-fetcher/app/main.py services/article-fetcher/tests/test_main.py
git commit -m "feat(article-fetcher): add FastAPI routes and background task"
```

---

## Task 5: Dockerfile

**Files:**
- Create: `services/article-fetcher/Dockerfile`

- [ ] **Step 1: Create `Dockerfile`** (mirrors the ai-agent pattern)

```dockerfile
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY services/article-fetcher/pyproject.toml .
COPY services/article-fetcher/app ./app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .

EXPOSE 8200

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]
```

- [ ] **Step 2: Verify build**

```bash
docker build -f services/article-fetcher/Dockerfile -t article-fetcher-test .
```

Expected: image builds successfully

- [ ] **Step 3: Commit**

```bash
git add services/article-fetcher/Dockerfile
git commit -m "feat(article-fetcher): add Dockerfile"
```

---

## Task 6: Docker Compose + env wiring

**Files:**
- Modify: `compose.yml`
- Modify: `.env`

- [ ] **Step 1: Add env vars to `.env`**

Append to `.env`:

```bash
# Articles MinIO
ARTICLES_MINIO_ACCESS_KEY=minioadmin
ARTICLES_MINIO_SECRET_KEY=minioadmin
```

- [ ] **Step 2: Read the current end of `compose.yml` to find the `volumes:` section**

Locate the `volumes:` block at the bottom — you'll add `articles-minio-data` there.

- [ ] **Step 3: Add `articles-minio` service to `compose.yml`**

Add before the `volumes:` section:

```yaml
  articles-minio:
    image: minio/minio
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${ARTICLES_MINIO_ACCESS_KEY:-minioadmin}
      MINIO_ROOT_PASSWORD: ${ARTICLES_MINIO_SECRET_KEY:-minioadmin}
    ports:
      - "9092:9000"
      - "9093:9001"
    volumes:
      - articles-minio-data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 5s
      retries: 5
```

- [ ] **Step 4: Add `article-fetcher` service to `compose.yml`**

Add after `articles-minio`:

```yaml
  article-fetcher:
    build:
      context: .
      dockerfile: services/article-fetcher/Dockerfile
    restart: unless-stopped
    ports:
      - "8200:8200"
    depends_on:
      redis:
        condition: service_healthy
      articles-minio:
        condition: service_healthy
    env_file:
      - .env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - MINIO_ENDPOINT=articles-minio:9000
      - MINIO_ACCESS_KEY=${ARTICLES_MINIO_ACCESS_KEY:-minioadmin}
      - MINIO_SECRET_KEY=${ARTICLES_MINIO_SECRET_KEY:-minioadmin}
      - MINIO_BUCKET=articles
      - MINIO_PUBLIC_ENDPOINT=http://localhost:9092
    develop:
      watch:
        - path: ./services/article-fetcher
          action: sync
          target: /app
          ignore:
            - .venv
        - path: ./services/article-fetcher/pyproject.toml
          action: rebuild
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8200/health"]
      interval: 10s
      timeout: 5s
      retries: 5
```

- [ ] **Step 5: Add volume to `compose.yml` volumes block**

In the `volumes:` section at the bottom, add:

```yaml
  articles-minio-data:
```

- [ ] **Step 6: Validate compose file**

```bash
docker compose config --quiet
```

Expected: exits 0 with no errors

- [ ] **Step 7: Commit**

```bash
git add compose.yml .env
git commit -m "feat(article-fetcher): wire up Docker Compose services"
```

---

## Task 7: Smoke test end-to-end

- [ ] **Step 1: Start the new services**

```bash
docker compose up -d redis articles-minio article-fetcher --build
```

- [ ] **Step 2: Wait for health**

```bash
docker compose ps
```

Expected: `redis`, `articles-minio`, `article-fetcher` all show `healthy`

- [ ] **Step 3: Hit health endpoint**

```bash
curl http://localhost:8200/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 4: Submit a fetch job**

```bash
curl -X POST http://localhost:8200/fetch \
  -H "Content-Type: application/json" \
  -d '{"doi": "10.1039/c9sc04589e"}'
```

Expected: `{"job_id": "<uuid>", "status": "pending"}`

- [ ] **Step 5: Poll job status**

```bash
JOB_ID=<uuid from step 4>
curl http://localhost:8200/jobs/$JOB_ID
```

Poll a few times. Expected progression: `pending` → `running` → `done` or `failed`

- [ ] **Step 6: If done, verify presigned URL is accessible**

```bash
URL=$(curl -s http://localhost:8200/jobs/$JOB_ID | python3 -c "import sys,json; print(json.load(sys.stdin)['url'])")
curl -I "$URL"
```

Expected: `HTTP/1.1 200 OK` with `Content-Type: application/pdf`

- [ ] **Step 7: Final commit**

```bash
git add -p  # review any leftover changes
git commit -m "feat(article-fetcher): complete microservice implementation"
```
