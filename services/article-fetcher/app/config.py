from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = "redis://redis:6379/0"
    minio_endpoint: str = "articles-minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "articles"
    minio_public_endpoint: str = "http://localhost:9092"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
