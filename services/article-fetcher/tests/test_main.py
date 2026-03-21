import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_deps(mock_redis, mock_s3):
    """Patch Redis and StorageClient for all route tests."""
    with (
        patch("app.main.redis_client", mock_redis),
        patch("app.main.storage", mock_s3),
    ):
        yield mock_redis, mock_s3


@pytest.fixture
def client(mock_deps):
    from app.main import app
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_post_fetch_returns_job_id(client, mock_deps):
    mock_redis, _ = mock_deps
    mock_redis.set.return_value = True

    resp = client.post("/fetch", json={"doi": "10.1234/test"})
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "pending"
    mock_redis.set.assert_called_once()


def test_get_job_pending(client, mock_deps):
    mock_redis, _ = mock_deps
    job = {
        "job_id": "abc123",
        "doi": "10.1234/test",
        "status": "pending",
        "object_key": None,
        "error": None,
        "created_at": "2026-03-22T10:00:00Z",
    }
    mock_redis.get.return_value = json.dumps(job)

    resp = client.get("/jobs/abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["url"] is None


def test_get_job_done_returns_presigned_url(client, mock_deps):
    mock_redis, mock_s3 = mock_deps
    job = {
        "job_id": "abc123",
        "doi": "10.1234/test",
        "status": "done",
        "object_key": "abc123.pdf",
        "error": None,
        "created_at": "2026-03-22T10:00:00Z",
    }
    mock_redis.get.return_value = json.dumps(job)
    mock_s3.presign_url.return_value = "http://localhost:9092/articles/abc123.pdf?sig=x"

    resp = client.get("/jobs/abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert "abc123.pdf" in data["url"]


def test_get_job_failed(client, mock_deps):
    mock_redis, _ = mock_deps
    job = {
        "job_id": "abc123",
        "doi": "10.1234/test",
        "status": "failed",
        "object_key": None,
        "error": "Article not found",
        "created_at": "2026-03-22T10:00:00Z",
    }
    mock_redis.get.return_value = json.dumps(job)

    resp = client.get("/jobs/abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error"] == "Article not found"


def test_get_job_not_found(client, mock_deps):
    mock_redis, _ = mock_deps
    mock_redis.get.return_value = None

    resp = client.get("/jobs/doesnotexist")
    assert resp.status_code == 404
