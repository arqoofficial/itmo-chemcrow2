import asyncio
import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from redis.asyncio import Redis

from app.config import settings
from app.minio_store import make_minio_store
from app.parser import process_pdf_to_minio
from app.redis_store import RedisJobStore
from app.schemas import (
    IngestWebhookPayload,
    JobState,
    JobStatus,
    JobStatusResponse,
    JobSubmitResponse,
)

log = logging.getLogger(__name__)

job_store: RedisJobStore = None  # set in lifespan
minio = None                      # set in lifespan


@asynccontextmanager
async def lifespan(app: FastAPI):
    global job_store, minio
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    job_store = RedisJobStore(redis=redis, ttl=settings.REDIS_JOB_TTL)
    minio = make_minio_store(
        endpoint=settings.ARTICLES_MINIO_ENDPOINT,
        access_key=settings.ARTICLES_MINIO_ACCESS_KEY,
        secret_key=settings.ARTICLES_MINIO_SECRET_KEY,
        input_bucket=settings.ARTICLES_MINIO_INPUT_BUCKET,
        output_bucket=settings.ARTICLES_MINIO_OUTPUT_BUCKET,
        secure=settings.ARTICLES_MINIO_SECURE,
    )
    log.info("pdf-parser service starting (env=%s)", settings.ENVIRONMENT)
    yield
    await redis.aclose()
    log.info("pdf-parser service shutting down")


app = FastAPI(title="PDF Parser Service", version="0.1.0", lifespan=lifespan)


def _build_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=0,
    )


def _build_langfuse_handler():
    if not settings.LANGFUSE_PUBLIC_KEY:
        return None
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
        lf = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_BASE_URL,
        )
        if not lf.auth_check():
            log.warning("Langfuse auth_check failed — tracing disabled")
            return None
        return CallbackHandler()
    except Exception:
        log.warning("Langfuse unavailable — tracing disabled")
        return None


async def _notify_ai_agent(conversation_id: str, doc_key: str) -> None:
    """POST /rag/ingest to ai-agent. Retries once after 5 s on failure."""
    url = f"{settings.AI_AGENT_INGEST_URL}/rag/ingest"
    payload = {"conversation_id": conversation_id, "doc_key": doc_key}
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                log.info(
                    "pdf-parser: notified ai-agent ingest for conv=%s doc=%s",
                    conversation_id,
                    doc_key,
                )
                return
        except Exception:
            if attempt == 0:
                log.warning(
                    "pdf-parser: ingest webhook failed, retrying in 5s (conv=%s doc=%s)",
                    conversation_id,
                    doc_key,
                )
                await asyncio.sleep(5)
            else:
                log.exception(
                    "pdf-parser: ingest webhook failed after retry (conv=%s doc=%s)",
                    conversation_id,
                    doc_key,
                )


async def _run_parser(job_id: str, object_key: str, conversation_id: str, doc_key: str) -> None:
    await job_store.update(job_id, status=JobStatus.RUNNING)
    try:
        pdf_bytes = await asyncio.to_thread(minio.download_pdf, object_key)
        llm = _build_llm()
        langfuse_handler = _build_langfuse_handler()
        artifacts = await process_pdf_to_minio(
            pdf_bytes, job_id, conversation_id, doc_key, minio, llm, langfuse_handler,
        )
        await job_store.update(job_id, status=JobStatus.COMPLETED, artifacts=artifacts)
        log.info("job %s completed with %d artifacts", job_id, len(artifacts))
        await _notify_ai_agent(conversation_id, doc_key)
    except Exception as exc:
        log.exception("job %s failed", job_id)
        await job_store.update(job_id, status=JobStatus.FAILED, error=str(exc))


@app.get("/health")
async def health():
    return {"status": "ok", "service": "pdf-parser"}


@app.post("/jobs", response_model=JobSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_job(payload: IngestWebhookPayload, background_tasks: BackgroundTasks) -> JobSubmitResponse:
    """Accept webhook from article-fetcher. PDF is already in articles-minio."""
    job = JobState(
        job_id=payload.job_id,
        status=JobStatus.PENDING,
        doi=payload.doi,
        doc_key=payload.doc_key,
        conversation_id=payload.conversation_id,
        created_at=time.time(),
        updated_at=time.time(),
    )
    await job_store.save(job)
    background_tasks.add_task(
        _run_parser,
        payload.job_id,
        payload.object_key,
        payload.conversation_id,
        payload.doc_key,
    )
    log.info(
        "submitted job %s for DOI %s (conv=%s)",
        payload.job_id,
        payload.doi,
        payload.conversation_id,
    )
    return JobSubmitResponse(job_id=payload.job_id, status=JobStatus.PENDING)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    job = await job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return JobStatusResponse.from_job(job)
