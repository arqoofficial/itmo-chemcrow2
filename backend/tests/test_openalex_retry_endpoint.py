"""Tests for OpenAlex search retry endpoint."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def conversation_id():
    return str(uuid.uuid4())


@pytest.fixture
def user_headers():
    """Headers for authenticated user."""
    return {"Authorization": "Bearer test-token"}


@pytest.mark.asyncio
async def test_retry_openalex_search_returns_202(conversation_id, user_headers):
    """Successful retry request returns 202 Accepted."""
    with patch("app.api.routes.articles.get_async_redis") as mock_redis:
        mock_redis.return_value = AsyncMock()
        mock_redis.return_value.set.return_value = True  # Lock acquired
        mock_redis.return_value.get.return_value = "molecule synthesis"

        with patch("app.api.routes.articles.run_openalex_search") as mock_task:
            client = TestClient(app)
            response = client.post(
                f"/api/v1/articles/conversations/{conversation_id}/retry-openalex-search",
                json={"query": "molecule synthesis"},
                headers=user_headers,
            )

    assert response.status_code == 202


@pytest.mark.asyncio
async def test_retry_openalex_search_409_if_in_progress(conversation_id, user_headers):
    """Returns 409 Conflict if search already in progress."""
    with patch("app.api.routes.articles.get_async_redis") as mock_redis:
        mock_redis.return_value = AsyncMock()
        mock_redis.return_value.set.return_value = False  # Lock NOT acquired

        client = TestClient(app)
        response = client.post(
            f"/api/v1/articles/conversations/{conversation_id}/retry-openalex-search",
            json={"query": "molecule synthesis"},
            headers=user_headers,
        )

    assert response.status_code == 409
    assert "already in progress" in response.json()["detail"]


@pytest.mark.asyncio
async def test_retry_openalex_search_410_if_query_expired(
    conversation_id, user_headers
):
    """Returns 410 Gone if query not provided and Redis key expired."""
    with patch("app.api.routes.articles.get_async_redis") as mock_redis:
        mock_redis.return_value = AsyncMock()
        mock_redis.return_value.get.return_value = None  # Query expired

        client = TestClient(app)
        response = client.post(
            f"/api/v1/articles/conversations/{conversation_id}/retry-openalex-search",
            json={},
            headers=user_headers,
        )

    assert response.status_code == 410
    assert "expired" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_retry_openalex_search_passes_message_id(conversation_id, user_headers):
    """Passes original_message_id to Celery task."""
    message_id = str(uuid.uuid4())

    with patch("app.api.routes.articles.get_async_redis") as mock_redis:
        mock_redis.return_value = AsyncMock()
        mock_redis.return_value.set.return_value = True
        mock_redis.return_value.get.return_value = "test query"

        with patch("app.api.routes.articles.run_openalex_search") as mock_task:
            client = TestClient(app)
            response = client.post(
                f"/api/v1/articles/conversations/{conversation_id}/retry-openalex-search",
                json={"query": "test query", "original_message_id": message_id},
                headers=user_headers,
            )

        # Verify task was called with message_id
        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args[1] if mock_task.delay.call_args[1] else {}
        assert call_kwargs.get("original_message_id") == message_id


@pytest.mark.asyncio
async def test_retry_openalex_search_generates_dedup_key(conversation_id, user_headers):
    """Generates dedup key from query hash."""
    with patch("app.api.routes.articles.get_async_redis") as mock_redis:
        mock_redis.return_value = AsyncMock()
        mock_redis.return_value.set.return_value = True

        with patch("app.api.routes.articles.run_openalex_search"):
            client = TestClient(app)
            response = client.post(
                f"/api/v1/articles/conversations/{conversation_id}/retry-openalex-search",
                json={"query": "test query"},
                headers=user_headers,
            )

        # Verify Redis SET was called for dedup lock
        mock_redis.return_value.set.assert_called_once()
        call_args = mock_redis.return_value.set.call_args
        dedup_key = call_args[0][0]
        assert "openalex_search_active" in dedup_key
        assert conversation_id in dedup_key
