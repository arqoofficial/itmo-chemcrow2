import logging
import time

from redis.asyncio import Redis

from app.schemas import JobState, JobStatus

log = logging.getLogger(__name__)

_KEY_PREFIX = "pdf_parser:job:"


class RedisJobStore:
    def __init__(self, redis: Redis, ttl: int = 86400):
        self._r = redis
        self._ttl = ttl

    def _key(self, job_id: str) -> str:
        return f"{_KEY_PREFIX}{job_id}"

    async def save(self, job: JobState) -> None:
        await self._r.set(self._key(job.job_id), job.model_dump_json(), ex=self._ttl)
        log.info("redis_store: saved job %s status=%s", job.job_id, job.status)

    async def get(self, job_id: str) -> JobState | None:
        raw = await self._r.get(self._key(job_id))
        if raw is None:
            return None
        return JobState.model_validate_json(raw)

    async def update(self, job_id: str, **fields) -> None:
        job = await self.get(job_id)
        if job is None:
            log.warning("redis_store: update on missing job %s", job_id)
            return
        updated = job.model_copy(update={**fields, "updated_at": time.time()})
        await self.save(updated)
