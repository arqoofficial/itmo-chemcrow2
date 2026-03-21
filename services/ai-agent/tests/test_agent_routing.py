from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app import agent


class _FakeCitationTool:
    name = "literature_citation_search"

    def __init__(self) -> None:
        self.called = False
        self.last_args: dict | None = None

    def invoke(self, args: dict) -> str:
        self.called = True
        self.last_args = args
        return (
            "Citation candidates from local literature corpus:\n"
            "1. doc_id=chapter_03; title=Глава 3. Выбор растворителя; "
            "source=app/data-rag/corpus_raw/chapter_03_vybor_rastvoritelya.md; "
            "score=0.9123; excerpt=Растворитель влияет на скорость..."
        )


class _DeterministicCitationLLM:
    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        # First model turn: decide to call local citation tool.
        if not any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "literature_citation_search",
                        "args": {"topic": "best solvent for SN2", "top_k": 3},
                        "id": "call_local_citations_1",
                        "type": "tool_call",
                    }
                ],
            )

        # Second model turn: consume tool output and produce final answer.
        tool_output = ""
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage):
                tool_output = str(msg.content)
                break
        return AIMessage(content=f"Using local citations:\n{tool_output}")


def test_agent_invokes_local_citation_tool_for_literature_request(monkeypatch):
    fake_tool = _FakeCitationTool()
    monkeypatch.setattr(agent, "ALL_TOOLS", [fake_tool])

    graph = agent._build_graph(_DeterministicCitationLLM())
    result = graph.invoke({"messages": [HumanMessage(content="Find literature citations for solvent choice in SN2")]})

    assert fake_tool.called is True
    assert fake_tool.last_args == {"topic": "best solvent for SN2", "top_k": 3}

    messages = result["messages"]
    final_ai = next(msg for msg in reversed(messages) if isinstance(msg, AIMessage))
    assert "Using local citations:" in final_ai.content
    assert "Citation candidates from local literature corpus:" in final_ai.content
