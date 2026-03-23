import os
import pytest
from unittest.mock import patch


def test_config_loads_defaults():
    with patch.dict(os.environ, {
        "REDIS_URL": "redis://localhost:6379/0",
        "MINIO_ENDPOINT": "localhost:9092",
        "MINIO_ACCESS_KEY": "minioadmin",
        "MINIO_SECRET_KEY": "minioadmin",
        "MINIO_BUCKET": "articles",
        "MINIO_PUBLIC_ENDPOINT": "http://localhost:9092",
    }):
        from app.config import Settings
        s = Settings()
        assert s.redis_url == "redis://localhost:6379/0"
        assert s.minio_bucket == "articles"
