from fastapi import APIRouter

from app.api.routes import (
    articles,
    conversations,
    events,
    items,
    login,
    private,
    retrosynthesis,
    search,
    tasks,
    users,
    utils,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(tasks.router)
api_router.include_router(retrosynthesis.router)
api_router.include_router(conversations.router)
api_router.include_router(events.router)
api_router.include_router(articles.router)
api_router.include_router(search.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
