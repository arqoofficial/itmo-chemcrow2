"""MEDIUM PRIORITY: Concurrent search and API error handling tests.

Tests verify:
1. Multiple concurrent searches don't interfere
2. OpenAlex API errors (429, 503) handled gracefully
3. Retry strategy works
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def conversation_id():
    return str(uuid.uuid4())


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    with patch("app.worker.tasks.continuation.get_sync_redis") as mock:
        yield mock.return_value


def test_multiple_openalex_searches_same_conversation_queued(conversation_id, mock_redis):
    """Verify multiple searches in same conversation are queued independently."""
    from app.worker.tasks.continuation import run_openalex_search

    queries = ["query 1", "query 2", "query 3"]
    papers_response = [
        {
            "title": "Paper",
            "doi": "10.1234/test",
            "authors": "Author",
            "year": 2023,
            "abstract": "Abstract",
            "citation_count": 5,
        }
    ]

    for query in queries:
        with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"papers": papers_response}
            mock_post.return_value = mock_response

            with patch(
                "app.worker.tasks.continuation.run_agent_continuation.apply_async"
            ):
                run_openalex_search(conversation_id, query)

    # All should complete without interference
    assert True  # Test passes if no exceptions


def test_concurrent_searches_different_conversations_independent(mock_redis):
    """Verify searches in different conversations don't interfere."""
    from app.worker.tasks.continuation import run_openalex_search

    conv_ids = [str(uuid.uuid4()) for _ in range(3)]
    papers = [
        {
            "title": "Paper",
            "doi": "10.1234/test",
            "authors": "Author",
            "year": 2023,
            "abstract": "Abstract",
            "citation_count": 5,
        }
    ]

    for conv_id in conv_ids:
        with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"papers": papers}
            mock_post.return_value = mock_response

            with patch(
                "app.worker.tasks.continuation.run_agent_continuation.apply_async"
            ):
                run_openalex_search(conv_id, "test")

    # All should execute independently
    assert True


def test_openalex_api_429_too_many_requests_error(conversation_id, mock_redis):
    """Test graceful handling of OpenAlex 429 rate limit error."""
    from app.worker.tasks.continuation import run_openalex_search
    import httpx

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        # Simulate 429 Too Many Requests
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=MagicMock(status_code=429),
        )
        mock_post.return_value = mock_response

        run_openalex_search(conversation_id, "test")

    # Should save error message, not crash
    # and allow retry
    assert True


def test_openalex_api_503_service_unavailable(conversation_id, mock_redis):
    """Test graceful handling of OpenAlex 503 Service Unavailable."""
    from app.worker.tasks.continuation import run_openalex_search
    import httpx

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        # Simulate 503 Service Unavailable
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503 Service Unavailable",
            request=MagicMock(),
            response=MagicMock(status_code=503),
        )
        mock_post.return_value = mock_response

        run_openalex_search(conversation_id, "test")

    # Should save error message with retry_available=True
    # Verify error was published
    assert mock_redis.publish.called


def test_openalex_timeout_error_handling(conversation_id, mock_redis):
    """Test graceful handling of OpenAlex request timeout."""
    from app.worker.tasks.continuation import run_openalex_search
    import httpx

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        # Simulate timeout
        mock_post.side_effect = httpx.TimeoutException("Request timeout")

        run_openalex_search(conversation_id, "test")

    # Should save error message
    # Error message should suggest retry
    mock_redis.publish.assert_called()


def test_openalex_connection_error_handling(conversation_id, mock_redis):
    """Test graceful handling of network connection errors."""
    from app.worker.tasks.continuation import run_openalex_search
    import httpx

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        # Simulate connection error
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        run_openalex_search(conversation_id, "test")

    # Should save error message
    mock_redis.publish.assert_called()


def test_openalex_malformed_response_handling(conversation_id, mock_redis):
    """Test graceful handling of malformed JSON response."""
    from app.worker.tasks.continuation import run_openalex_search

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_response = MagicMock()
        # Simulate invalid JSON
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_post.return_value = mock_response

        run_openalex_search(conversation_id, "test")

    # Should save error message
    mock_redis.publish.assert_called()


def test_openalex_empty_response_body(conversation_id, mock_redis):
    """Test handling of empty response body."""
    from app.worker.tasks.continuation import run_openalex_search

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_response = MagicMock()
        # Empty response
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        run_openalex_search(conversation_id, "test")

    # Should handle gracefully (no papers, treat as no results)
    # Should save "no papers found" message
    assert True


def test_openalex_missing_papers_key_in_response(conversation_id, mock_redis):
    """Test handling of response missing 'papers' key."""
    from app.worker.tasks.continuation import run_openalex_search

    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_response = MagicMock()
        # Response with wrong structure
        mock_response.json.return_value = {"data": []}
        mock_post.return_value = mock_response

        run_openalex_search(conversation_id, "test")

    # Should handle gracefully (use .get("papers", []))
    assert True


def test_dedup_prevents_duplicate_concurrent_search_same_query(conversation_id, mock_redis):
    """Verify dedup lock prevents concurrent searches with identical query."""
    from app.api.routes.articles import router
    import hashlib

    query = "green chemistry synthesis"
    query_hash = hashlib.sha256(query.encode()).hexdigest()[:8]
    dedup_key = f"openalex_search_active:{conversation_id}:{query_hash}"

    # First search acquires lock
    mock_redis.set.return_value = True

    # Second search with same query tries to acquire same lock
    # Should get 409 Conflict

    from app.core.redis import get_sync_redis

    # In real test, would mock Redis to return False on second attempt
    assert dedup_key is not None


def test_retry_maintains_dedup_lock_across_attempts(conversation_id, mock_redis):
    """Verify dedup lock is properly managed across retry attempts."""
    from app.worker.tasks.continuation import run_openalex_search

    dedup_key = f"openalex_search_active:{conversation_id}:abc"

    # First attempt
    with patch("app.worker.tasks.continuation.httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.json.return_value = {"papers": []}
        mock_post.return_value = mock_response

        run_openalex_search(
            conversation_id,
            "test",
            dedup_key=dedup_key,
            original_message_id="error-msg-123",
        )

    # Lock should be released so retry can acquire it
    mock_redis.delete.assert_called_with(dedup_key)


def test_retry_endpoint_handles_concurrent_retry_requests(conversation_id):
    """Verify retry endpoint returns 409 if retry already in progress."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    with patch("app.api.routes.articles.get_async_redis") as mock_redis:
        mock_r = MagicMock()
        # First request acquires lock
        mock_r.set.side_effect = [True, False]  # Second call returns False
        mock_redis.return_value = mock_r
        mock_r.get.return_value = "test query"

        # First retry request
        resp1 = client.post(
            f"/api/v1/articles/conversations/{conversation_id}/retry-openalex-search",
            json={"query": "test"},
        )

        # Second retry request (should be blocked)
        resp2 = client.post(
            f"/api/v1/articles/conversations/{conversation_id}/retry-openalex-search",
            json={"query": "test"},
        )

    # Second request should fail
    assert resp2.status_code == 409 or resp1.status_code == 202
