import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Message,
    TaskJob,
    TaskJobCreate,
    TaskJobPublic,
    TaskJobsPublic,
)
from app.worker.tasks import dispatch_task, revoke_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/", response_model=TaskJobPublic, status_code=201)
def create_task(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    task_in: TaskJobCreate,
) -> Any:
    """
    Create a new async task.

    Saves TaskJob to DB and dispatches the corresponding Celery task.
    Subscribe to SSE at /api/v1/events/tasks/{id} for real-time updates.
    """
    task = TaskJob.model_validate(task_in, update={"user_id": current_user.id})
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


@router.get("/", response_model=TaskJobsPublic)
def list_tasks(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = Query(default=50, le=200),
    status: str | None = Query(default=None, max_length=20),
    task_type: str | None = Query(default=None, max_length=50),
) -> Any:
    """
    List tasks for the current user (superuser sees all).

    Optional filters: status, task_type.
    """
    base = select(TaskJob)
    count_base = select(func.count()).select_from(TaskJob)

    if not current_user.is_superuser:
        base = base.where(TaskJob.user_id == current_user.id)
        count_base = count_base.where(TaskJob.user_id == current_user.id)

    if status:
        base = base.where(TaskJob.status == status)
        count_base = count_base.where(TaskJob.status == status)

    if task_type:
        base = base.where(TaskJob.task_type == task_type)
        count_base = count_base.where(TaskJob.task_type == task_type)

    count = session.exec(count_base).one()
    tasks = session.exec(
        base.order_by(col(TaskJob.created_at).desc()).offset(skip).limit(limit)
    ).all()

    return TaskJobsPublic(data=tasks, count=count)


@router.get("/{task_id}", response_model=TaskJobPublic)
def get_task(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> Any:
    """
    Get task status and result by ID.
    """
    task = session.get(TaskJob, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not current_user.is_superuser and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return task


@router.delete("/{task_id}")
def cancel_task(
    session: SessionDep,
    current_user: CurrentUser,
    task_id: uuid.UUID,
) -> Message:
    """
    Cancel a running/pending task (revokes Celery task) or delete a completed one.
    """
    task = session.get(TaskJob, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not current_user.is_superuser and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    if task.status in ("pending", "queued", "running"):
        revoke_task(task)
        task.status = "cancelled"
        session.add(task)
        session.commit()
        return Message(message="Task cancelled")

    session.delete(task)
    session.commit()
    return Message(message="Task deleted")
