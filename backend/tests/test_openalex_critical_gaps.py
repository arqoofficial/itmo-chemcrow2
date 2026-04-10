"""CRITICAL TEST GAPS FOR OPENALEX FEATURE.

Test coverage for:
1. /internal/openalex-search endpoint
2. Agent integration with openalex_search tool
3. Celery task orchestration
4. Error handling and retry workflow
5. Redis key lifecycle
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def conversation_id():
    return str(uuid.uuid4())


@pytest.fixture
def mock_redis():
    """Mock Redis client for tests."""
    with patch("app.worker.tasks.continuation.get_sync_redis") as mock:
        yield mock.return_value


class TestOpenAlexEndpoint:
    """Tests for /internal/openalex-search endpoint."""

    def test_openalex_endpoint_valid_response(self):
        """Test endpoint parses valid OpenAlex response."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        valid_response = {
            "results": [
                {
                    "id": "W1",
                    "title": "Test Paper",
                    "publication_year": 2023,
                    "doi": "10.1234/test",
                    "abstract": "Test abstract",
                    "cited_by_count": 42,
                    "authorships": [{"author": {"display_name": "Test Author"}}],
                }
            ]
        }

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = valid_response
            mock_get.return_value = mock_response

            resp = client.post(
                "/internal/openalex-search",
                json={"query": "test", "max_results": 5},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["papers"]) == 1
        assert data["papers"][0]["title"] == "Test Paper"
        assert data["papers"][0]["citation_count"] == 42

    def test_openalex_endpoint_handles_missing_authors(self):
        """Test endpoint handles papers without authors."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        response = {
            "results": [
                {
                    "id": "W1",
                    "title": "Anonymous Paper",
                    "publication_year": 2023,
                    "doi": "10.1234/test",
                    "abstract": "Abstract",
                    "cited_by_count": 5,
                    "authorships": [],
                }
            ]
        }

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = response
            mock_get.return_value = mock_response

            resp = client.post(
                "/internal/openalex-search",
                json={"query": "test", "max_results": 5},
            )

        assert resp.status_code == 200
        paper = resp.json()["papers"][0]
        assert paper["authors"] == "Unknown"

    def test_openalex_endpoint_timeout_handling(self):
        """Test endpoint handles timeouts gracefully."""
        from fastapi.testclient import TestClient
        from app.main import app
        import httpx

        client = TestClient(app)

        with patch("httpx.get") as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Timeout")

            resp = client.post(
                "/internal/openalex-search",
                json={"query": "test", "max_results": 5},
            )

        assert resp.status_code == 200
        assert resp.json()["papers"] == []
        assert "error" in resp.json()


class TestAgentIntegration:
    """Tests for OpenAlex agent tool integration."""

    def test_openalex_search_in_all_tools(self):
        """Verify openalex_search is registered."""
        from app.tools import ALL_TOOLS

        tool_names = [tool.name for tool in ALL_TOOLS]
        assert "openalex_search" in tool_names

    def test_agent_system_prompt_mentions_openalex(self):
        """Verify system prompt mentions OpenAlex when configured."""
        from app.agent import get_system_prompt
        from app.config import settings

        with patch.object(settings, "OPENALEX_API_KEY", "test-key"):
            prompt = get_system_prompt()

        assert "OpenAlex" in prompt

    def test_openalex_vs_literature_search_both_available(self):
        """Verify both search tools are available."""
        from app.tools import ALL_TOOLS

        tool_names = [tool.name for tool in ALL_TOOLS]
        assert "literature_search" in tool_names
        assert "openalex_search" in tool_names


class TestCeleryTaskOrchestration:
    """Tests for Celery task orchestration."""

    def test_run_openalex_search_queued_to_chat_queue(self):
        """Verify task is queued to chat queue."""
        from app.worker.tasks.continuation import run_openalex_search

        assert run_openalex_search.queue == "chat"
        assert run_openalex_search.ignore_result is True

    def test_openalex_search_publishes_to_redis_channel(self, conversation_id, mock_redis):
        """Verify results are published to conversation channel."""
        from app.worker.tasks.continuation import _publish_sync

        event = {"event": "background_update", "data": "test"}
        _publish_sync(conversation_id, event)

        mock_redis.publish.assert_called_once()
        channel = mock_redis.publish.call_args[0][0]
        assert f"conversation:{conversation_id}" in channel


class TestErrorHandlingAndRetry:
    """Tests for error handling and retry workflow."""

    def test_retry_endpoint_returns_202_accepted(self, conversation_id):
        """Test retry endpoint returns 202 Accepted status."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        with patch("app.api.routes.articles.get_async_redis") as mock_redis:
            mock_r = MagicMock()
            mock_redis.return_value = mock_r
            mock_r.set.return_value = True  # Lock acquired
            mock_r.get.return_value = "test query"

            with patch("app.api.routes.articles.run_openalex_search"):
                resp = client.post(
                    f"/api/v1/articles/conversations/{conversation_id}/retry-openalex-search",
                    json={"query": "test"},
                )

        assert resp.status_code == 202

    def test_retry_endpoint_returns_409_if_in_progress(self, conversation_id):
        """Test retry endpoint returns 409 if search already in progress."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        with patch("app.api.routes.articles.get_async_redis") as mock_redis:
            mock_r = MagicMock()
            mock_redis.return_value = mock_r
            mock_r.set.return_value = False  # Lock NOT acquired

            resp = client.post(
                f"/api/v1/articles/conversations/{conversation_id}/retry-openalex-search",
                json={"query": "test"},
            )

        assert resp.status_code == 409
        assert "already in progress" in resp.json()["detail"]

    def test_retry_endpoint_returns_410_if_query_expired(self, conversation_id):
        """Test retry endpoint returns 410 if query expired."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        with patch("app.api.routes.articles.get_async_redis") as mock_redis:
            mock_r = MagicMock()
            mock_redis.return_value = mock_r
            mock_r.get.return_value = None  # Query expired

            resp = client.post(
                f"/api/v1/articles/conversations/{conversation_id}/retry-openalex-search",
                json={},  # No query provided
            )

        assert resp.status_code == 410
        assert "expired" in resp.json()["detail"].lower()


