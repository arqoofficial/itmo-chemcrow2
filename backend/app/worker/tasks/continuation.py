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
from app.worker.tasks.chat import _process_streaming, _submit_article_jobs

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


@celery_app.task(queue="chat", ignore_result=True)
def run_agent_continuation(conversation_id: str) -> None:
    """Re-invoke the agent with fresh history (includes background messages).

    Uses per-conversation lock to prevent concurrent streaming:
    - conv_processing:{id} — SET NX EX 600 (atomic, avoids permanent lock on crash)
    - conv_pending:{id}    — Redis list for queued signals
    """
    r = get_sync_redis()
    lock_key = f"conv_processing:{conversation_id}"
    pending_key = f"conv_pending:{conversation_id}"

    # Atomic acquire — single command, avoids SETNX+EXPIRE race condition
    acquired = r.set(lock_key, "1", nx=True, ex=600)
    if not acquired:
        r.rpush(pending_key, "1")
        logger.info("run_agent_continuation queued for conv=%s (already processing)", conversation_id)
        return

    try:
        with Session(engine) as db:
            messages_db = db.exec(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(col(ChatMessage.created_at).asc())
            ).all()
            messages_payload = [
                {"role": msg.role, "content": msg.content}
                for msg in messages_db
            ]

        _publish_sync(conversation_id, {"event": "thinking", "conversation_id": conversation_id})

        try:
            assistant_content, tool_calls_raw = _process_streaming(
                conversation_id, messages_payload, r,
            )
        except Exception:
            logger.exception("Streaming failed in run_agent_continuation conv=%s", conversation_id)
            return

        tool_calls_json = json.dumps(tool_calls_raw) if tool_calls_raw else None

        with Session(engine) as db:
            assistant_message = ChatMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_content,
                tool_calls=tool_calls_json,
            )
            db.add(assistant_message)

            conv = db.get(Conversation, conversation_id)
            if conv:
                conv.updated_at = get_datetime_utc()
                db.add(conv)

            db.commit()
            db.refresh(assistant_message)
            msg_id = str(assistant_message.id)

        _publish_sync(conversation_id, {
            "event": "message",
            "id": msg_id,
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": tool_calls_json,
            "created_at": str(assistant_message.created_at),
        })

        logger.info("run_agent_continuation complete conv=%s msg=%s", conversation_id, msg_id)

    finally:
        r.delete(lock_key)
        # Drain entire pending queue into a single dispatch
        if r.llen(pending_key) > 0:
            r.delete(pending_key)
            run_agent_continuation.apply_async(args=[conversation_id], countdown=0)


def _get_fetch_status(client: httpx.Client, job_id: str) -> str:
    """Get article-fetcher status. Returns 'pending'|'done'|'failed'."""
    try:
        resp = client.get(f"{settings.ARTICLE_FETCHER_URL}/jobs/{job_id}", timeout=5.0)
        if resp.status_code == 200:
            return resp.json().get("status", "pending")
        return "pending"
    except Exception:
        logger.warning("Failed to get fetch status for job %s", job_id, exc_info=True)
        return "pending"


def _get_parse_status(client: httpx.Client, job_id: str) -> str:
    """Get pdf-parser status. Returns 'pending' on HTTP 404 — job not yet created."""
    try:
        resp = client.get(f"{settings.PDF_PARSER_URL}/jobs/{job_id}", timeout=5.0)
        if resp.status_code == 404:
            return "pending"  # not yet created — never treat as failed
        if resp.status_code == 200:
            return resp.json().get("status", "pending")
        return "pending"
    except Exception:
        logger.warning("Failed to get parse status for job %s", job_id, exc_info=True)
        return "pending"


def _trigger_rag_continuation(conversation_id: str, completed_job_ids: list[str] | None = None) -> None:
    """Build PAPERS_INGESTED message from Redis metadata and dispatch continuation.

    completed_job_ids is optional. When None (manual trigger), uses generic message.
    """
    r = get_sync_redis()
    lines = []
    for i, job_id in enumerate(completed_job_ids or [], 1):
        raw = r.get(f"s2_paper_meta:{job_id}")
        if raw:
            p = json.loads(raw)
            doi = p.get("doi") or "N/A"
            title = p.get("title") or "Untitled"
            authors = p.get("authors") or "Unknown"
            year = p.get("year") or "N/A"
            lines.append(f"{i}. {title} — {authors} ({year}) — DOI: {doi}")
    papers_formatted = "\n".join(lines) if lines else "recently parsed articles"
    content = prompts.PAPERS_INGESTED.format(papers_formatted=papers_formatted)
    save_background_message(conversation_id, content, variant="info")
    _publish_sync(conversation_id, {"event": "background_update"})
    run_agent_continuation.apply_async(args=[conversation_id], countdown=1)


@celery_app.task(
    bind=True,
    queue="chat",
    max_retries=120,
    default_retry_delay=10,
    ignore_result=True,
)
def monitor_ingestion(self, conversation_id: str, job_ids: list[str]) -> None:
    """Poll article-fetcher and pdf-parser until all jobs complete, then trigger RAG continuation."""
    logger.debug("monitor_ingestion poll conv=%s job_ids=%s", conversation_id, job_ids)

    with httpx.Client(timeout=10.0) as client:
        fetch_statuses = {jid: _get_fetch_status(client, jid) for jid in job_ids}

        # STOP: all downloads failed
        if all(s == "failed" for s in fetch_statuses.values()):
            logger.warning("All article downloads failed for conv=%s", conversation_id)
            _publish_sync(conversation_id, {
                "event": "background_error",
                "detail": "All article downloads failed.",
                "retry_available": False,
            })
            return

        # Only check pdf-parser for jobs where article-fetcher is done
        done_fetch = [jid for jid, s in fetch_statuses.items() if s == "done"]
        parse_statuses = {jid: _get_parse_status(client, jid) for jid in done_fetch}

        # STOP: any parse failed
        if any(s == "failed" for s in parse_statuses.values()):
            logger.warning("Parse failure detected for conv=%s", conversation_id)
            _publish_sync(conversation_id, {
                "event": "background_error",
                "detail": "One or more articles failed to parse.",
                "retry_available": False,
            })
            return

        # WAIT: any download still running
        if any(s not in ("done", "failed") for s in fetch_statuses.values()):
            raise self.retry()

        # WAIT: any parse not yet completed
        if any(s != "completed" for s in parse_statuses.values()):
            raise self.retry()

    # SUCCESS: all fetched + all parsed
    completed_jobs = [jid for jid, s in parse_statuses.items() if s == "completed"]
    _trigger_rag_continuation(conversation_id, completed_jobs)
    logger.info("monitor_ingestion complete conv=%s", conversation_id)


def _on_monitor_ingestion_failure(self, exc, task_id, args, kwargs, einfo):
    """Called when monitor_ingestion exhausts retries. Log WARNING only."""
    conversation_id = args[0] if args else "unknown"
    logger.warning(
        "monitor_ingestion timed out after max retries for conv=%s — user already has initial response",
        conversation_id,
    )


monitor_ingestion.on_failure = _on_monitor_ingestion_failure
