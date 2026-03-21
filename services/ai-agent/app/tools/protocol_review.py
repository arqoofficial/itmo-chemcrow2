"""Protocol review tool using a parallel LangGraph review pipeline."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, ValidationError
from typing_extensions import TypedDict


# ============================================================
# Pydantic structured output
# ============================================================

class SectionReview(BaseModel):
    evaluation: str = Field(...)
    feasibility: str = Field(...)
    risks_or_gaps: List[str] = Field(default_factory=list)
    improvement_ideas: List[str] = Field(default_factory=list)


class SafetyReview(BaseModel):
    hazards: List[str] = Field(default_factory=list)
    ppe: List[str] = Field(default_factory=list)
    engineering_controls: List[str] = Field(default_factory=list)
    critical_notes: List[str] = Field(default_factory=list)


class FinalStructuredOutput(BaseModel):
    precursor_review: SectionReview
    steps_review: SectionReview
    catalyst_review: SectionReview
    reaction_conditions_review: SectionReview
    laboratory_safety_review: SafetyReview
    overall_summary: str
    priority_recommendations: List[str] = Field(default_factory=list)


# ============================================================
# LangGraph state
# ============================================================

class GraphState(TypedDict, total=False):
    protocol_text: str
    precursor_answer: str
    steps_answer: str
    catalyst_answer: str
    conditions_answer: str
    safety_answer: str
    aggregated_answer: str
    final_text: str
    structured_output: Dict[str, Any]


# ============================================================
# Prompts
# ============================================================

SYSTEM_ANALYSIS = """You are a senior chemist reviewing a laboratory protocol.
Write concise, technical, mechanistic analysis.
Be critical but constructive.
Focus on internal consistency, feasibility, completeness, missing details, and practical laboratory execution.
Do not output JSON unless explicitly asked.
"""

SYSTEM_AGGREGATION = """You are an expert scientific editor.
Merge multiple chemistry review branches into one coherent consolidated report.
Remove repetition, preserve technical meaning, and keep the tone practical and critical.
"""

SYSTEM_FINAL = """You are a senior chemistry reviewer producing a final expert report.
Write clearly, use sections, and end with priority recommendations.
"""

SYSTEM_JSON = """You convert scientific review text into strict JSON.
Return only valid JSON.
"""


def _make_analysis_prompt(protocol_text: str, focus: str) -> str:
    return f"""Review the following chemistry protocol.

Focus area: {focus}

For this focus area, provide:
1. Short description of what is present in the protocol
2. Evaluation of quality/completeness
3. Feasibility assessment
4. Missing information, ambiguities, or potential practical problems
5. Concrete approaches to improvement

Protocol:
\"\"\"{protocol_text}\"\"\"
""".strip()


def _make_safety_prompt(protocol_text: str) -> str:
    return f"""Review the following chemistry protocol strictly from the perspective of laboratory safety.

Provide:
1. Main hazards
2. Required PPE
3. Engineering controls / ventilation / gas-handling precautions
4. Missing safety instructions
5. Recommendations to improve safety documentation

Protocol:
\"\"\"{protocol_text}\"\"\"
""".strip()


def _make_aggregate_prompt(state: GraphState) -> str:
    return f"""Combine five expert reviews of the same laboratory protocol into one coherent consolidated review.
Remove repetition. Keep sections: Precursors, Steps, Catalyst, Reaction conditions, Safety, Priority improvements.

[PRECURSORS] {state.get("precursor_answer", "")}
[STEPS] {state.get("steps_answer", "")}
[CATALYST] {state.get("catalyst_answer", "")}
[REACTION CONDITIONS] {state.get("conditions_answer", "")}
[LAB SAFETY] {state.get("safety_answer", "")}
""".strip()


def _make_structured_json_prompt(final_text: str) -> str:
    schema = {
        "precursor_review": {"evaluation": "", "feasibility": "", "risks_or_gaps": [], "improvement_ideas": []},
        "steps_review": {"evaluation": "", "feasibility": "", "risks_or_gaps": [], "improvement_ideas": []},
        "catalyst_review": {"evaluation": "", "feasibility": "", "risks_or_gaps": [], "improvement_ideas": []},
        "reaction_conditions_review": {"evaluation": "", "feasibility": "", "risks_or_gaps": [], "improvement_ideas": []},
        "laboratory_safety_review": {"hazards": [], "ppe": [], "engineering_controls": [], "critical_notes": []},
        "overall_summary": "",
        "priority_recommendations": [],
    }
    return f"""Convert the following review into strict JSON matching this schema.
Return ONLY valid JSON, no markdown, no explanation.

Schema: {json.dumps(schema)}

