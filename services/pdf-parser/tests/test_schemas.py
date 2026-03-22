from app.schemas import JobStatus, JobState, IngestWebhookPayload


def test_job_status_values():
    assert JobStatus.PENDING == "pending"
    assert JobStatus.RUNNING == "running"
    assert JobStatus.COMPLETED == "completed"
    assert JobStatus.FAILED == "failed"


def test_job_state_serialization():
    job = JobState(
        job_id="abc123",
        status=JobStatus.PENDING,
        doi="10.1234/test",
        doc_key="10_1234_test",
        conversation_id="conv-999",
    )
    data = job.model_dump()
    assert data["job_id"] == "abc123"
    assert data["status"] == "pending"
    assert data["error"] is None
    assert data["artifacts"] == {}
    assert data["conversation_id"] == "conv-999"
    assert data["doc_key"] == "10_1234_test"


def test_ingest_webhook_payload():
    payload = IngestWebhookPayload(
        job_id="j1",
        doi="10.1038/s41586-021-03819-2",
        object_key="j1.pdf",
        conversation_id="conv-001",
    )
    assert payload.doc_key == "10_1038_s41586-021-03819-2"
