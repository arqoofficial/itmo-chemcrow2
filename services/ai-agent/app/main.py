from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI
from langchain_core.messages import AIMessage
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from app.agent import convert_messages, get_agent
from app.config import settings
from app.guard import scan_input, scan_output
from app.hazard_checker import find_hazards
from app.schemas import ChatRequest, ChatResponse
from app.tracing import check_langfuse_auth, get_langfuse_config
from app.tools.rag import _CURRENT_CONV_ID, ingest_conversation_document

logger = logging.getLogger(__name__)


def _blocked_message(text: str) -> str:
    """Return a blocked-request message in the user's language."""
    if any("\u0400" <= ch <= "\u04ff" for ch in text):
        return "Этот запрос запрещен."
    return "This request is not allowed."


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

    _CURRENT_CONV_ID.set(request.conversation_id)
    langchain_messages = convert_messages([m.model_dump() for m in request.messages])
    user_text = ""
    for m in reversed(langchain_messages):
        if hasattr(m, "type") and m.type == "human":
            user_text = m.content or ""
            break
    _, failed_input = await asyncio.to_thread(scan_input, user_text)
    if failed_input:
        logger.warning("Input blocked by LLM Guard (sync): %s", failed_input)
        return ChatResponse(content=_blocked_message(user_text))

    agent = get_agent(request.provider)
    lf_config = get_langfuse_config()
    result = await agent.ainvoke({
        "messages": langchain_messages,
        "conversation_id": request.conversation_id,
    }, config=lf_config)
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
    _CURRENT_CONV_ID.set(request.conversation_id)
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
                    "data": json.dumps({"content": _blocked_message(user_text)}),
                }
                yield {"event": "done", "data": json.dumps({"status": "completed"})}
                return

            full_content: list[str] = []

            async for event in agent.astream_events(
                {
                    "messages": langchain_messages,
                    "conversation_id": request.conversation_id,
                },
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


@app.get("/config/article-fetcher-url")
def get_article_fetcher_url():
    return {"article_fetcher_url": settings.ARTICLE_FETCHER_URL}


class IngestRequest(BaseModel):
    conversation_id: str
    doc_key: str


@app.post("/rag/ingest", status_code=202)
async def rag_ingest(payload: IngestRequest, background_tasks: BackgroundTasks):
    """
    Called by pdf-parser after parsing completes.
    Downloads chunks from MinIO and builds an in-memory retriever for the conversation.
    """
    background_tasks.add_task(
        asyncio.to_thread,
        ingest_conversation_document,
        payload.conversation_id,
        payload.doc_key,
    )
    logger.info("rag/ingest queued for conv=%s doc=%s", payload.conversation_id, payload.doc_key)
    return {"status": "queued", "conversation_id": payload.conversation_id, "doc_key": payload.doc_key}
