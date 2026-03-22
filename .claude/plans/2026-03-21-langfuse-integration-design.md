# Langfuse Integration Design

**Date:** 2026-03-21
**Branch:** add_langfuse
**Status:** Approved

## Overview

Integrate self-hosted Langfuse into ChemCrow2 to provide full agent traces for every chat request. Each request becomes one Langfuse trace with nested spans for all LLM calls and tool invocations, using the LangChain callback handler approach.

## Approach

**Option A — LangChain callback handler.** Inject `langfuse`'s `CallbackHandler` (from `langfuse.callback`) into every `agent.ainvoke()` and `agent.astream_events()` call via `config={"callbacks": [handler]}`. LangChain/LangGraph automatically propagates this through the full graph, producing nested spans for model calls and tool calls with no changes to `agent.py` or any tool files.

Tracing is **optional**: if `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_HOST` are not set, tracing is silently skipped and a warning is logged at startup.

## Section 1: Infrastructure

- Add two new services to `compose.yml` under the `langfuse` Docker Compose profile:
  - `langfuse-db` — dedicated Postgres instance for Langfuse (separate from the app `db` to avoid schema conflicts), with a named volume `langfuse-db-data` for persistence and a healthcheck
  - `langfuse-server` — official `langfuse/langfuse` image, exposed on port `3000`, with `depends_on: langfuse-db: condition: service_healthy` (following the existing pattern used by `backend` → `db`)
- Profile-gated startup: `docker compose --profile langfuse up`
- Default stack remains unchanged for devs who don't need tracing
- Add `langfuse-db-data` to the top-level `volumes:` section in `compose.yml`

## Section 2: SDK Integration

- Add `langfuse` (PyPI package, provides `langfuse.callback.CallbackHandler`) to `services/ai-agent/pyproject.toml` dependencies
- Create a new module `services/ai-agent/app/tracing.py` with a `get_langfuse_handler()` function that:
  - Returns a `langfuse.callback.CallbackHandler` instance if all three vars (`LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST`) are set
  - Returns `None` otherwise
- Add three optional settings to `config.py`:
  ```python
  LANGFUSE_SECRET_KEY: str = ""
  LANGFUSE_PUBLIC_KEY: str = ""
  LANGFUSE_HOST: str = "http://langfuse-server:3000"
  ```
- In `main.py`:
  - In the `lifespan` startup function:
    - If any Langfuse var is missing: `logging.warning("Langfuse tracing is disabled — set LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_HOST to enable.")`
    - If all vars are set: `logging.info("Langfuse tracing enabled — host=%s", settings.LANGFUSE_HOST)`
  - In `/api/v1/chat`: build a handler per request; pass `config={"callbacks": [handler]}` to `agent.ainvoke()`; call `handler.flush()` after `ainvoke()` returns to ensure trace data is sent before the response is returned
  - In `/api/v1/chat/stream`: build a handler per request; pass `config={"callbacks": [handler]}` as a keyword argument to `agent.astream_events()`

**Important:** The `CallbackHandler` must only be injected at invocation time (via `ainvoke` / `astream_events` config), never passed to `_build_graph()` or `graph.compile()`. The compiled graph is cached and reused across requests; passing a handler at build time would cause trace cross-contamination between requests.

## Section 3: Configuration & Environment

- Add to `.env.example`:
  ```bash
  # Langfuse tracing (optional — start with: docker compose --profile langfuse up)
  LANGFUSE_SECRET_KEY=
  LANGFUSE_PUBLIC_KEY=
  LANGFUSE_HOST=http://langfuse-server:3000

  # Langfuse server internals (required when running --profile langfuse)
  NEXTAUTH_SECRET=change-me-to-a-random-32-char-secret
  NEXTAUTH_URL=http://localhost:3000
  LANGFUSE_POSTGRES_PASSWORD=changeme
  ```
- `langfuse-server` reads `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `NEXTAUTH_SECRET`, `NEXTAUTH_URL`, and the DB connection vars from `.env`, so keys are defined once and shared between the server and the SDK

## Files Changed

| File | Change |
|------|--------|
| `compose.yml` | Add `langfuse-db` and `langfuse-server` services under `langfuse` profile; add `langfuse-db-data` named volume |
| `services/ai-agent/pyproject.toml` | Add `langfuse` dependency |
| `services/ai-agent/app/config.py` | Add `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST` settings |
| `services/ai-agent/app/tracing.py` | New file — `get_langfuse_handler()` helper |
| `services/ai-agent/app/main.py` | Add startup warning/info log; inject callback handler into both endpoints; flush after sync invoke |
| `.env.example` | Add Langfuse env vars with comments |

## Out of Scope

- Custom events (hazard checks, streaming done) — not requested
- OpenTelemetry bridge — not needed
- Manual SDK instrumentation — replaced by callback handler approach
