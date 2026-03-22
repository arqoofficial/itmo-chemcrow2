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
