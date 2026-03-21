from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError
from typing_extensions import TypedDict

from langgraph.graph import END, START, StateGraph
from langchain_openai import ChatOpenAI


load_dotenv()
# Optional Langfuse support
try:
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler

    _LANGFUSE_AVAILABLE = True
except Exception:  # pragma: no cover
    Langfuse = None
    CallbackHandler = None
    _LANGFUSE_AVAILABLE = False



class ProtocolReviewError(ValueError):
    """Predictable user-facing error for invalid protocol-review input."""


# ============================================================
# ENV / MODELS
# ============================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_API_BASE")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set.")

_LANGFUSE_HANDLER = None
if _LANGFUSE_AVAILABLE:
    try:
        langfuse = Langfuse()
        langfuse.auth_check()
        _LANGFUSE_HANDLER = CallbackHandler()
    except Exception:
        _LANGFUSE_HANDLER = None

LF_CONFIG: Dict[str, Any] = {}
if _LANGFUSE_HANDLER is not None:
    LF_CONFIG = {"callbacks": [_LANGFUSE_HANDLER]}

analysis_llm = ChatOpenAI(
    model=OPENAI_MODEL,
    base_url=OPENAI_BASE_URL,
    api_key=OPENAI_API_KEY,
    temperature=0.3,
)

extract_base_llm = ChatOpenAI(
    model=OPENAI_MODEL,
    base_url=OPENAI_BASE_URL,
    api_key=OPENAI_API_KEY,
    temperature=0.0,
)


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
    structured_json_raw: str
    structured_output: Dict[str, Any]


# ============================================================
# Helpers
# ============================================================

def validate_protocol_text(protocol_text: str) -> str:
    s = (protocol_text or "").strip()
    if not s:
        raise ProtocolReviewError("Protocol text is empty.")
    if len(s) < 40:
        raise ProtocolReviewError("Protocol text is too short for meaningful review.")
    if len(s) > 100_000:
        raise ProtocolReviewError("Protocol text is too long.")
    return s


def call_freeform(llm: ChatOpenAI, system_prompt: str, user_prompt: str) -> str:
    messages = [
        ("system", system_prompt),
        ("user", user_prompt),
    ]
    response = llm.invoke(messages, config=LF_CONFIG)
    content = response.content
    return content if isinstance(content, str) else str(content)


def parse_json_safely(text: str) -> Dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


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


def make_analysis_prompt(protocol_text: str, focus: str) -> str:
    return f"""
Review the following chemistry protocol.

Focus area: {focus}

For this focus area, provide:
1. Short description of what is present in the protocol
2. Evaluation of quality/completeness
3. Feasibility assessment
4. Missing information, ambiguities, or potential practical problems
5. Concrete approaches to improvement

Protocol:
\"\"\"
{protocol_text}
\"\"\"
""".strip()


def make_safety_prompt(protocol_text: str) -> str:
    return f"""
Review the following chemistry protocol strictly from the perspective of laboratory safety.

Provide:
1. Main hazards
2. Required PPE
3. Engineering controls / ventilation / gas-handling precautions
4. Process safety concerns
5. Missing safety instructions
6. Recommendations to improve safety documentation

Protocol:
\"\"\"
{protocol_text}
\"\"\"
""".strip()


def make_aggregate_prompt(state: GraphState) -> str:
    return f"""
You are given five expert reviews of the same laboratory protocol.

Combine them into one coherent consolidated review.
Remove repetition.
Keep the result structured with the following sections:
- Precursors and reagents
- Synthesis steps / workflow
- Catalyst
- Reaction conditions
- Laboratory safety
- Cross-cutting issues
- Priority improvements

Reviews:

[PRECURSORS]
{state.get("precursor_answer", "")}

[STEPS]
{state.get("steps_answer", "")}

[CATALYST]
{state.get("catalyst_answer", "")}

[REACTION CONDITIONS]
{state.get("conditions_answer", "")}

[LAB SAFETY]
{state.get("safety_answer", "")}
""".strip()


def make_final_text_prompt(protocol_text: str, aggregated_answer: str) -> str:
    return f"""
Write the final expert assessment of the following chemistry protocol.

Requirements:
- concise but complete
- technically strong
- readable
- organized in sections
- include overall judgment
- include priority recommendations at the end

Protocol:
\"\"\"
{protocol_text}
\"\"\"

Aggregated review:
\"\"\"
{aggregated_answer}
\"\"\"
""".strip()


def make_structured_json_prompt(final_text: str) -> str:
    return f"""
Convert the following final review into strict JSON.

Return ONLY valid JSON.
No markdown.
No explanation.
No code fence.

JSON schema:
{{
  "precursor_review": {{
    "evaluation": "string",
    "feasibility": "string",
    "risks_or_gaps": ["string"],
    "improvement_ideas": ["string"]
  }},
  "steps_review": {{
    "evaluation": "string",
    "feasibility": "string",
    "risks_or_gaps": ["string"],
    "improvement_ideas": ["string"]
  }},
  "catalyst_review": {{
    "evaluation": "string",
    "feasibility": "string",
    "risks_or_gaps": ["string"],
    "improvement_ideas": ["string"]
  }},
  "reaction_conditions_review": {{
    "evaluation": "string",
    "feasibility": "string",
    "risks_or_gaps": ["string"],
    "improvement_ideas": ["string"]
  }},
  "laboratory_safety_review": {{
    "hazards": ["string"],
    "ppe": ["string"],
    "engineering_controls": ["string"],
    "critical_notes": ["string"]
  }},
  "overall_summary": "string",
  "priority_recommendations": ["string"]
}}

Text to convert:
\"\"\"
{final_text}
\"\"\"
""".strip()


