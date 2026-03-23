from enum import Enum
from pydantic import BaseModel, Field


def _doi_to_doc_key(doi: str) -> str:
    """Convert a DOI to a filesystem-safe doc key."""
    return doi.replace("/", "_").replace(".", "_")


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestWebhookPayload(BaseModel):
    """Payload sent by article-fetcher when a PDF download completes."""
    job_id: str
    doi: str
    object_key: str       # MinIO key of the PDF in the 'articles' bucket
    conversation_id: str

    @property
    def doc_key(self) -> str:
        return _doi_to_doc_key(self.doi)


class JobState(BaseModel):
    job_id: str
    status: JobStatus
    doi: str
    doc_key: str
    conversation_id: str
    error: str | None = None
    # Maps artifact name to MinIO object key
    artifacts: dict[str, str] = Field(default_factory=dict)
    created_at: float | None = None
    updated_at: float | None = None


class JobSubmitResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    doi: str
    doc_key: str
    conversation_id: str
    error: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_job(cls, job: "JobState") -> "JobStatusResponse":
        return cls.model_validate(job.model_dump(exclude={"created_at", "updated_at"}))
