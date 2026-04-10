"""Literature search endpoint — calls Semantic Scholar directly, no agent involved."""
from __future__ import annotations

import logging
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])

_S2_API_BASE = "https://api.semanticscholar.org/graph/v1"
_S2_FIELDS = "title,authors,abstract,year,citationCount,url,externalIds"


class LiteratureSearchRequest(BaseModel):
    query: str
    max_results: int = 5


class PaperResult(BaseModel):
    title: str
    authors: list[str]
    abstract: str | None
    year: int | None
    citation_count: int | None
    url: str | None
    doi: str | None


class LiteratureSearchResponse(BaseModel):
    papers: list[PaperResult]
    query: str


@router.post("/literature", response_model=LiteratureSearchResponse)
def literature_search(
    req: LiteratureSearchRequest,
    current_user: CurrentUser,
) -> LiteratureSearchResponse:
    """Search Semantic Scholar directly — returns structured results, no LLM involved."""
    headers: dict[str, str] = {}
    s2_key = getattr(settings, "SEMANTIC_SCHOLAR_API_KEY", None)
    if s2_key:
        headers["x-api-key"] = s2_key

    params = {
        "query": req.query,
        "limit": min(req.max_results, 10),
        "fields": _S2_FIELDS,
    }

    retry_waits = [2, 5] if not s2_key else [1, 2, 4, 8]
    last_exc: Exception | None = None

    for wait in [0, *retry_waits]:
        if wait:
            time.sleep(wait)
        try:
            r = httpx.get(
                f"{_S2_API_BASE}/paper/search",
                params=params,
                headers=headers,
                timeout=15,
            )
            if r.status_code == 429:
                logger.warning("S2 429 for query=%r, will retry in %ds", req.query, retry_waits[0] if retry_waits else 0)
                last_exc = HTTPException(status_code=429, detail="Semantic Scholar rate limit — try again in a moment")
                continue
            r.raise_for_status()
            data = r.json()
            papers = [
                PaperResult(
                    title=p.get("title") or "",
                    authors=[a.get("name", "") for a in p.get("authors", [])],
                    abstract=p.get("abstract"),
                    year=p.get("year"),
                    citation_count=p.get("citationCount"),
                    url=p.get("url"),
                    doi=(p.get("externalIds") or {}).get("DOI"),
                )
                for p in data.get("data", [])
            ]
            return LiteratureSearchResponse(papers=papers, query=req.query)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("S2 search failed for query=%r", req.query)
            last_exc = exc
            break

    if isinstance(last_exc, HTTPException):
        raise last_exc
    raise HTTPException(status_code=502, detail=f"Search failed: {last_exc}")
