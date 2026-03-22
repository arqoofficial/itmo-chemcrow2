from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

VALID_JOB_ID = "abc12345-0000-0000-0000-000000000000"


def test_get_article_job_proxies_to_fetcher(client: TestClient, superuser_token_headers: dict):
    job_payload = {
        "job_id": VALID_JOB_ID,
        "status": "done",
        "url": f"http://localhost:9092/articles/{VALID_JOB_ID}.pdf?sig=x",
        "error": None,
    }
    with patch("app.api.routes.articles.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = job_payload
        mock_client_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        resp = client.get(f"/api/v1/articles/jobs/{VALID_JOB_ID}", headers=superuser_token_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == VALID_JOB_ID
    assert data["status"] == "done"
    assert f"{VALID_JOB_ID}.pdf" in data["url"]


def test_get_article_job_returns_404_when_not_found(client: TestClient, superuser_token_headers: dict):
    with patch("app.api.routes.articles.httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client_cls.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

        resp = client.get(f"/api/v1/articles/jobs/{VALID_JOB_ID}", headers=superuser_token_headers)

    assert resp.status_code == 404


def test_get_article_job_rejects_invalid_job_id(client: TestClient, superuser_token_headers: dict):
    """Non-UUID job_id values must be rejected with 422."""
    resp = client.get("/api/v1/articles/jobs/nonexistent", headers=superuser_token_headers)
    assert resp.status_code == 422


def test_get_article_job_requires_auth(client: TestClient):
    resp = client.get(f"/api/v1/articles/jobs/{VALID_JOB_ID}")
    assert resp.status_code == 401
