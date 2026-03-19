from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_core.messages import AIMessage
from sse_starlette import EventSourceResponse

from app.agent import convert_messages, get_agent
from app.config import settings
from app.schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AI Agent service starting (env=%s)", settings.ENVIRONMENT)
    yield
    logger.info("AI Agent service shutting down")


app = FastAPI(
    title="ChemCrow2 AI Agent",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-agent"}


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Synchronous chat: send messages, get a complete response.
    Used by Celery workers for non-streaming processing.
    """
    agent = get_agent(request.provider)
    langchain_messages = convert_messages([m.model_dump() for m in request.messages])
    result = await agent.ainvoke({"messages": langchain_messages})

    final_messages = result["messages"]
    last_ai = None
    for msg in reversed(final_messages):
        if isinstance(msg, AIMessage):
            last_ai = msg
            break

    if not last_ai:
        return ChatResponse(content="I could not generate a response.")

    tool_calls = None
    if last_ai.tool_calls:
        tool_calls = [
            {"name": tc["name"], "args": tc["args"]}
            for tc in last_ai.tool_calls
        ]

    return ChatResponse(
        content=last_ai.content or "",
        tool_calls=tool_calls,
    )


@app.post("/api/v1/chat/stream")
async def chat_stream(request: ChatRequest) -> EventSourceResponse:
    """
    Streaming chat via SSE. Streams intermediate steps (tool calls, partial responses).
    """
    agent = get_agent(request.provider)
    langchain_messages = convert_messages([m.model_dump() for m in request.messages])

    async def event_generator():
        try:
            async for event in agent.astream_events(
                {"messages": langchain_messages},
                version="v2",
            ):
                kind = event.get("event", "")

                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield {
                            "event": "token",
                            "data": json.dumps({"content": chunk.content}),
                        }

                elif kind == "on_tool_start":
                    yield {
                        "event": "tool_start",
                        "data": json.dumps({
                            "tool": event.get("name", ""),
                            "input": event.get("data", {}).get("input", {}),
                        }),
                    }

                elif kind == "on_tool_end":
                    yield {
                        "event": "tool_end",
                        "data": json.dumps({
                            "tool": event.get("name", ""),
                            "output": str(event.get("data", {}).get("output", "")),
                        }),
                    }

            yield {"event": "done", "data": json.dumps({"status": "completed"})}

        except Exception as exc:
            logger.exception("Streaming error")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc)}),
            }

    return EventSourceResponse(
        event_generator(),
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )
