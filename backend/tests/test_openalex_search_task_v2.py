"""Tests for run_openalex_search Celery task - FIXED VERSION.

CRITICAL TEST GAPS: Verifies Celery task orchestration, article jobs, and message flow.
"""
import json
import uuid
from unittest.mock import MagicMock, patch, AsyncMock

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
    """Sample OpenAlex response with proper structure."""
    return [
        {
            "doi": "10.1234/aspirin.2020",
            "title": "Aspirin Synthesis: A Modern Approach",
            "authors": "John Smith, Alice Johnson",
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


def test_run_openalex_search_success(conversation_id, mock_redis, sample_openalex_papers):
    """Successful search saves background message and publishes event."""
    with patch("httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": sample_openalex_papers}
        mock_client.post.return_value = mock_response

        with patch("app.worker.tasks.continuation.save_background_message") as mock_save_msg:
            with patch("app.worker.tasks.continuation.run_agent_continuation"):
                run_openalex_search(conversation_id, "aspirin synthesis", max_results=2)

    # Verify API was called
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert "/internal/openalex-search" in call_args[0][0]

    # Verify background message was saved (published)
    mock_redis.publish.assert_called()


def test_run_openalex_search_no_results(conversation_id, mock_redis):
    """Empty results save error message."""
    with patch("httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": []}
        mock_client.post.return_value = mock_response

        run_openalex_search(conversation_id, "nonexistent topic")

    # Verify error message was saved
    mock_redis.publish.assert_called()
    call_args = mock_redis.publish.call_args
    assert "no papers found" in call_args[0][1].lower()


def test_run_openalex_search_api_error(conversation_id, mock_redis):
    """API error saves error message."""
    with patch("httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.post.side_effect = Exception("API Error")

        run_openalex_search(conversation_id, "test")

    # Verify error message was published
    mock_redis.publish.assert_called()


def test_run_openalex_search_releases_dedup_lock(conversation_id, mock_redis):
    """Dedup lock is released in finally block."""
    dedup_key = "openalex_search_active:test:abc123"

    with patch("httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": []}
        mock_client.post.return_value = mock_response

        run_openalex_search(conversation_id, "test", dedup_key=dedup_key)

    # Verify dedup lock was deleted
    mock_redis.delete.assert_called_with(dedup_key)


def test_run_openalex_search_dispatches_continuation(conversation_id, mock_redis):
    """On success, run_agent_continuation is dispatched."""
    papers = [
        {"title": "Paper", "doi": "10.1234/test", "abstract": "Abstract", "authors": "Author", "year": 2023, "citation_count": 5}
    ]

    with patch("httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": papers}
        mock_client.post.return_value = mock_response

        with patch(
            "app.worker.tasks.continuation.run_agent_continuation.apply_async"
        ) as mock_dispatch:
            run_openalex_search(conversation_id, "test")

        mock_dispatch.assert_called_once()


def test_run_openalex_search_submits_article_jobs(conversation_id, mock_redis):
    """Papers with DOIs are submitted to article-fetcher."""
    papers = [
        {
            "doi": "10.1234/paper1",
            "title": "Paper 1",
            "authors": "Author A",
            "year": 2020,
            "abstract": "Abstract 1",
            "citation_count": 10,
        },
        {
            "doi": "10.5678/paper2",
            "title": "Paper 2",
            "authors": "Author B",
            "year": 2021,
            "abstract": "Abstract 2",
            "citation_count": 5,
        },
    ]

    with patch("httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": papers}
        mock_client.post.return_value = mock_response

        with patch(
            "app.worker.tasks.continuation._submit_article_jobs"
        ) as mock_submit:
            mock_submit.return_value = [
                {"job_id": "job-1", "doi": "10.1234/paper1"},
                {"job_id": "job-2", "doi": "10.5678/paper2"},
            ]
            with patch("app.worker.tasks.continuation.run_agent_continuation"):
                run_openalex_search(conversation_id, "test")

        # Verify article jobs were submitted
        mock_submit.assert_called_once()
        call_args = mock_submit.call_args
        dois = call_args[0][2]  # Third argument
        assert len(dois) == 2
        assert "10.1234/paper1" in dois
        assert "10.5678/paper2" in dois


def test_run_openalex_search_publishes_background_message(conversation_id, mock_redis):
    """Verify background_update SSE event is published."""
    papers = [
        {
            "doi": "10.1111/p1",
            "title": "Paper 1",
            "authors": "Author A",
            "year": 2023,
            "abstract": "Abstract",
            "citation_count": 10,
        }
    ]

    with patch("httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": papers}
        mock_client.post.return_value = mock_response

        with patch("app.worker.tasks.continuation._submit_article_jobs") as mock_submit:
            mock_submit.return_value = []
            with patch("app.worker.tasks.continuation.run_agent_continuation"):
                run_openalex_search(conversation_id, "test query")

    # Verify background_update was published to trigger frontend SSE re-enable
    calls = mock_redis.publish.call_args_list
    # Should have at least 2 calls: one for the results message, one for background_update
    assert len(calls) >= 2

    # Find the background_update event
    background_update_found = False
    for call in calls:
        if "background_update" in str(call):
            background_update_found = True
            break

    assert background_update_found, "background_update event not published"


def test_run_openalex_search_queues_monitor_ingestion(conversation_id, mock_redis):
    """Verify monitor_ingestion is queued after articles are submitted."""
    papers = [
        {"doi": "10.1234/test", "title": "Paper", "authors": "Author", "year": 2023, "abstract": "Abstract", "citation_count": 5}
    ]

    with patch("httpx.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": papers}
        mock_client.post.return_value = mock_response

        with patch(
            "app.worker.tasks.continuation._submit_article_jobs"
        ) as mock_submit:
            mock_submit.return_value = [{"job_id": "job-abc", "doi": "10.1234/test"}]

            with patch(
                "app.worker.tasks.continuation.monitor_ingestion.delay"
            ) as mock_monitor:
                with patch("app.worker.tasks.continuation.run_agent_continuation"):
                    run_openalex_search(conversation_id, "test")

            mock_monitor.assert_called_once()
            # Verify job_ids are passed
            call_args = mock_monitor.call_args
            assert "job-abc" in str(call_args)


def test_run_openalex_search_queues_to_chat_queue():
    """Verify task is queued to 'chat' queue."""
    # Verify task has queue="chat" config
    assert run_openalex_search.queue == "chat"
    # Verify it's set to ignore results (fire-and-forget)
    assert run_openalex_search.ignore_result is True
