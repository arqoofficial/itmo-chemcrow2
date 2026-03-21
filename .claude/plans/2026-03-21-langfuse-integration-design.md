# Langfuse Integration Design

**Date:** 2026-03-21
**Branch:** add_langfuse
**Status:** Approved

## Overview

Integrate self-hosted Langfuse into ChemCrow2 to provide full agent traces for every chat request. Each request becomes one Langfuse trace with nested spans for all LLM calls and tool invocations, using the LangChain callback handler approach.

## Approach

**Option A — LangChain callback handler.** Inject `langfuse-langchain`'s `CallbackHandler` into every `agent.ainvoke()` and `agent.astream_events()` call via `config={"callbacks": [handler]}`. LangChain/LangGraph automatically propagates this through the full graph, producing nested spans for model calls and tool calls with no changes to `agent.py` or any tool files.

Tracing is **optional**: if `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_HOST` are not set, tracing is silently skipped and a warning is logged at startup.

## Section 1: Infrastructure

- Add two new services to `compose.yml` under the `langfuse` Docker Compose profile:
  - `langfuse-server` — official `langfuse/langfuse` image, exposed on port `3000`
  - `langfuse-db` — dedicated Postgres instance for Langfuse (separate from the app `db`)
- Profile-gated startup: `docker compose --profile langfuse up`
- Default stack remains unchanged for devs who don't need tracing

## Section 2: SDK Integration

- Add `langfuse-langchain` to `services/ai-agent/pyproject.toml` dependencies
- Add a `get_langfuse_handler()` helper that returns a `CallbackHandler` if all three Langfuse env vars are set, otherwise `None`
- Add three optional settings to `config.py`:
  ```python
  LANGFUSE_SECRET_KEY: str = ""
  LANGFUSE_PUBLIC_KEY: str = ""
  LANGFUSE_HOST: str = "http://langfuse-server:3000"
  ```
- In `main.py`, both `/api/v1/chat` and `/api/v1/chat/stream` build a handler per request and pass it via `config={"callbacks": [handler]}`
- In the `lifespan` startup function:
  - If Langfuse vars are missing: `logging.warning("Langfuse tracing is disabled — set LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and LANGFUSE_HOST to enable.")`
  - If all vars are set: `logging.info("Langfuse tracing enabled — host=%s", settings.LANGFUSE_HOST)`

## Section 3: Configuration & Environment

- Add to `.env` (and `.env.example` if present):
  ```bash
  # Langfuse tracing (optional — start with --profile langfuse)
  LANGFUSE_SECRET_KEY=
  LANGFUSE_PUBLIC_KEY=
  LANGFUSE_HOST=http://langfuse-server:3000
  # Langfuse internal DB
  LANGFUSE_POSTGRES_PASSWORD=changeme
  ```
- `langfuse-server` reads `LANGFUSE_SECRET_KEY` and `LANGFUSE_PUBLIC_KEY` from the same `.env`, so keys are defined once and shared

## Files Changed

| File | Change |
|------|--------|
| `compose.yml` | Add `langfuse-server` and `langfuse-db` services under `langfuse` profile |
| `services/ai-agent/pyproject.toml` | Add `langfuse-langchain` dependency |
| `services/ai-agent/app/config.py` | Add `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST` settings |
| `services/ai-agent/app/main.py` | Add startup warning/info log; inject callback handler into both endpoints |
| `.env` | Add Langfuse env vars (commented out) |

## Out of Scope

- Custom events (hazard checks, streaming done) — not requested
- OpenTelemetry bridge — not needed
- Manual SDK instrumentation — replaced by callback handler approach
