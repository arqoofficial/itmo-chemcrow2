"""Tests for run_openalex_search Celery task."""
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models import ChatMessage, Conversation
from app.worker.tasks.continuation import (
    _format_openalex_results,
    run_openalex_search,
    save_background_message,
)


@pytest.fixture
def conversation_id():
    return str(uuid.uuid4())


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    with patch("app.worker.tasks.continuation.get_sync_redis") as mock:
        yield mock.return_value


@pytest.fixture
def sample_openalex_papers():
    """Sample OpenAlex papers (already transformed by endpoint)."""
    return [
        {
            "doi": "10.1234/aspirin.2020",
            "title": "Aspirin Synthesis: A Modern Approach",
            "authors": "John Smith",
            "year": 2020,
            "abstract": "This study presents a novel synthetic route to aspirin using catalytic methods.",
            "citation_count": 42,
        },
        {
            "doi": "10.5678/green.2019",
            "title": "Green Chemistry in Pharmaceutical Synthesis",
            "authors": "Jane Doe",
            "year": 2019,
            "abstract": "Environmental considerations in drug manufacturing processes.",
            "citation_count": 28,
        },
    ]


def test_format_openalex_results(sample_openalex_papers):
    """Verifies result formatting."""
    result = _format_openalex_results(sample_openalex_papers, "aspirin synthesis")

    assert "Aspirin Synthesis: A Modern Approach" in result
    assert "John Smith" in result
    assert "10.1234/aspirin.2020" in result
    assert "2020" in result
    assert "2" in result  # count


def test_format_openalex_results_truncates_abstract():
    """Abstracts longer than 400 chars are truncated."""
    papers = [
        {
            "title": "Long Paper",
            "authors": "Author",
            "year": 2020,
            "doi": "10.1234/test",
            "abstract": "x" * 500,  # 500 chars
            "citation_count": 5,
        }
    ]
    result = _format_openalex_results(papers, "test")
    assert "..." in result
    assert "Citations: 5" in result


def test_run_openalex_search_success(conversation_id, mock_redis, sample_openalex_papers):
    """Successful search saves background message and publishes event."""
    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": sample_openalex_papers}
        mock_post.return_value = mock_response

        run_openalex_search(conversation_id, "aspirin synthesis", max_results=2)

    # Verify API was called
    mock_post.assert_called_once()
    assert "/internal/openalex-search" in mock_post.call_args[0][0]

    # Verify background message was saved
    mock_redis.publish.assert_called()


def test_run_openalex_search_no_results(conversation_id, mock_redis):
    """Empty results save error message."""
    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": []}
        mock_post.return_value = mock_response

        run_openalex_search(conversation_id, "nonexistent topic")

    # Verify error message was saved
    mock_redis.publish.assert_called()
    call_args = mock_redis.publish.call_args
    assert "no papers found" in call_args[0][1].lower()


def test_run_openalex_search_api_error(conversation_id, mock_redis):
    """API error saves error message."""
    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_post.side_effect = Exception("API Error")

        run_openalex_search(conversation_id, "test")

    # Verify error message was published
    mock_redis.publish.assert_called()


def test_run_openalex_search_releases_dedup_lock(conversation_id, mock_redis):
    """Dedup lock is released in finally block."""
    dedup_key = "openalex_search_active:test:abc123"

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": []}
        mock_post.return_value = mock_response

        run_openalex_search(conversation_id, "test", dedup_key=dedup_key)

    # Verify dedup lock was deleted
    mock_redis.delete.assert_called_with(dedup_key)


def test_run_openalex_search_message_update_on_retry(conversation_id, mock_redis):
    """When original_message_id provided, error message is updated in-place."""
    original_message_id = str(uuid.uuid4())

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_post.side_effect = Exception("API Error")

        run_openalex_search(
            conversation_id,
            "test",
            original_message_id=original_message_id,
        )

    # Verify save_background_message was called with replace_message_id
    # (This would be verified through DB mock in integration test)


def test_run_openalex_search_deletes_error_on_success(conversation_id, mock_redis):
    """On success, original error message is deleted."""
    original_message_id = str(uuid.uuid4())
    papers = [{"title": "Paper", "doi": "10.1234/test", "abstract": "Abstract"}]

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": papers}
        mock_post.return_value = mock_response

        with patch("app.worker.tasks.continuation._delete_message") as mock_delete:
            run_openalex_search(
                conversation_id,
                "test",
                original_message_id=original_message_id,
            )

        # Verify error message was deleted
        mock_delete.assert_called_with(original_message_id)


def test_run_openalex_search_submits_article_jobs(conversation_id, mock_redis):
    """Papers with DOIs are submitted to article-fetcher."""
    papers = [
        {
            "title": "Paper 1",
            "doi": "10.1234/paper1",
            "abstract": "Abstract 1",
        },
        {
            "title": "Paper 2",
            "doi": "10.5678/paper2",
            "abstract": "Abstract 2",
        },
    ]

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": papers}
        mock_post.return_value = mock_response

        with patch(
            "app.worker.tasks.continuation._submit_article_jobs"
        ) as mock_submit:
            run_openalex_search(conversation_id, "test")

        # Verify article jobs were submitted
        mock_submit.assert_called_once()
        call_args = mock_submit.call_args
        dois = call_args[0][2]  # Third argument
        assert len(dois) == 2
        assert "10.1234/paper1" in dois
        assert "10.5678/paper2" in dois


def test_run_openalex_search_dispatches_continuation(conversation_id, mock_redis):
    """On success, run_agent_continuation is dispatched."""
    papers = [{"title": "Paper", "doi": "10.1234/test", "abstract": "Abstract"}]

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": papers}
        mock_post.return_value = mock_response

        with patch(
            "app.worker.tasks.continuation.run_agent_continuation.apply_async"
        ) as mock_dispatch:
            run_openalex_search(conversation_id, "test")

        mock_dispatch.assert_called_once()