# ============================================================
# Graph nodes
# ============================================================

def precursor_node(state: GraphState) -> GraphState:
    answer = call_freeform(
        analysis_llm,
        SYSTEM_ANALYSIS,
        make_analysis_prompt(
            state["protocol_text"],
            "precursors / starting materials / reagents / substrate feed",
        ),
    )
    return {"precursor_answer": answer}


def steps_node(state: GraphState) -> GraphState:
    answer = call_freeform(
        analysis_llm,
        SYSTEM_ANALYSIS,
        make_analysis_prompt(
            state["protocol_text"],
            "step-by-step synthesis workflow / procedural sequence / operational completeness",
        ),
    )
    return {"steps_answer": answer}


def catalyst_node(state: GraphState) -> GraphState:
    answer = call_freeform(
        analysis_llm,
        SYSTEM_ANALYSIS,
        make_analysis_prompt(
            state["protocol_text"],
            "catalyst identity, preparation state, handling, applicability, and catalyst-related completeness",
        ),
    )
    return {"catalyst_answer": answer}


def conditions_node(state: GraphState) -> GraphState:
    answer = call_freeform(
        analysis_llm,
        SYSTEM_ANALYSIS,
        make_analysis_prompt(
            state["protocol_text"],
            "reaction conditions: temperature, time, gas flow, mixing, acidity, reactor setup, and control variables",
        ),
    )
    return {"conditions_answer": answer}


def safety_node(state: GraphState) -> GraphState:
    answer = call_freeform(
        analysis_llm,
        SYSTEM_ANALYSIS,
        make_safety_prompt(state["protocol_text"]),
    )
    return {"safety_answer": answer}


def aggregate_node(state: GraphState) -> GraphState:
    answer = call_freeform(
        analysis_llm,
        SYSTEM_AGGREGATION,
        make_aggregate_prompt(state),
    )
    return {"aggregated_answer": answer}


def final_text_node(state: GraphState) -> GraphState:
    answer = call_freeform(
        analysis_llm,
        SYSTEM_FINAL,
        make_final_text_prompt(state["protocol_text"], state["aggregated_answer"]),
    )
    return {"final_text": answer}


def structured_output_node(state: GraphState) -> GraphState:
    raw = call_freeform(
        extract_base_llm,
        SYSTEM_JSON,
        make_structured_json_prompt(state["final_text"]),
    )
    parsed = parse_json_safely(raw)
    validated = FinalStructuredOutput.model_validate(parsed)
    return {
        "structured_json_raw": raw,
        "structured_output": validated.model_dump(),
    }


# ============================================================
# Graph build
# ============================================================

def _build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("precursor_review", precursor_node)
    graph.add_node("steps_review", steps_node)
    graph.add_node("catalyst_review", catalyst_node)
    graph.add_node("conditions_review", conditions_node)
    graph.add_node("safety_review", safety_node)

    graph.add_node("aggregate", aggregate_node)
    graph.add_node("final_text", final_text_node)
    graph.add_node("structured_output", structured_output_node)

    graph.add_edge(START, "precursor_review")
    graph.add_edge(START, "steps_review")
    graph.add_edge(START, "catalyst_review")
    graph.add_edge(START, "conditions_review")
    graph.add_edge(START, "safety_review")

    graph.add_edge("precursor_review", "aggregate")
    graph.add_edge("steps_review", "aggregate")
    graph.add_edge("catalyst_review", "aggregate")
    graph.add_edge("conditions_review", "aggregate")
    graph.add_edge("safety_review", "aggregate")

    graph.add_edge("aggregate", "final_text")
    graph.add_edge("final_text", "structured_output")
    graph.add_edge("structured_output", END)

    return graph.compile()


APP_GRAPH = _build_graph()


# ============================================================
# Public service function
# ============================================================

def run_protocol_review(
    protocol_text: str,
    *,
    include_intermediate: bool = False,
) -> Dict[str, Any]:
    clean_text = validate_protocol_text(protocol_text)

    result = APP_GRAPH.invoke(
        {"protocol_text": clean_text},
        config=LF_CONFIG,
    )

    payload: Dict[str, Any] = {
        "input_protocol_text": clean_text,
        "final_text": result["final_text"],
        "structured_output": result["structured_output"],
        "warnings": [],
    }

    if include_intermediate:
        payload["intermediate"] = {
            "precursor_answer": result.get("precursor_answer"),
            "steps_answer": result.get("steps_answer"),
            "catalyst_answer": result.get("catalyst_answer"),
            "conditions_answer": result.get("conditions_answer"),
            "safety_answer": result.get("safety_answer"),
            "aggregated_answer": result.get("aggregated_answer"),
        }

    return payload