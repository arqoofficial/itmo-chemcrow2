from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load repo-root .env to pick up defaults (OPENAI provider settings, endpoint overrides).
_REPO_ENV = PROJECT_ROOT.parents[1] / ".env"  # ai-agent -> services -> repo root
if _REPO_ENV.exists():
    with _REPO_ENV.open("r", encoding="utf-8") as fp:
        for raw in fp:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] in ('\"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value

from app.config import settings  # noqa: E402


def _build_payload(question: str, provider: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": question}],
    }
    if provider:
        payload["provider"] = provider
    return payload


def _ask_mas(agent_url: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    timeout = httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds))
    with httpx.Client(timeout=timeout) as client:
        response = client.post(agent_url, json=payload)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("Unexpected response type from MAS endpoint")
        return body


def _extract_bind(agent_url: str) -> tuple[str, int] | None:
    parsed = urlparse(agent_url)
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return None
    return host, port


def _is_local_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "0.0.0.0"}


def _health_url_from_agent_url(agent_url: str) -> str:
    parsed = urlparse(agent_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8100
    return f"{parsed.scheme or 'http'}://{host}:{port}/health"


def _wait_for_health(health_url: str, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=httpx.Timeout(2.0, connect=2.0)) as client:
                resp = client.get(health_url)
                if resp.status_code == 200:
                    return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def _auto_start_local_agent(agent_url: str, startup_wait_seconds: float) -> bool:
    bind = _extract_bind(agent_url)
    if not bind:
        return False
    host, port = bind
    if not _is_local_host(host):
        return False

    health_url = _health_url_from_agent_url(agent_url)
    if _wait_for_health(health_url, timeout_seconds=1.0):
        return True

    # Run through uv so server starts in the ai-agent project environment
    # (pyproject.toml dependencies, including tool stack packages).
    cmd = [
        "uv",
        "run",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]

    popen_kwargs: dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "start_new_session": True,
    }

    # Windows: detach from current console and avoid Ctrl+C propagation.
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    try:
        subprocess.Popen(cmd, **popen_kwargs)
    except Exception:
        return False

    return _wait_for_health(health_url, timeout_seconds=startup_wait_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ask MAS directly via ai-agent API (no UI).",
    )
    parser.add_argument("question", nargs="?", help="Question for MAS")
    parser.add_argument(
        "--agent-url",
        type=str,
        default=os.environ.get("AI_AGENT_CHAT_URL", "http://127.0.0.1:8100/api/v1/chat"),
        help="MAS chat endpoint URL",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="LLM provider override for MAS (openai | anthropic)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="HTTP timeout seconds",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON response instead of plain answer text",
    )
    parser.add_argument(
        "--no-auto-start-agent",
        action="store_true",
        help="Do not auto-start local ai-agent when connection is refused",
    )
    parser.add_argument(
        "--startup-wait-seconds",
        type=float,
        default=25.0,
        help="How long to wait for auto-started agent health endpoint",
    )
    args = parser.parse_args()

    question = (args.question or "").strip()
    if not question:
        question = input("Enter your question for MAS: ").strip()
    if not question:
        raise SystemExit("Question must be a non-empty string.")

    payload = _build_payload(question=question, provider=args.provider)

    if not args.no_auto_start_agent:
        _auto_start_local_agent(
            agent_url=args.agent_url,
            startup_wait_seconds=max(args.startup_wait_seconds, 1.0),
        )

    try:
        body = _ask_mas(
            agent_url=args.agent_url,
            payload=payload,
            timeout_seconds=max(args.timeout_seconds, 1.0),
        )
    except httpx.HTTPStatusError as exc:
        details = exc.response.text[:1000] if exc.response is not None else str(exc)
        raise SystemExit(f"MAS request failed with HTTP {exc.response.status_code}: {details}") from exc
    except httpx.HTTPError as exc:
        hint = ""
        bind = _extract_bind(args.agent_url)
        if bind and _is_local_host(bind[0]):
            hint = (
                "\nHint: local ai-agent is unreachable. Auto-start is enabled by default; "
                "if startup failed, run manually:\n"
                "  uv run uvicorn app.main:app --host 127.0.0.1 --port 8100"
            )
        raise SystemExit(f"MAS request failed: {exc}{hint}") from exc

    if args.json:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return

    content = str(body.get("content", "") or "")
    print(content)

    tool_calls = body.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        print("\n[tool_calls]")
        for idx, tc in enumerate(tool_calls, start=1):
            name = tc.get("name") if isinstance(tc, dict) else None
            args_preview = tc.get("args") if isinstance(tc, dict) else None
            print(f"{idx}. name={name} args={args_preview}")


if __name__ == "__main__":
    main()
