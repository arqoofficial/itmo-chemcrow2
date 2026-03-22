import time
import pytest
import fakeredis.aioredis
from app.redis_store import RedisJobStore
from app.schemas import JobState, JobStatus


@pytest.fixture
async def store():
    fake = fakeredis.aioredis.FakeRedis()
    yield RedisJobStore(redis=fake, ttl=60)
    await fake.aclose()


async def test_create_and_get_job(store):
    job = JobState(
        job_id="j1", status=JobStatus.PENDING,
        doi="10.1234/test", doc_key="10_1234_test",
        conversation_id="conv-1",
        created_at=time.time(), updated_at=time.time(),
    )
    await store.save(job)
    fetched = await store.get("j1")
    assert fetched is not None
    assert fetched.status == JobStatus.PENDING
    assert fetched.conversation_id == "conv-1"


async def test_get_missing_job_returns_none(store):
    result = await store.get("nonexistent")
    assert result is None


async def test_update_status(store):
    job = JobState(
        job_id="j2", status=JobStatus.PENDING,
        doi="10.1234/test", doc_key="10_1234_test",
        conversation_id="conv-2",
        created_at=time.time(), updated_at=time.time(),
    )
    await store.save(job)
    await store.update("j2", status=JobStatus.COMPLETED, artifacts={"chunk_000": "parsed-chunks/conv-2/10_1234_test/_chunks/chunk_000.md"})
    fetched = await store.get("j2")
    assert fetched.status == JobStatus.COMPLETED
    assert "chunk_000" in fetched.artifacts


async def test_update_failure(store):
    job = JobState(
        job_id="j3", status=JobStatus.RUNNING,
        doi="10.1234/test", doc_key="10_1234_test",
        conversation_id="conv-3",
        created_at=time.time(), updated_at=time.time(),
    )
    await store.save(job)
    await store.update("j3", status=JobStatus.FAILED, error="Docling crashed")
    fetched = await store.get("j3")
    assert fetched.status == JobStatus.FAILED
    assert fetched.error == "Docling crashed"
