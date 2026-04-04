"""Async pipeline Celery tasks: run_s2_search, monitor_ingestion, run_agent_continuation."""
from __future__ import annotations

import json
import logging

import httpx
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.core.redis import get_sync_redis
from app.models import ChatMessage, Conversation, get_datetime_utc
from app.worker import prompts
from app.worker.celery_app import celery_app
from app.worker.tasks.chat import _submit_article_jobs

logger = logging.getLogger(__name__)

_AI_AGENT_URL = settings.AI_AGENT_URL


def _publish_sync(conversation_id: str, data: dict) -> None:
    r = get_sync_redis()
    r.publish(f"conversation:{conversation_id}", json.dumps(data, default=str))


def save_background_message(
    conversation_id: str,
    content: str,
    variant: str = "info",
) -> None:
    """Persist a background message. variant='info'|'error' controls frontend card style."""
    with Session(engine) as db:
        msg = ChatMessage(
            conversation_id=conversation_id,
            role="background",
            content=content,
            msg_metadata={"variant": variant},
        )
        db.add(msg)
        db.commit()


def _format_s2_results(papers: list[dict], query: str) -> str:
    lines = []
    for i, p in enumerate(papers, 1):
        doi = p.get("doi") or "N/A"
        authors = p.get("authors") or "Unknown"
        year = p.get("year") or "N/A"
        title = p.get("title") or "Untitled"
        abstract = p.get("abstract") or "No abstract."
        if len(abstract) > 400:
            abstract = abstract[:400] + "..."
        lines.append(
            f"{i}. **{title}** — {authors} ({year}) — DOI: {doi}\n"
            f"   Abstract: {abstract}"
        )
    papers_formatted = "\n\n".join(lines)
    return prompts.S2_RESULTS.format(
        query=query,
        n=len(papers),
        papers_formatted=papers_formatted,
    )


@celery_app.task(queue="chat", ignore_result=True)
def run_s2_search(conversation_id: str, query: str, max_results: int = 5) -> None:
    """Call ai-agent blocking S2 search, save background message, dispatch continuation."""
    logger.info("run_s2_search started conv=%s query=%r", conversation_id, query)

    # 1. Call ai-agent blocking endpoint
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{_AI_AGENT_URL}/internal/s2-search",
                json={"query": query, "max_results": max_results},
            )
            resp.raise_for_status()
        papers = resp.json().get("papers", [])
    except Exception:
        logger.exception("S2 search failed for conv=%s", conversation_id)
        _publish_sync(conversation_id, {
            "event": "background_error",
            "detail": f'Literature search for "{query}" failed. Please try again.',
            "retry_available": True,
        })
        return

    # 2. No results
    if not papers:
        _publish_sync(conversation_id, {
            "event": "background_error",
            "detail": f'No papers found for "{query}".',
            "retry_available": False,
        })
        return

    # 3. Submit article downloads
    r = get_sync_redis()
    dois = [p["doi"] for p in papers if p.get("doi")]
    new_jobs = _submit_article_jobs(r, conversation_id, dois)

    # 4. Save paper metadata per job_id for PAPERS_INGESTED prompt (48h TTL)
    paper_by_doi = {p["doi"]: p for p in papers if p.get("doi")}
    for job in new_jobs:
        meta_key = f"s2_paper_meta:{job['job_id']}"
        r.set(meta_key, json.dumps(paper_by_doi.get(job["doi"], {})), ex=48 * 3600)

    # 5. Save background message (S2 results)
    content = _format_s2_results(papers, query)
    save_background_message(conversation_id, content, variant="info")

    # 6. Publish background_update so frontend re-enables SSE
    _publish_sync(conversation_id, {"event": "background_update"})

    # 7. Dispatch continuation (abstract-level response) and ingestion monitor
    # countdown=1 gives frontend time to re-enable SSE before streaming starts
    run_agent_continuation.apply_async(args=[conversation_id], countdown=1)

    if new_jobs:
        job_ids = [j["job_id"] for j in new_jobs]
        monitor_ingestion.delay(conversation_id, job_ids)

    logger.info(
        "run_s2_search done conv=%s papers=%d jobs=%d",
        conversation_id, len(papers), len(new_jobs),
    )


# Forward declarations — full implementations in Tasks 6 and 7
@celery_app.task(queue="chat", ignore_result=True)
def run_agent_continuation(conversation_id: str) -> None:
    raise NotImplementedError("Task 7")


@celery_app.task(bind=True, queue="chat", max_retries=120, default_retry_delay=10, ignore_result=True)
def monitor_ingestion(self, conversation_id: str, job_ids: list[str]) -> None:
    raise NotImplementedError("Task 6")
