from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_core.messages import AIMessage
from sse_starlette import EventSourceResponse

from app.agent import convert_messages, get_agent
from app.config import settings
from app.guard import scan_input, scan_output
from app.hazard_checker import find_hazards
from app.schemas import ChatRequest, ChatResponse
from app.tracing import check_langfuse_auth, get_langfuse_config

logger = logging.getLogger(__name__)


async def _warmup_guard():
    import asyncio
    try:
        await asyncio.to_thread(scan_input, "warmup")
        await asyncio.to_thread(scan_output, "warmup", "warmup")
        logger.info("LLM Guard scanners warmed up")
    except Exception:
        logger.exception("LLM Guard warmup failed — scans will be skipped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    logger.info("AI Agent service starting (env=%s)", settings.ENVIRONMENT)
    asyncio.create_task(_warmup_guard())
    check_langfuse_auth()
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
    import asyncio

    langchain_messages = convert_messages([m.model_dump() for m in request.messages])
    user_text = ""
    for m in reversed(langchain_messages):
        if hasattr(m, "type") and m.type == "human":
            user_text = m.content or ""
            break
    _, failed_input = await asyncio.to_thread(scan_input, user_text)
    if failed_input:
        logger.warning("Input blocked by LLM Guard (sync): %s", failed_input)
        return ChatResponse(content="Недопустимый запрос.")

    agent = get_agent(request.provider)
    lf_config = get_langfuse_config()
    result = await agent.ainvoke({"messages": langchain_messages}, config=lf_config)
    for cb in lf_config.get("callbacks", []):
        if hasattr(cb, "flush"):
            cb.flush()

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

    lf_config = get_langfuse_config()

    async def event_generator():
        try:
            # ── Input scan ────────────────────────────────────────────────
            import asyncio
            user_text = ""
            for m in reversed(langchain_messages):
                if hasattr(m, "type") and m.type == "human":
                    user_text = m.content or ""
                    break
            _, failed_input = await asyncio.to_thread(scan_input, user_text)
            if failed_input:
                logger.warning("Input blocked by LLM Guard: %s", failed_input)
                yield {
                    "event": "token",
                    "data": json.dumps({"content": "Недопустимый запрос."}),
                }
                yield {"event": "done", "data": json.dumps({"status": "completed"})}
                return

            full_content: list[str] = []

            async for event in agent.astream_events(
                {"messages": langchain_messages},
                config=lf_config,
                version="v2",
            ):
                kind = event.get("event", "")

                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        full_content.append(chunk.content)
                        yield {
                            "event": "token",
                            "data": json.dumps({"content": chunk.content}),
                        }

                elif kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    tool_input = event.get("data", {}).get("input", {})
                    logger.info("TOOL CALL: %s | input: %s", tool_name, tool_input)
                    yield {
                        "event": "tool_start",
                        "data": json.dumps({
                            "tool": tool_name,
                            "input": tool_input,
                        }),
                    }

                elif kind == "on_tool_end":
                    tool_name = event.get("name", "")
                    tool_output = str(event.get("data", {}).get("output", ""))
                    tool_input = event.get("data", {}).get("input", {})
                    smiles = tool_input.get("smiles", "")
                    if tool_name == "predict_nmr":
                        try:
                            from app.tools.nmr import pop_pending_image
                            image_uri = pop_pending_image(smiles)
                            if image_uri:
                                tool_output = tool_output + f"\n\n![¹H NMR spectrum]({image_uri})"
                        except Exception:
                            pass
                    elif tool_name == "draw_molecule_rdkit":
                        try:
                            from app.tools.molecule_draw_rdkit import pop_pending_image
                            image_uri = pop_pending_image(smiles)
                            if image_uri:
                                tool_output = f"![Structure]({image_uri})"
                        except Exception:
                            pass
                    logger.info("TOOL END: %s | output: %.200s", tool_name, tool_output)
                    yield {
                        "event": "tool_end",
                        "data": json.dumps({
                            "tool": tool_name,
                            "output": tool_output,
                        }),
                    }

            # ── Output scan ───────────────────────────────────────────────
            assembled = "".join(full_content)
            assembled, failed_output = await asyncio.to_thread(scan_output, user_text, assembled)
            if failed_output:
                logger.warning("Output flagged by LLM Guard: %s", failed_output)

            # Check assembled response for hazardous chemicals
            hazards = find_hazards(assembled)
            if hazards:
                yield {
                    "event": "hazards",
                    "data": json.dumps({"chemicals": hazards}),
                }

            yield {"event": "done", "data": json.dumps({"status": "completed"})}

        except Exception as exc:
            logger.exception("Streaming error")
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc)}),
            }
        finally:
            for cb in lf_config.get("callbacks", []):
                if hasattr(cb, "flush"):
                    cb.flush()

    return EventSourceResponse(
        event_generator(),
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )
