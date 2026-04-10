"""Integration tests for OpenAlex search feature critical fixes."""
import json
import uuid
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.config import settings
from app.models import ChatMessage, Conversation
from app.worker.tasks.continuation import (
    _trigger_rag_continuation,
    run_openalex_search,
)


@pytest.fixture
def conversation_id():
    return str(uuid.uuid4())


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    with patch("app.worker.tasks.continuation.get_sync_redis") as mock:
        yield mock.return_value


class TestOpenAlexIntegration:
    """Integration tests for OpenAlex feature."""

    def test_rag_continuation_retrieves_both_s2_and_openalex_papers(
        self, conversation_id, mock_redis
    ):
        """Verify RAG continuation retrieves both S2 and OpenAlex papers."""
        # Setup: mixed papers from both sources
        s2_paper_id = "s2-paper-123"
        oa_paper_id = "oa-paper-456"

        s2_meta = {
            "doi": "10.1234/s2.2024",
            "title": "S2 Paper",
            "authors": "Smith et al",
            "year": 2024,
        }
        oa_meta = {
            "doi": "10.5678/oa.2024",
            "title": "OpenAlex Paper",
            "authors": "Jones et al",
            "year": 2024,
        }

        def mock_get(key):
            if key == f"s2_paper_meta:{s2_paper_id}":
                return json.dumps(s2_meta)
            elif key == f"openalex_paper_meta:{oa_paper_id}":
                return json.dumps(oa_meta)
            return None

        mock_redis.get.side_effect = mock_get

        with patch("app.worker.tasks.continuation.run_agent_continuation.apply_async"):
            with patch(
                "app.worker.tasks.continuation.save_background_message"
            ) as mock_save:
                _trigger_rag_continuation(conversation_id, [s2_paper_id, oa_paper_id])

        # Verify both papers were retrieved
        saved_message = mock_save.call_args[0][1]
        assert "S2 Paper" in saved_message
        assert "OpenAlex Paper" in saved_message
        assert "Smith et al" in saved_message
        assert "Jones et al" in saved_message

    def test_openalex_endpoint_uses_auth_header_not_query_params(self):
        """Verify API key is in Authorization header, not URL."""
        from app.api.routes.internal import OpenAlexSearchRequest, openalex_search

        if not settings.OPENALEX_API_KEY:
            pytest.skip("OPENALEX_API_KEY not configured")

        payload = OpenAlexSearchRequest(query="test", max_results=5)

        with patch("app.api.routes.internal.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": []}
            mock_get.return_value = mock_response

            openalex_search(payload)

        # Verify Authorization header is used
        call_kwargs = mock_get.call_args.kwargs
        assert "headers" in call_kwargs
        assert "Authorization" in call_kwargs["headers"]

        # Verify API key is NOT in URL params
        assert "api_key" not in call_kwargs.get("params", {})

    def test_exception_handling_distinguishes_timeout_from_connection_error(
        self, conversation_id, mock_redis
    ):
        """Verify timeout and connection errors are handled separately."""
        with patch("app.worker.tasks.continuation.httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value.__enter__.return_value = mock_instance

            # Test timeout
            mock_instance.post.side_effect = httpx.TimeoutException("Timeout")

            with patch("app.worker.tasks.continuation.save_background_message") as mock_save:
                with patch("app.worker.tasks.continuation._publish_sync"):
                    run_openalex_search(conversation_id, "test")

            # Verify timeout-specific message saved
            timeout_message = mock_save.call_args[0][1]
            assert "timeout" in timeout_message.lower()

            # Test connection error
            mock_save.reset_mock()
            mock_instance.post.side_effect = httpx.ConnectError("Connection failed")

            with patch("app.worker.tasks.continuation.save_background_message") as mock_save:
                with patch("app.worker.tasks.continuation._publish_sync"):
                    run_openalex_search(conversation_id, "test")

            # Verify connection-specific message saved
            connection_message = mock_save.call_args[0][1]
            assert "unreachable" in connection_message.lower() or "connection" in connection_message.lower()

    def test_celery_task_uses_config_url_not_hardcoded(self, conversation_id, mock_redis):
        """Verify Celery task uses BACKEND_INTERNAL_URL setting."""
        with patch("app.worker.tasks.continuation.httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value.__enter__.return_value = mock_instance
            mock_response = MagicMock()
            mock_response.json.return_value = {"papers": []}
            mock_instance.post.return_value = mock_response

            with patch("app.worker.tasks.continuation.save_background_message"):
                with patch("app.worker.tasks.continuation._publish_sync"):
                    run_openalex_search(conversation_id, "test")

            # Verify config URL was used
            call_args = mock_instance.post.call_args[0][0]
            assert call_args.startswith(settings.BACKEND_INTERNAL_URL)
            assert "/internal/openalex-search" in call_args

    def test_author_extraction_handles_malformed_data(self):
        """Verify author extraction doesn't crash on malformed author data."""
        from app.api.routes.internal import OpenAlexSearchRequest, openalex_search

        if not settings.OPENALEX_API_KEY:
            pytest.skip("OPENALEX_API_KEY not configured")

        payload = OpenAlexSearchRequest(query="test", max_results=5)

        # Mock OpenAlex response with missing author data
        malformed_result = {
            "title": "Paper with bad author data",
            "authorships": [
                {"author": None},  # Missing author dict
                {},  # Missing author key entirely
                {"author": {"display_name": None}},  # Null display_name
                {"author": {"display_name": "Valid Author"}},  # Valid
            ],
            "publication_year": 2024,
            "doi": "10.1234/test",
            "cited_by_count": 5,
        }

        with patch("app.api.routes.internal.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": [malformed_result]}
            mock_get.return_value = mock_response

            result = openalex_search(payload)

        # Verify no crash, and paper was processed
        assert "papers" in result
        assert len(result["papers"]) > 0
        paper = result["papers"][0]
        assert paper["title"] == "Paper with bad author data"
        # Should have extracted at least one valid author
        assert "author" in paper["authors"].lower() or "unknown" in paper["authors"].lower()

    def test_missing_api_key_returns_explicit_error(self):
        """Verify missing API key returns explicit error, not silent empty result."""
        from app.api.routes.internal import OpenAlexSearchRequest, openalex_search

        payload = OpenAlexSearchRequest(query="test", max_results=5)

        # Temporarily disable API key
        with patch("app.api.routes.internal.settings.OPENALEX_API_KEY", ""):
            result = openalex_search(payload)

        # Should have explicit error, not just empty papers
        assert "error" in result
        assert len(result.get("error", "")) > 0
        assert "not configured" in result["error"].lower()

    def test_redis_caching_error_doesnt_block_queue(self, conversation_id, mock_redis):
        """Verify Redis caching failure doesn't prevent search queue."""
        from app.api.routes.internal import QueueBackgroundToolRequest, queue_background_tool

        payload = QueueBackgroundToolRequest(
            type="openalex_search",
            conversation_id=conversation_id,
            query="test",
            max_results=5,
        )

        # Simulate Redis failure
        mock_redis.set.side_effect = Exception("Redis connection failed")

        with patch("app.api.routes.internal.run_openalex_search.delay") as mock_delay:
            result = queue_background_tool(payload)

        # Verify queue succeeded despite Redis error
        assert result["status"] == "queued"
        mock_delay.assert_called_once()


class TestOpenAlexErrorMessages:
    """Test that error messages are user-friendly and don't leak credentials."""

    def test_error_messages_do_not_contain_credentials(self, conversation_id, mock_redis):
        """Verify error messages don't leak API keys or sensitive URLs."""
        with patch("app.worker.tasks.continuation.httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value.__enter__.return_value = mock_instance

            # Simulate connection error with sensitive URL info
            exc = httpx.ConnectError("Failed to connect to http://backend:8000?api_key=secret")
            mock_instance.post.side_effect = exc

            with patch("app.worker.tasks.continuation.save_background_message") as mock_save:
                with patch("app.worker.tasks.continuation._publish_sync"):
                    run_openalex_search(conversation_id, "test")

            # Get saved error message
            error_message = mock_save.call_args[0][1]

            # Verify no sensitive data leaked
            assert "secret" not in error_message.lower()
            assert "api_key" not in error_message.lower()
            assert "http://" not in error_message  # URL details hidden
