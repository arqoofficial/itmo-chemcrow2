"""Retrosynthesis microservice — FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from app.config import settings
from app.engines.aizynthfinder_engine import AiZynthFinderEngine
from app.engines.base import RetrosynthesisEngine
from app.schemas import MultiStepRequest, MultiStepResult, ResourcesResponse

logger = logging.getLogger(__name__)

ENGINES: dict[str, RetrosynthesisEngine] = {}


def _register_engines() -> None:
    config_path = Path(settings.AZF_CONFIG_PATH)
    if config_path.exists():
        ENGINES["aizynthfinder"] = AiZynthFinderEngine(config_path)
        logger.info("Registered engine: aizynthfinder")
    else:
        logger.warning("AZF config not found at %s — engine skipped", config_path)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    _register_engines()
    yield


app = FastAPI(
    title="Retrosynthesis Service",
    version="0.1.0",
    lifespan=lifespan,
)


def _get_engine(name: str = "aizynthfinder") -> RetrosynthesisEngine:
    engine = ENGINES.get(name)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail=f"Engine '{name}' is not available. Loaded: {list(ENGINES)}",
        )
    return engine


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@app.post("/api/v1/run", response_model=MultiStepResult)
def run_multi_step(request: MultiStepRequest) -> dict[str, Any]:
    """Run multi-step (tree-search) retrosynthesis.

    Called by Celery workers and AI agent. Synchronous — blocks until done.
    """
    engine = _get_engine()
    return engine.run_multi_step(
        request.smiles,
        max_transforms=request.max_transforms,
        time_limit=request.time_limit,
        iterations=request.iterations,
        expansion_model=request.expansion_model,
        stock=request.stock,
    )


@app.get("/api/v1/resources", response_model=ResourcesResponse)
def get_resources() -> dict[str, list[str]]:
    """Return available expansion models and stocks."""
    engine = _get_engine()
    return engine.get_resources()


@app.get("/health")
def health() -> dict[str, str]:
    status = "ok" if ENGINES else "no_engines"
    return {"status": status, "engines": list(ENGINES)}
