"""Article jobs proxy — forwards job status requests to the article-fetcher service."""
from __future__ import annotations

import json
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.redis import get_async_redis
from app.models import Conversation
from app.worker.tasks.continuation import _trigger_rag_continuation, run_s2_search

router = APIRouter(prefix="/articles", tags=["articles"])


class ArticleJobResponse(BaseModel):
    job_id: str
    status: str
    url: str | None = None
    error: str | None = None


class ArticleJobInfo(BaseModel):
    doi: str
    job_id: str


@router.get("/jobs/{job_id}", response_model=ArticleJobResponse)
async def get_article_job(
    job_id: str = Path(pattern=r"^[0-9a-f-]{36}$"),
    current_user: CurrentUser = ...,  # noqa: ARG001 — auth guard
) -> ArticleJobResponse:
    """Proxy job status from the article-fetcher service."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{settings.ARTICLE_FETCHER_URL}/jobs/{job_id}")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"Article fetcher unreachable: {exc}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Job not found")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Article fetcher error")

    return ArticleJobResponse(**resp.json())


class ParseStatusResponse(BaseModel):
    job_id: str
    status: str
    error: str | None = None


@router.get("/jobs/{job_id}/parse-status", response_model=ParseStatusResponse)
async def get_parse_status(
    job_id: str = Path(pattern=r"^[0-9a-f-]{36}$"),
    current_user: CurrentUser = ...,  # noqa: ARG001 — auth guard
) -> ParseStatusResponse:
    """Proxy parse job status from the pdf-parser service."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{settings.PDF_PARSER_URL}/jobs/{job_id}")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"PDF parser unreachable: {exc}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Parse job not found")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="PDF parser error")

    data = resp.json()
    return ParseStatusResponse(
        job_id=data["job_id"],
        status=data["status"],
        error=data.get("error"),
    )


@router.post("/jobs/{job_id}/reparse", response_model=ParseStatusResponse)
async def reparse_job(
    job_id: str = Path(pattern=r"^[0-9a-f-]{36}$"),
    current_user: CurrentUser = ...,  # noqa: ARG001 — auth guard
) -> ParseStatusResponse:
    """Re-queue a failed parse job in the pdf-parser service."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(f"{settings.PDF_PARSER_URL}/jobs/{job_id}/reparse")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"PDF parser unreachable: {exc}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Parse job not found")
    if resp.status_code == 409:
        raise HTTPException(status_code=409, detail=resp.json().get("detail", "Job not in failed state"))
    if resp.status_code != 202:
        raise HTTPException(status_code=502, detail="PDF parser error")

    data = resp.json()
    return ParseStatusResponse(job_id=data["job_id"], status=data["status"], error=None)


@router.get("/conversations/{conversation_id}/jobs", response_model=list[ArticleJobInfo])
async def get_conversation_article_jobs(
    conversation_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[ArticleJobInfo]:
    """Return all article download jobs stored for a conversation."""
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    r = get_async_redis()
    raw = await r.lrange(f"conversation:{conversation_id}:article_jobs", 0, -1)
    return [ArticleJobInfo(**json.loads(item)) for item in raw]


@router.post("/conversations/{conversation_id}/retry-s2-search", status_code=202)
async def retry_s2_search(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,  # noqa: ARG001 — auth guard
) -> dict:
    """Re-run the last S2 search for a conversation. Returns 410 if query expired (>24h)."""
    r = get_async_redis()
    query = await r.get(f"s2_last_query:{conversation_id}")
    if not query:
        raise HTTPException(
            status_code=410,
            detail="Search query expired. Please start a new search.",
        )
    run_s2_search.delay(str(conversation_id), query)
    return {"status": "queued"}


@router.post("/conversations/{conversation_id}/trigger-rag-continuation", status_code=202)
async def trigger_rag_continuation_endpoint(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,  # noqa: ARG001 — auth guard
) -> dict:
    """Manually trigger a RAG-based agent continuation (used by 'Notify Agent' button)."""
    _trigger_rag_continuation(str(conversation_id))
    return {"status": "queued"}
