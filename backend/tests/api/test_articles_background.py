"""Tests for retry-s2-search and trigger-rag-continuation endpoints."""
import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from tests.utils.utils import get_superuser_token_headers

client = TestClient(app)
CONV_ID = str(uuid.uuid4())


def _auth_headers() -> dict[str, str]:
    return get_superuser_token_headers(client)


def test_retry_s2_search_returns_202_when_query_exists():
    headers = _auth_headers()
    with patch("app.api.routes.articles.run_s2_search") as mock_task, \
         patch("app.api.routes.articles.get_async_redis") as mock_redis:
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(return_value="aspirin synthesis")
        mock_redis.return_value = mock_r
        mock_task.delay.return_value = None

        resp = client.post(
            f"/api/v1/articles/conversations/{CONV_ID}/retry-s2-search",
            headers=headers,
        )
    assert resp.status_code == 202


def test_retry_s2_search_returns_410_when_query_expired():
    headers = _auth_headers()
    with patch("app.api.routes.articles.get_async_redis") as mock_redis:
        mock_r = AsyncMock()
        mock_r.get = AsyncMock(return_value=None)
        mock_redis.return_value = mock_r

        resp = client.post(
            f"/api/v1/articles/conversations/{CONV_ID}/retry-s2-search",
            headers=headers,
        )
    assert resp.status_code == 410
    assert "expired" in resp.json()["detail"].lower()


def test_trigger_rag_continuation_returns_202():
    headers = _auth_headers()
    with patch("app.api.routes.articles._trigger_rag_continuation") as mock_trigger:
        resp = client.post(
            f"/api/v1/articles/conversations/{CONV_ID}/trigger-rag-continuation",
            headers=headers,
        )
    assert resp.status_code == 202
    mock_trigger.assert_called_once_with(str(CONV_ID))
