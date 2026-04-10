"""Tests for OpenAlex search tool."""
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


@pytest.fixture
def mock_openalex_config(monkeypatch):
    """Mock OpenAlex configuration."""
    from app.config import settings

    monkeypatch.setattr(settings, "OPENALEX_API_KEY", "test-key-123")
    monkeypatch.setattr(settings, "BACKEND_INTERNAL_URL", "http://backend:8000")
    return settings


def test_openalex_search_no_conversation_context():
    """Returns an error message when no conversation context is set."""
    from app.tools.rag import _CURRENT_CONV_ID
    from app.tools.search import openalex_search

    _CURRENT_CONV_ID.set(None)
    result = openalex_search.invoke("aspirin synthesis")
    assert "no conversation context" in result.lower()


def test_openalex_search_returns_queued_message(mock_openalex_config):
    """Returns a queued message when conversation context is set."""
    from app.tools.rag import _CURRENT_CONV_ID
    from app.tools.search import openalex_search

    with patch("app.tools.search.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=202)
        _CURRENT_CONV_ID.set("conv-123")

        result = openalex_search.invoke("aspirin synthesis")

    assert isinstance(result, str)
    assert "queued" in result.lower()


def test_openalex_search_posts_to_backend_queue(mock_openalex_config):
    """Verifies tool POSTs to backend with correct payload."""
    from app.tools.rag import _CURRENT_CONV_ID
    from app.tools.search import openalex_search

    with patch("app.tools.search.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=202)
        _CURRENT_CONV_ID.set("conv-abc-123")

        result = openalex_search.invoke(
            {"query": "molecular docking", "max_results": 10}
        )

    assert "queued" in result.lower()
    mock_post.assert_called_once()

    # Verify payload
    call_kwargs = mock_post.call_args.kwargs
    payload = call_kwargs.get("json")
    assert payload["type"] == "openalex_search"
    assert payload["conversation_id"] == "conv-abc-123"
    assert payload["query"] == "molecular docking"
    assert payload["max_results"] == 10


def test_openalex_search_default_max_results(mock_openalex_config):
    """Uses default max_results if not provided."""
    from app.tools.rag import _CURRENT_CONV_ID
    from app.tools.search import openalex_search

    with patch("app.tools.search.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=202)
        _CURRENT_CONV_ID.set("conv-test")

        result = openalex_search.invoke("reaction prediction")

    payload = mock_post.call_args.kwargs.get("json")
    assert payload["max_results"] == 5  # default


def test_openalex_search_handles_backend_error(mock_openalex_config):
    """Returns error message if backend is unreachable."""
    from app.tools.rag import _CURRENT_CONV_ID
    from app.tools.search import openalex_search

    with patch("app.tools.search.httpx.post") as mock_post:
        mock_post.side_effect = Exception("Connection failed")
        _CURRENT_CONV_ID.set("conv-test")

        result = openalex_search.invoke("some query")

    assert "unavailable" in result.lower()


def test_openalex_search_requires_api_key(monkeypatch):
    """Returns error if OpenAlex API key not configured."""
    from app.config import settings
    from app.tools.rag import _CURRENT_CONV_ID
    from app.tools.search import openalex_search

    monkeypatch.setattr(settings, "OPENALEX_API_KEY", "")
    _CURRENT_CONV_ID.set("conv-test")

    result = openalex_search.invoke("test query")

    assert "api key not configured" in result.lower()
    assert "semantic scholar" in result.lower()
