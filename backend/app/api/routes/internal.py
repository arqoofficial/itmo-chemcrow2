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
        try:
            r.set(
                f"openalex_last_query:{payload.conversation_id}",
                payload.query,
                ex=24 * 3600,
            )
        except Exception as exc:
            logger.warning(
                "Failed to cache OpenAlex query for retry conv=%s: %s",
                payload.conversation_id,
                exc,
            )
            # Don't fail the entire request — queue task anyway
            # Retry may fail later with "query expired" but that's acceptable
        run_openalex_search.delay(payload.conversation_id, payload.query, payload.max_results)
        logger.info("Queued run_openalex_search for conv=%s query=%r", payload.conversation_id, payload.query)
        return {"status": "queued"}

    return {"status": "ignored", "reason": f"unknown type: {payload.type}"}


class OpenAlexSearchRequest(BaseModel):
    query: str
    max_results: int = 5


@router.post("/openalex-search")
def openalex_search(payload: OpenAlexSearchRequest) -> dict:
    """Blocking call to OpenAlex API. Called by Celery run_openalex_search task.

    Returns error key in response if API key not configured or search fails.
    """
    import httpx
    import json

    from app.core.config import settings

    if not settings.OPENALEX_API_KEY:
        logger.error("OpenAlex API search called but OPENALEX_API_KEY not configured")
        return {
            "papers": [],
            "error": "OpenAlex API key not configured. Search cannot proceed.",
        }

    try:
        url = f"{settings.OPENALEX_API_BASE}/works"
        params = {
            "search": payload.query,
            "per_page": payload.max_results,
        }
        headers = {
            "Authorization": f"Bearer {settings.OPENALEX_API_KEY}",
        }
        resp = httpx.get(url, params=params, headers=headers, timeout=15.0)
        resp.raise_for_status()

        data = resp.json()
        papers = []

        for result in data.get("results", []):
            # Safely extract author names with fallback
            authors = []
            for auth in result.get("authorships", []):
                author = auth.get("author", {})
                name = author.get("display_name", "Unknown")
                if name:
                    authors.append(name)
            authors_str = ", ".join(authors) or "Unknown"

            paper = {
                "doi": result.get("doi"),
                "title": result.get("title", "Untitled"),
                "authors": authors_str,
                "year": result.get("publication_year", "N/A"),
                "abstract": result.get("abstract") or "",
                "citation_count": result.get("cited_by_count", 0),
            }
            papers.append(paper)

        logger.info("OpenAlex search succeeded query=%r papers=%d", payload.query, len(papers))
        return {"papers": papers}

    except httpx.TimeoutException as exc:
        logger.error("OpenAlex HTTP timeout after 15s for query=%r", payload.query)
        return {
            "papers": [],
            "error": "OpenAlex search timed out. Please try again.",
        }
    except httpx.HTTPStatusError as exc:
        logger.error(
            "OpenAlex HTTP error %d for query=%r",
            exc.response.status_code,
            payload.query,
        )
        return {
            "papers": [],
            "error": f"OpenAlex API returned error {exc.response.status_code}",
        }
    except httpx.RequestError as exc:
        logger.error("OpenAlex HTTP connection failed for query=%r: %s", payload.query, exc)
        return {"papers": [], "error": "Connection error: could not reach OpenAlex"}
    except json.JSONDecodeError as exc:
        logger.error("OpenAlex returned invalid JSON for query=%r", payload.query)
        return {
            "papers": [],
            "error": "OpenAlex returned invalid response format",
        }
