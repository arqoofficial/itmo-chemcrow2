"""Internal endpoints — no auth, Docker-network only. Never expose to public internet."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.redis import get_sync_redis

logger = logging.getLogger(__name__)

# Lazy import guard: task module doesn't exist until Task 5 is implemented.
# The name must be at module level so unittest.mock.patch can target it.
try:
    from app.worker.tasks.continuation import run_openalex_search, run_s2_search  # noqa: F401
except ImportError:
    run_s2_search = None  # type: ignore[assignment]
    run_openalex_search = None  # type: ignore[assignment]

router = APIRouter(prefix="/internal", tags=["internal"])


class QueueBackgroundToolRequest(BaseModel):
    type: str  # "s2_search" or "openalex_search"
    conversation_id: str
    query: str
    max_results: int = 5


@router.post("/queue-background-tool", status_code=202)
def queue_background_tool(payload: QueueBackgroundToolRequest) -> dict:
    """Queue a background tool call. Called by ai-agent literature_search/openalex_search tools."""
    if payload.type == "s2_search":
        # Persist query for retry support (24h TTL)
        r = get_sync_redis()
        r.set(
            f"s2_last_query:{payload.conversation_id}",
            payload.query,
            ex=24 * 3600,
        )
        run_s2_search.delay(payload.conversation_id, payload.query, payload.max_results)
        logger.info("Queued run_s2_search for conv=%s query=%r", payload.conversation_id, payload.query)
        return {"status": "queued"}

    elif payload.type == "openalex_search":
        # Persist query for retry support (24h TTL)
        r = get_sync_redis()
        r.set(
            f"openalex_last_query:{payload.conversation_id}",
            payload.query,
            ex=24 * 3600,
        )
        run_openalex_search.delay(payload.conversation_id, payload.query, payload.max_results)
        logger.info("Queued run_openalex_search for conv=%s query=%r", payload.conversation_id, payload.query)
        return {"status": "queued"}

    return {"status": "ignored", "reason": f"unknown type: {payload.type}"}


class OpenAlexSearchRequest(BaseModel):
    query: str
    max_results: int = 5


@router.post("/openalex-search")
def openalex_search(payload: OpenAlexSearchRequest) -> dict:
    """Blocking call to OpenAlex API. Called by Celery run_openalex_search task."""
    import httpx

    from app.core.config import settings

    if not settings.OPENALEX_API_KEY:
        logger.warning("OpenAlex API search called but API key not configured")
        return {"papers": []}

    try:
        url = f"{settings.OPENALEX_API_BASE}/works"
        params = {
            "search": payload.query,
            "per_page": payload.max_results,
            "api_key": settings.OPENALEX_API_KEY,
        }
        resp = httpx.get(url, params=params, timeout=15.0)
        resp.raise_for_status()

        data = resp.json()
        papers = []

        for result in data.get("results", []):
            paper = {
                "doi": result.get("doi"),
                "title": result.get("title", "Untitled"),
                "authors": ", ".join(
                    [auth["author"]["display_name"] for auth in result.get("authorships", [])]
                ) or "Unknown",
                "year": result.get("publication_year", "N/A"),
                "abstract": result.get("abstract") or "",
                "citation_count": result.get("cited_by_count", 0),
            }
            papers.append(paper)

        logger.info("OpenAlex search succeeded query=%r papers=%d", payload.query, len(papers))
        return {"papers": papers}

    except httpx.RequestError as exc:
        logger.exception("OpenAlex HTTP request failed for query=%r", payload.query)
        return {"papers": [], "error": f"Connection error: {exc}"}
    except Exception:
        logger.exception("OpenAlex search failed for query=%r", payload.query)
        return {"papers": [], "error": "Search failed"}
