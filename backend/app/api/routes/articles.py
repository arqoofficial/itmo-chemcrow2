"""Article jobs proxy — forwards job status requests to the article-fetcher service."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core.config import settings

router = APIRouter(prefix="/articles", tags=["articles"])


class ArticleJobResponse(BaseModel):
    job_id: str
    status: str
    url: str | None = None
    error: str | None = None


@router.get("/jobs/{job_id}", response_model=ArticleJobResponse)
async def get_article_job(
    job_id: str,
    current_user: CurrentUser,  # noqa: ARG001 — auth guard
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
