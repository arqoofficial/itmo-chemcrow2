import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis as redis_lib
import requests
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
    if not isinstance(raw, (str, bytes, bytearray)):
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
        if settings.article_processor_webhook_url:
            try:
                requests.post(
                    settings.article_processor_webhook_url,
                    json={"job_id": job_id, "doi": doi, "object_key": object_key, "status": "done"},
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
