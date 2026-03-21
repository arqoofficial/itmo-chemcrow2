from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# --- get_langfuse_handler ---

def test_get_langfuse_handler_returns_none_when_secret_key_missing(monkeypatch):
    """Returns None when LANGFUSE_SECRET_KEY is empty."""
    monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "")
    monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setattr("app.config.settings.LANGFUSE_HOST", "http://localhost:3000")

    from app.tracing import get_langfuse_handler
    assert get_langfuse_handler() is None


def test_get_langfuse_handler_returns_none_when_public_key_missing(monkeypatch):
    """Returns None when LANGFUSE_PUBLIC_KEY is empty."""
    monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr("app.config.settings.LANGFUSE_HOST", "http://localhost:3000")

    from app.tracing import get_langfuse_handler
    assert get_langfuse_handler() is None


def test_get_langfuse_handler_returns_handler_when_configured(monkeypatch):
    """Returns a CallbackHandler when all three vars are set."""
    monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setattr("app.config.settings.LANGFUSE_HOST", "http://localhost:3000")

    from langfuse.langchain import CallbackHandler

    with patch("langfuse.langchain.CallbackHandler.__init__", return_value=None):
        from app.tracing import get_langfuse_handler
        handler = get_langfuse_handler()
        assert isinstance(handler, CallbackHandler)


# --- get_langfuse_config ---

def test_get_langfuse_config_returns_empty_when_unconfigured(monkeypatch):
    """Returns {} when Langfuse is not configured."""
    monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "")
    monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr("app.config.settings.LANGFUSE_HOST", "http://localhost:3000")

    from app.tracing import get_langfuse_config
    assert get_langfuse_config() == {}


def test_get_langfuse_config_returns_callbacks_when_configured(monkeypatch):
    """Returns {"callbacks": [handler]} when configured."""
    monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setattr("app.config.settings.LANGFUSE_HOST", "http://localhost:3000")

    with patch("langfuse.langchain.CallbackHandler.__init__", return_value=None):
        from app.tracing import get_langfuse_config
        config = get_langfuse_config()
        assert "callbacks" in config
        assert len(config["callbacks"]) == 1


# --- check_langfuse_auth ---

def test_check_langfuse_auth_returns_false_when_unconfigured(monkeypatch):
    """Returns False and logs warning when keys not set."""
    monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "")
    monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "")

    from app.tracing import check_langfuse_auth
    assert check_langfuse_auth() is False


def test_check_langfuse_auth_returns_false_on_exception(monkeypatch):
    """Returns False and logs exception when auth_check() raises."""
    monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "sk-bad")
    monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "pk-bad")
    monkeypatch.setattr("app.config.settings.LANGFUSE_HOST", "http://localhost:3000")

    mock_client = MagicMock()
    mock_client.auth_check.side_effect = Exception("unauthorized")

    with patch("langfuse.Langfuse", return_value=mock_client):
        from app.tracing import check_langfuse_auth
        assert check_langfuse_auth() is False


def test_check_langfuse_auth_returns_true_on_success(monkeypatch):
    """Returns True when auth_check() succeeds."""
    monkeypatch.setattr("app.config.settings.LANGFUSE_SECRET_KEY", "sk-ok")
    monkeypatch.setattr("app.config.settings.LANGFUSE_PUBLIC_KEY", "pk-ok")
    monkeypatch.setattr("app.config.settings.LANGFUSE_HOST", "http://localhost:3000")

    mock_client = MagicMock()
    mock_client.auth_check.return_value = None  # success

    with patch("langfuse.Langfuse", return_value=mock_client):
        from app.tracing import check_langfuse_auth
        assert check_langfuse_auth() is True
