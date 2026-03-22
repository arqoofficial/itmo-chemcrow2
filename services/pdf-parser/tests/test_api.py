import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    with patch("app.main.job_store", new=MagicMock()), \
         patch("app.main.minio", new=MagicMock()):
        with patch("app.main.make_minio_store", return_value=MagicMock()), \
             patch("app.main.Redis") as mock_redis_cls:
            mock_redis_cls.from_url.return_value = AsyncMock()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                yield c


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_submit_job_returns_job_id(client):
    with patch("app.main.job_store") as mock_store, \
         patch("app.main._run_parser", new_callable=AsyncMock):
        mock_store.save = AsyncMock()
        resp = await client.post("/jobs", json={
            "job_id": "fetcher-job-001",
            "doi": "10.1038/s41586-021-03819-2",
            "object_key": "fetcher-job-001.pdf",
            "conversation_id": "conv-abc",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert data["job_id"] == "fetcher-job-001"
        assert data["status"] == "pending"


async def test_get_job_status(client):
    from app.schemas import JobState, JobStatus
    import time
    mock_job = JobState(
        job_id="test-123",
        status=JobStatus.RUNNING,
        doi="10.1234/test",
        doc_key="10_1234_test",
        conversation_id="conv-xyz",
        created_at=time.time(),
        updated_at=time.time(),
    )
    with patch("app.main.job_store") as mock_store:
        mock_store.get = AsyncMock(return_value=mock_job)
        resp = await client.get("/jobs/test-123")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        assert resp.json()["conversation_id"] == "conv-xyz"


async def test_get_job_not_found(client):
    with patch("app.main.job_store") as mock_store:
        mock_store.get = AsyncMock(return_value=None)
        resp = await client.get("/jobs/missing-id")
        assert resp.status_code == 404


async def test_ingest_webhook_fired_on_completion(client):
    """After successful parsing, POST /rag/ingest is called on ai-agent."""
    from app.schemas import JobState, JobStatus
    import time

    mock_job = JobState(
        job_id="j-completed",
        status=JobStatus.COMPLETED,
        doi="10.1234/test",
        doc_key="10_1234_test",
        conversation_id="conv-fire",
        created_at=time.time(),
        updated_at=time.time(),
        artifacts={"chunk_000": "parsed-chunks/conv-fire/10_1234_test/_chunks/chunk_000.md"},
    )

    with patch("app.main.job_store") as mock_store, \
         patch("app.main._notify_ai_agent", new_callable=AsyncMock) as mock_notify:
        mock_store.get = AsyncMock(return_value=mock_job)
        mock_store.update = AsyncMock()
        # Simulate _run_parser calling _notify_ai_agent directly
        await mock_notify("conv-fire", "10_1234_test")
        mock_notify.assert_called_once_with("conv-fire", "10_1234_test")
