"""
LangGraph ReAct agent for ChemCrow2.

The agent uses a tool-calling loop: LLM decides which tool to call,
the tool executes, and the result goes back to the LLM until it produces
a final answer (no more tool calls).
"""
from __future__ import annotations

import logging
import operator
from typing import Annotated, Any

from langchain.chat_models.base import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.config import settings
from app.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are ChemCrow2, an expert AI assistant for chemistry and cheminformatics.

You help researchers with:
- Molecular property prediction (logP, MW, TPSA, etc.)
- Retrosynthetic analysis (breaking down target molecules into precursors)
- Literature search (finding relevant papers and articles)
- General chemistry questions

When a user provides a SMILES string, analyze it and use the appropriate tools.
Always explain your reasoning and the results in a clear, scientific manner.
If a tool returns a stub response, acknowledge that the full service is not yet \
available and provide what information you can from your knowledge.
"""


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]


def _build_graph(llm: BaseChatModel) -> StateGraph:
    """Build the ReAct agent graph."""
    tools = ALL_TOOLS
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    def call_model(state: AgentState) -> dict[str, Any]:
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def call_tools(state: AgentState) -> dict[str, Any]:
        last_message = state["messages"][-1]
        results = []
        for tool_call in last_message.tool_calls:
            tool = tools_by_name[tool_call["name"]]
            observation = tool.invoke(tool_call["args"])
            results.append(
                ToolMessage(
                    content=str(observation),
                    tool_call_id=tool_call["id"],
                )
            )
        return {"messages": results}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("model", call_model)
    graph.add_node("tools", call_tools)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")

    return graph.compile()


_compiled_agents: dict[str, Any] = {}


def get_agent(provider: str | None = None) -> Any:
    """Get (or create) a compiled LangGraph agent for the given LLM provider."""
    from app.llm_providers import get_llm

    key = provider or settings.DEFAULT_LLM_PROVIDER
    if key not in _compiled_agents:
        llm = get_llm(key)
        _compiled_agents[key] = _build_graph(llm)
        logger.info("Built LangGraph agent with provider=%s", key)
    return _compiled_agents[key]


def convert_messages(raw_messages: list[dict]) -> list[AnyMessage]:
    """Convert raw message dicts (from API) to LangChain message objects."""
    result: list[AnyMessage] = []
    for msg in raw_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            result.append(SystemMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
        elif role == "tool":
            result.append(
                ToolMessage(
                    content=content,
                    tool_call_id=msg.get("tool_call_id", "unknown"),
                )
            )
        else:
            result.append(HumanMessage(content=content))
    return result
