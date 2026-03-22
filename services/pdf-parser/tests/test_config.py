def test_settings_have_required_fields():
    from app.config import settings
    assert hasattr(settings, "REDIS_URL")
    assert hasattr(settings, "ARTICLES_MINIO_ENDPOINT")
    assert hasattr(settings, "ARTICLES_MINIO_ACCESS_KEY")
    assert hasattr(settings, "ARTICLES_MINIO_SECRET_KEY")
    assert hasattr(settings, "ARTICLES_MINIO_INPUT_BUCKET")
    assert hasattr(settings, "ARTICLES_MINIO_OUTPUT_BUCKET")
    assert hasattr(settings, "AI_AGENT_INGEST_URL")
    assert hasattr(settings, "OPENAI_API_KEY")


def test_settings_defaults():
    from app.config import settings
    assert settings.ARTICLES_MINIO_INPUT_BUCKET == "articles"
    assert settings.ARTICLES_MINIO_OUTPUT_BUCKET == "parsed-chunks"
    assert settings.REDIS_JOB_TTL == 86400
    assert settings.AI_AGENT_INGEST_URL == "http://ai-agent:8100"
