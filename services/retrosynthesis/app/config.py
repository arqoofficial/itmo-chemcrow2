from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )

    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    AZF_CONFIG_PATH: str = "data/aizynthfinder/config.yml"

    HOST: str = "0.0.0.0"
    PORT: int = 8052

    MAX_TIME_LIMIT: int = 120
    MAX_ITERATIONS: int = 100
    MAX_TRANSFORMS: int = 24


settings = Settings()  # type: ignore
