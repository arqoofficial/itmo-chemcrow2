from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


def get_langfuse_handler():
    """Return a Langfuse CallbackHandler if configured, else None.

    Langfuse v4 reads credentials from environment variables:
    LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_HOST.
    This function syncs settings into the environment before constructing
    the handler, so the settings values take precedence over any existing
    env vars.
    """
    if not (settings.LANGFUSE_SECRET_KEY and settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_HOST):
        return None

    import os

    os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_HOST"] = settings.LANGFUSE_HOST

    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


def get_langfuse_config() -> dict:
    """Return a LangChain config dict with Langfuse callbacks, or {} if not configured.

    Usage:
        lf_config = get_langfuse_config()
        result = await agent.ainvoke(input, config=lf_config)
        # For sync endpoints, flush after invoke:
        for cb in lf_config.get("callbacks", []):
            if hasattr(cb, "flush"):
                cb.flush()
    """
    handler = get_langfuse_handler()
    if handler is None:
        return {}
    return {"callbacks": [handler]}


def check_langfuse_auth() -> bool:
    """Check Langfuse authentication at startup. Logs result. Returns True if auth OK."""
    if not (settings.LANGFUSE_SECRET_KEY and settings.LANGFUSE_PUBLIC_KEY):
        logger.warning(
            "Langfuse tracing disabled — set LANGFUSE_SECRET_KEY and "
            "LANGFUSE_PUBLIC_KEY to enable."
        )
        return False

    try:
        from langfuse import Langfuse

        client = Langfuse(
            secret_key=settings.LANGFUSE_SECRET_KEY,
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            host=settings.LANGFUSE_HOST,
        )
        client.auth_check()
        logger.info("Langfuse tracing enabled — host=%s", settings.LANGFUSE_HOST)
        return True
    except Exception:
        logger.exception("Langfuse auth check failed — tracing disabled")
        return False