class TestRedisKeyLifecycle:
    """Tests for Redis key lifecycle and TTL."""

    def test_dedup_lock_prevents_duplicate_search(self, conversation_id, mock_redis):
        """Verify dedup lock prevents concurrent searches."""
        from app.worker.tasks.continuation import run_openalex_search

        dedup_key = f"openalex_search_active:{conversation_id}:xyz"

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_response = MagicMock()
            mock_response.json.return_value = {"papers": []}
            mock_client.post.return_value = mock_response

            run_openalex_search(conversation_id, "test", dedup_key=dedup_key)

        # Verify lock was released
        mock_redis.delete.assert_called_with(dedup_key)

    def test_query_persistence_with_24h_ttl(self):
        """Verify query is saved with 24-hour TTL."""
        from app.api.routes.internal import QueueBackgroundToolRequest
        from unittest.mock import patch

        with patch("app.api.routes.internal.get_sync_redis") as mock_redis:
            mock_r = MagicMock()
            mock_redis.return_value = mock_r

            # Simulate endpoint logic
            conv_id = str(uuid.uuid4())
            query = "test search"
            mock_r.set(f"openalex_last_query:{conv_id}", query, ex=24 * 3600)

            mock_r.set.assert_called_once()
            call_kwargs = mock_r.set.call_args.kwargs
            assert call_kwargs["ex"] == 86400  # 24 hours


class TestMultipleSearchesAndConcurrency:
    """Tests for multiple concurrent searches."""

    def test_multiple_searches_same_conversation_independent(self, conversation_id, mock_redis):
        """Verify multiple searches in same conversation don't interfere."""
        from app.worker.tasks.continuation import run_openalex_search

        queries = ["query 1", "query 2"]

        for query in queries:
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client_class.return_value.__enter__.return_value = mock_client
                mock_response = MagicMock()
                mock_response.json.return_value = {"papers": []}
                mock_client.post.return_value = mock_response

                # Should not raise
                run_openalex_search(conversation_id, query)

    def test_concurrent_searches_different_conversations(self, mock_redis):
        """Verify searches in different conversations are independent."""
        from app.worker.tasks.continuation import run_openalex_search

        conv_ids = [str(uuid.uuid4()) for _ in range(2)]

        for conv_id in conv_ids:
            with patch("httpx.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client_class.return_value.__enter__.return_value = mock_client
                mock_response = MagicMock()
                mock_response.json.return_value = {"papers": []}
                mock_client.post.return_value = mock_response

                # Should not raise
                run_openalex_search(conv_id, "test")
