"""Unit tests for article helper functions in the chat Celery task."""
import json
from unittest.mock import MagicMock, patch

import pytest


# ── _extract_dois ────────────────────────────────────────────────────────────

def test_extract_dois_finds_dois_in_tool_output():
    from app.worker.tasks.chat import _extract_dois

    output = (
        "- **Paper One** (2023)\n"
        "  DOI: 10.1038/s41586-021-03819-2\n"
        "- **Paper Two** (2022)\n"
        "  DOI: 10.1021/acs.nanolett.1c02548\n"
    )
    result = _extract_dois(output)
    assert result == ["10.1038/s41586-021-03819-2", "10.1021/acs.nanolett.1c02548"]


def test_extract_dois_skips_na():
    from app.worker.tasks.chat import _extract_dois

    output = "  DOI: N/A\n  DOI: 10.1234/test\n"
    result = _extract_dois(output)
    assert result == ["10.1234/test"]


def test_extract_dois_returns_empty_when_none():
    from app.worker.tasks.chat import _extract_dois

    result = _extract_dois("No DOIs here at all.")
    assert result == []


def test_extract_dois_deduplicates():
    from app.worker.tasks.chat import _extract_dois

    output = "  DOI: 10.1/a\n  DOI: 10.1/a\n"
    result = _extract_dois(output)
    assert result == ["10.1/a"]


# ── _get_conversation_article_jobs ──────────────────────────────────────────

def test_get_conversation_article_jobs_returns_parsed_list():
    from app.worker.tasks.chat import _get_conversation_article_jobs

    r = MagicMock()
    r.lrange.return_value = [
        json.dumps({"doi": "10.1/a", "job_id": "uuid-1"}),
        json.dumps({"doi": "10.1/b", "job_id": "uuid-2"}),
    ]
    result = _get_conversation_article_jobs(r, "conv-123")
    assert result == [
        {"doi": "10.1/a", "job_id": "uuid-1"},
        {"doi": "10.1/b", "job_id": "uuid-2"},
    ]
    r.lrange.assert_called_once_with("conversation:conv-123:article_jobs", 0, -1)


def test_get_conversation_article_jobs_returns_empty_when_key_absent():
    from app.worker.tasks.chat import _get_conversation_article_jobs

    r = MagicMock()
    r.lrange.return_value = []
    result = _get_conversation_article_jobs(r, "conv-empty")
    assert result == []


# ── _build_article_status_block ─────────────────────────────────────────────

def test_build_article_status_block_formats_statuses():
    from app.worker.tasks.chat import _build_article_status_block

    jobs = [
        {"doi": "10.1/a", "status": "done"},
        {"doi": "10.1/b", "status": "running"},
        {"doi": "10.1/c", "status": "failed"},
        {"doi": "10.1/d", "status": "pending"},
    ]
    block = _build_article_status_block(jobs)
    assert "[Article Download Status]" in block
    assert "10.1/a: available" in block
    assert "10.1/b: downloading" in block
    assert "10.1/c: failed" in block
    assert "10.1/d: downloading" in block


def test_build_article_status_block_returns_empty_for_no_jobs():
    from app.worker.tasks.chat import _build_article_status_block

    assert _build_article_status_block([]) == ""