Text:
\"\"\"{final_text}\"\"\"
""".strip()


# ============================================================
# Lazy graph builder
# ============================================================

_graph: Any = None


def _get_graph() -> Any:
    global _graph
    if _graph is not None:
        return _graph

    from app.config import settings

    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL or None,
        temperature=0.3,
        streaming=False,
    )
    extract_llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL or None,
        temperature=0.0,
        streaming=False,
    )

    _isolated_config = {"callbacks": []}

    def _call(llm: ChatOpenAI, system: str, user: str) -> str:
        response = llm.invoke([("system", system), ("user", user)], config=_isolated_config)
        content = response.content
        return content if isinstance(content, str) else str(content)

    def precursor_node(state: GraphState) -> GraphState:
        return {"precursor_answer": _call(llm, SYSTEM_ANALYSIS,
            _make_analysis_prompt(state["protocol_text"], "precursors / starting materials / reagents"))}

    def steps_node(state: GraphState) -> GraphState:
        return {"steps_answer": _call(llm, SYSTEM_ANALYSIS,
            _make_analysis_prompt(state["protocol_text"], "step-by-step synthesis workflow / procedural sequence"))}

    def catalyst_node(state: GraphState) -> GraphState:
        return {"catalyst_answer": _call(llm, SYSTEM_ANALYSIS,
            _make_analysis_prompt(state["protocol_text"], "catalyst identity, preparation, handling, applicability"))}

    def conditions_node(state: GraphState) -> GraphState:
        return {"conditions_answer": _call(llm, SYSTEM_ANALYSIS,
            _make_analysis_prompt(state["protocol_text"], "reaction conditions: temperature, time, pressure, reactor setup"))}

    def safety_node(state: GraphState) -> GraphState:
        return {"safety_answer": _call(llm, SYSTEM_ANALYSIS,
            _make_safety_prompt(state["protocol_text"]))}

    def aggregate_node(state: GraphState) -> GraphState:
        return {"aggregated_answer": _call(llm, SYSTEM_AGGREGATION, _make_aggregate_prompt(state))}

    def final_text_node(state: GraphState) -> GraphState:
        prompt = f"""Write the final expert assessment of this chemistry protocol.
Use sections, be concise but complete, end with priority recommendations.

Protocol: \"\"\"{state["protocol_text"]}\"\"\"
Aggregated review: \"\"\"{state["aggregated_answer"]}\"\"\"
"""
        return {"final_text": _call(llm, SYSTEM_FINAL, prompt)}

    def structured_output_node(state: GraphState) -> GraphState:
        raw = _call(extract_llm, SYSTEM_JSON, _make_structured_json_prompt(state["final_text"]))
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        try:
            parsed = json.loads(raw)
            validated = FinalStructuredOutput.model_validate(parsed)
            return {"structured_output": validated.model_dump()}
        except (json.JSONDecodeError, ValidationError):
            return {"structured_output": {}}

    graph = StateGraph(GraphState)
    graph.add_node("precursor_review", precursor_node)
    graph.add_node("steps_review", steps_node)
    graph.add_node("catalyst_review", catalyst_node)
    graph.add_node("conditions_review", conditions_node)
    graph.add_node("safety_review", safety_node)
    graph.add_node("aggregate", aggregate_node)
    graph.add_node("final_text", final_text_node)
    graph.add_node("structured_output", structured_output_node)

    for branch in ["precursor_review", "steps_review", "catalyst_review", "conditions_review", "safety_review"]:
        graph.add_edge(START, branch)
        graph.add_edge(branch, "aggregate")

    graph.add_edge("aggregate", "final_text")
    graph.add_edge("final_text", "structured_output")
    graph.add_edge("structured_output", END)

    _graph = graph.compile()
    return _graph


# ============================================================
# Tool
# ============================================================

@tool
def protocol_review(protocol_text: str) -> str:
    """Review a chemistry laboratory protocol for feasibility, safety, and completeness.

    Runs a parallel multi-branch LangGraph review covering precursors, synthesis steps,
    catalyst, reaction conditions, and laboratory safety. Returns a structured expert report.

    Args:
        protocol_text: Full text of the laboratory protocol to review (min 40 characters).
    """
    s = (protocol_text or "").strip()
    if not s:
        return "Error: protocol text is empty."
    if len(s) < 40:
        return "Error: protocol text is too short for meaningful review."
    if len(s) > 100_000:
        return "Error: protocol text is too long."

    try:
        graph = _get_graph()
        result = graph.invoke({"protocol_text": s}, config={"callbacks": []})
        final_text = result.get("final_text", "")
        structured = result.get("structured_output", {})

        output = final_text
        if structured.get("priority_recommendations"):
            recs = "\n".join(f"- {r}" for r in structured["priority_recommendations"])
            output += f"\n\n**Priority recommendations:**\n{recs}"
        return output
    except Exception as e:
        return f"Error during protocol review: {e}"
