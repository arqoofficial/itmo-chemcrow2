"""Retrosynthesis endpoints — user-facing async API.

POST /multi-step → creates a TaskJob, dispatches Celery task, returns task info.
GET  /resources   → proxies available models/stocks from the microservice.

Track progress via GET /tasks/{id} or SSE /events/tasks/{id}.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import TaskJob, TaskJobPublic
from app.worker.tasks import dispatch_task

router = APIRouter(prefix="/retrosynthesis", tags=["retrosynthesis"])


# ------------------------------------------------------------------
# Request / response schemas
# ------------------------------------------------------------------


class MultiStepRequest(BaseModel):
    """Parameters for multi-step retrosynthesis (tree search)."""

    smiles: str = Field(..., min_length=1, description="Target molecule SMILES")
    max_transforms: int = Field(default=12, ge=1, le=24)
    time_limit: int = Field(default=10, ge=1, le=120, description="seconds")
    iterations: int = Field(default=100, ge=1, le=100)
    expansion_model: str = Field(default="uspto")
    stock: str = Field(default="zinc")


class ResourcesResponse(BaseModel):
    expansion_models: list[str]
    stocks: list[str]


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.post("/multi-step", response_model=TaskJobPublic, status_code=201)
def run_multi_step(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: MultiStepRequest,
) -> Any:
    """Launch multi-step retrosynthesis as a background task.

    Returns the created TaskJob. Subscribe to SSE at
    ``/api/v1/events/tasks/{id}`` for real-time progress.
    """
    task = TaskJob(
        user_id=current_user.id,
        task_type="retrosynthesis_multi_step",
        source="manual",
        input_data=body.model_dump_json(),
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    celery_task_id = dispatch_task(task)

    task.celery_task_id = celery_task_id
    task.status = "queued"
    session.add(task)
    session.commit()
    session.refresh(task)

    return task


@router.get("/resources", response_model=ResourcesResponse)
async def get_resources(current_user: CurrentUser) -> Any:  # noqa: ARG001
    """Return available retrosynthesis models and stocks."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{settings.RETROSYNTHESIS_URL}/api/v1/resources"
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Retrosynthesis service unavailable: {exc}",
        )
