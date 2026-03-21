from __future__ import annotations

import asyncio
import contextvars
import json
import operator
import os
import re
import string
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Annotated

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError
from typing_extensions import TypedDict

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, inchi, rdChemReactions, rdMolDescriptors
from rdkit.Chem.MolStandardize import rdMolStandardize

try:
    import pubchempy as pcp
except Exception:
    pcp = None

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

# Mandatory Langfuse support
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler


load_dotenv()

_LANGFUSE_CLIENT = Langfuse()
_LANGFUSE_CLIENT.auth_check()
_LANGFUSE_HANDLER = CallbackHandler()
LF_CONFIG: RunnableConfig = {"callbacks": [_LANGFUSE_HANDLER]}


llm0 = ChatOpenAI(
    model=os.getenv("MODEL0_MODEL"),
    api_key=os.getenv("MODEL0_API_KEY"),
    base_url=os.getenv("MODEL0_BASE_URL"),
    temperature=0.2,
    timeout=120,
    max_retries=1,
)

llm1 = ChatOpenAI(
    model=os.getenv("MODEL1_MODEL"),
    api_key=os.getenv("MODEL1_API_KEY"),
    base_url=os.getenv("MODEL1_BASE_URL"),
    temperature=0.2,
    timeout=120,
    max_retries=1,
)

llm2 = ChatOpenAI(
    model=os.getenv("MODEL2_MODEL"),
    api_key=os.getenv("MODEL2_API_KEY"),
    base_url=os.getenv("MODEL2_BASE_URL"),
    temperature=0.2,
    timeout=120,
    max_retries=1,
)

chairman_llm = ChatOpenAI(
    model=os.getenv("MODEL_MODEL"),
    api_key=os.getenv("MODEL_API_KEY"),
    base_url=os.getenv("MODEL_BASE_URL"),
    temperature=0.1,
    timeout=120,
    max_retries=1,
)

COUNCIL_MODELS = {
    "model_a": llm0,
    "model_b": llm1,
    "model_c": llm2,
}
CHAIRMAN_MODEL = chairman_llm

ENABLE_PUBCHEM_IUPAC = False


def message_to_text(msg: Any) -> str:
    content = getattr(msg, "content", msg)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False)


def split_reaction_smiles(reaction_smiles: str) -> dict[str, list[str] | str]:
    parts = reaction_smiles.strip().split(">")
    if len(parts) != 3:
        raise ValueError(
            "Expected reaction SMILES with 3 parts: reactants>agents>products. "
            f"Got {len(parts)} parts."
        )

    reactants_part, agents_part, products_part = parts

    def split_side(side: str) -> list[str]:
        side = side.strip()
        if not side:
            return []
        return [frag.strip() for frag in side.split(".") if frag.strip()]

    return {
        "reactants_part": reactants_part,
        "agents_part": agents_part,
        "products_part": products_part,
        "reactants": split_side(reactants_part),
        "agents": split_side(agents_part),
        "products": split_side(products_part),
    }


def clear_atom_maps(mol: Chem.Mol) -> Chem.Mol:
    mol = Chem.Mol(mol)
    for atom in mol.GetAtoms():
        if atom.HasProp("molAtomMapNumber"):
            atom.ClearProp("molAtomMapNumber")
    return mol


def standardize_mol(mol: Chem.Mol) -> Chem.Mol:
    mol = Chem.Mol(mol)
    mol = rdMolStandardize.Cleanup(mol)
    mol = rdMolStandardize.FragmentParent(mol)

    uncharger = rdMolStandardize.Uncharger()
    mol = uncharger.uncharge(mol)

    tautomer_enumerator = rdMolStandardize.TautomerEnumerator()
    mol = tautomer_enumerator.Canonicalize(mol)

    Chem.SanitizeMol(mol)
    return mol


@lru_cache(maxsize=10000)
def maybe_pubchem_iupac(smiles: str) -> str | None:
    if not ENABLE_PUBCHEM_IUPAC or pcp is None:
        return None

    try:
        rows = pcp.get_properties(["IUPACName"], smiles, "smiles")
        if rows and isinstance(rows, list):
            value = rows[0].get("IUPACName")
            return value or None
    except Exception:
        return None

    return None


def serialize_molecule(smiles: str, side: str, idx: int) -> dict:
    mol_in = Chem.MolFromSmiles(smiles)
    if mol_in is None:
        return {
            "side": side,
            "index": idx,
            "input_smiles": smiles,
            "valid": False,
            "error": "invalid_smiles",
        }

    try:
        mapped_canonical_smiles = Chem.MolToSmiles(mol_in, canonical=True, isomericSmiles=True)

        mol_unmapped = clear_atom_maps(mol_in)
        mol_std = standardize_mol(mol_unmapped)

        canonical_smiles = Chem.MolToSmiles(mol_std, canonical=True, isomericSmiles=True)
        cxsmiles = Chem.MolToCXSmiles(mol_std)
        smarts = Chem.MolToSmarts(mol_std)
        inchi_str = inchi.MolToInchi(mol_std)
        inchikey = inchi.MolToInchiKey(mol_std)
        formula = rdMolDescriptors.CalcMolFormula(mol_std)
        exact_mw = rdMolDescriptors.CalcExactMolWt(mol_std)

        return {
            "side": side,
            "index": idx,
            "input_smiles": smiles,
            "valid": True,
            "mapped_canonical_smiles": mapped_canonical_smiles,
            "canonical_smiles": canonical_smiles,
            "cxsmiles": cxsmiles,
            "smarts": smarts,
            "inchi": inchi_str,
            "inchikey": inchikey,
            "formula": formula,
            "iupac_name": maybe_pubchem_iupac(canonical_smiles),
            "molblock": Chem.MolToMolBlock(mol_std),
            "descriptors": {
                "mol_wt": Descriptors.MolWt(mol_std),
                "exact_mw": exact_mw,
                "logp": Crippen.MolLogP(mol_std),
                "tpsa": rdMolDescriptors.CalcTPSA(mol_std),
                "hba": Lipinski.NumHAcceptors(mol_std),
                "hbd": Lipinski.NumHDonors(mol_std),
                "rotatable_bonds": Lipinski.NumRotatableBonds(mol_std),
                "ring_count": rdMolDescriptors.CalcNumRings(mol_std),
                "heavy_atom_count": mol_std.GetNumHeavyAtoms(),
            },
        }

    except Exception as e:
        return {
            "side": side,
            "index": idx,
            "input_smiles": smiles,
            "valid": False,
            "error": f"{type(e).__name__}: {e}",
        }


def reaction_notations(reaction_smiles: str) -> dict:
    out = {
        "input_reaction_smiles": reaction_smiles,
        "canonical_mapped_reaction_smiles": None,
        "canonical_unmapped_reaction_smiles": None,
        "cx_reaction_smiles": None,
        "rxn_block_v2000": None,
    }

    try:
        rxn = rdChemReactions.ReactionFromSmiles(reaction_smiles)
        out["canonical_mapped_reaction_smiles"] = rdChemReactions.ReactionToSmiles(rxn, True)
        out["cx_reaction_smiles"] = rdChemReactions.ReactionToCXSmiles(rxn, True)
        out["rxn_block_v2000"] = rdChemReactions.ReactionToRxnBlock(rxn)

        rxn_unmapped = rdChemReactions.ReactionFromSmiles(reaction_smiles)
        rdChemReactions.RemoveMappingNumbersFromReactions(rxn_unmapped)
        out["canonical_unmapped_reaction_smiles"] = rdChemReactions.ReactionToSmiles(rxn_unmapped, True)
    except Exception:
        pass

    return out


def brief_component_lines(items: list[dict]) -> str:
    lines = []
    for item in items:
        if not item.get("valid"):
            lines.append(f"- invalid_smiles={item['input_smiles']}")
            continue

        label = item.get("iupac_name") or item["canonical_smiles"]
        lines.append(
            f"- name={label}; canonical_smiles={item['canonical_smiles']}; "
            f"formula={item['formula']}; inchikey={item['inchikey']}"
        )
    return "\n".join(lines)


def build_protocol_prompt(state: dict) -> str:
    reactant_lines = brief_component_lines(state["reactant_records"])
    agent_lines = brief_component_lines(state["agent_records"])
    product_lines = brief_component_lines(state["product_records"])

    return f"""
You are a senior synthetic chemist.

Your task is to infer a plausible laboratory synthesis protocol from the reaction transformation.

Important formatting rules:
- Return Markdown only.
- Do not return JSON.
- Do not mention atom mapping numbers.
- Use unmapped SMILES only if you need to reference structures.
- Follow the exact section structure below.

Required Markdown structure:

# Protocol Name
A concise protocol title.

## Precursors
- **compound / material** — **amount, equivalents, or loading if inferable; otherwise write "amount not specified"** — role or short note

## Step-by-step actions
1. Ordered experimental actions for carrying out the transformation.
2. Include reagent charging, mixing, temperature control, reaction progress monitoring, quench or workup only when chemically appropriate.
3. Keep the steps practical and chemically coherent.

## Conditions
- **Temperature:** ...
- **Time:** ...
- **Pressure:** ...
- **Atmosphere:** ...
- **Solvent:** ...
- **Catalyst / additive:** ...
- **Monitoring / endpoint:** ...

## Comments
- Explain the chemistry-based rationale for the chosen protocol.
- Mention selectivity considerations, likely roles of reagents, and key mechanistic logic.
- Mention ambiguities or plausible alternatives when the SMIRKS alone is insufficient.

Reaction summary:
- Unmapped reaction SMIRKS: {state["reaction_meta"]["canonical_unmapped_reaction_smiles"]}

Reactants:
{reactant_lines}

Agents:
{agent_lines if agent_lines else "- none"}

Products:
{product_lines}

Guidance:
- Infer a realistic protocol style from the transformation type.
- Prefer chemically typical solvents, bases, catalysts, and temperatures for this transformation.
- If exact quantities cannot be known from SMIRKS, state that clearly and use equivalents / catalyst loadings / qualitative amounts when reasonable.
- Be explicit about uncertainty rather than inventing unsupported specifics.
""".strip()


class FirstProtocolOpinion(BaseModel):
    protocol_markdown: str
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    abstain: bool = False
    abstain_reason: str = ""


class PeerReview(BaseModel):
    ranked_labels: list[str]
    top_choice_reason: str
    key_concerns: str
    abstain: bool = False
    abstain_reason: str = ""


class ChairmanDecision(BaseModel):
    final_protocol_markdown: str
    synthesis: str
    uncertainty: str
    chosen_members: list[str] = Field(default_factory=list)


class OpinionRecord(TypedDict):
    member: str
    protocol_markdown: str
    reasoning: str
    confidence: float
    abstain: bool
    abstain_reason: str
    ok: bool
    error: str


class ReviewRecord(TypedDict):
    reviewer: str
    ranked_labels: list[str]
    ranked_members: list[str]
    top_choice_reason: str
    key_concerns: str
    abstain: bool
    abstain_reason: str
    ok: bool
    error: str


class AggregateScore(TypedDict):
    member: str
    points: float
    first_place_votes: int


class ErrorRecord(TypedDict):
    stage: str
    member: str
    error: str


class ReactionCouncilState(TypedDict, total=False):
    reaction_smiles: str
    split_parts: dict
    reaction_meta: dict
    reactant_records: list[dict]
    agent_records: list[dict]
    product_records: list[dict]
    invalid_records: list[dict]
    protocol_prompt: str
    council_members: list[str]
    opinions: Annotated[list[OpinionRecord], operator.add]
    anonymous_responses: list[dict[str, str]]
    label_to_member: dict[str, str]
    reviews: Annotated[list[ReviewRecord], operator.add]
    aggregate_ranking: list[AggregateScore]
    aggregate_summary: str
    final_protocol_markdown: str
    chairman_reasoning: str
    uncertainty: str
    errors: Annotated[list[ErrorRecord], operator.add]


class Stage1Task(TypedDict):
    member: str
    protocol_prompt: str


class Stage2Task(TypedDict):
    reviewer: str
    protocol_prompt: str
    candidates: list[dict[str, str]]
    label_to_member: dict[str, str]


REFUSAL_PATTERNS = [
    "i can't help with that",
    "i cannot help with that",
    "i can't assist with that",
    "i cannot assist with that",
    "i’m sorry, but i can’t",
    "i'm sorry, but i can't",
    "i’m unable to comply",
    "i am unable to comply",
    "i can't provide",
    "i cannot provide",
    "i must refuse",
]


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def looks_like_refusal(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in REFUSAL_PATTERNS)


def extract_json_object(text: str) -> str | None:
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return None


def next_labels(n: int) -> list[str]:
    labels: list[str] = []
    i = 0
    while len(labels) < n:
        q = i
        label = ""
        while True:
            label = string.ascii_uppercase[q % 26] + label
            q = q // 26 - 1
            if q < 0:
                break
        labels.append(label)
        i += 1
    return labels


def repair_ranked_labels(raw_labels: list[str], allowed_labels: list[str]) -> list[str]:
    allowed = {x.upper() for x in allowed_labels}
    seen: set[str] = set()
    cleaned: list[str] = []
    for x in raw_labels:
        label = str(x).strip().upper()
        if label in allowed and label not in seen:
            cleaned.append(label)
            seen.add(label)
    for label in allowed_labels:
        up = label.upper()
        if up not in seen:
            cleaned.append(up)
    return cleaned


def format_candidates(candidates: list[dict[str, str]]) -> str:
    blocks = []
    for item in candidates:
        blocks.append(
            f"{item['label']}\n"
            f"Protocol:\n{item['protocol_markdown']}\n\n"
            f"Reasoning:\n{item['reasoning']}"
        )
    return "\n\n---\n\n".join(blocks)


async def runnable_ainvoke_compat(
    runnable: Any,
    inp: Any,
    config: RunnableConfig | None = None,
) -> Any:
    if hasattr(runnable, "ainvoke"):
        return await runnable.ainvoke(inp, config=config)

    ctx = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: ctx.run(runnable.invoke, inp, config))


async def invoke_structured_with_fallback(
    *,
    model: Any,
    schema: type[BaseModel],
    system_prompt: str,
    user_prompt: str,
    config: RunnableConfig | None = None,
) -> tuple[BaseModel | None, str, str | None]:
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    try:
        structured_model = model.with_structured_output(schema)
        parsed = await runnable_ainvoke_compat(structured_model, messages, config=config)
        return parsed, "", None
    except Exception as e:
        structured_error = f"{type(e).__name__}: {e}"

    fallback_user = (
        f"{user_prompt}\n\n"
        "Return ONLY valid JSON. No prose, no markdown fences.\n"
        f"JSON schema:\n{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
    )

    raw_text = ""
    try:
        raw = await runnable_ainvoke_compat(
            model,
            [SystemMessage(content=system_prompt), HumanMessage(content=fallback_user)],
            config=config,
        )
        raw_text = message_to_text(raw)

        if looks_like_refusal(raw_text):
            return None, raw_text, f"model_refusal: {raw_text[:500]}"

        json_blob = extract_json_object(raw_text)
        if not json_blob:
            return None, raw_text, f"no_json_found_after_fallback; structured_error={structured_error}"

        parsed = schema.model_validate_json(json_blob)
        return parsed, raw_text, None

    except ValidationError as e:
        return None, raw_text, f"validation_error: {e}"
    except Exception as e:
        return None, raw_text, f"fallback_error: {type(e).__name__}: {e}; structured_error={structured_error}"


def make_abstaining_opinion(member: str, reason: str) -> OpinionRecord:
    return {
        "member": member,
        "protocol_markdown": "",
        "reasoning": "",
        "confidence": 0.0,
        "abstain": True,
        "abstain_reason": reason[:500],
        "ok": False,
        "error": reason[:500],
    }


def best_available_member(state: ReactionCouncilState) -> OpinionRecord | None:
    usable = [o for o in state["opinions"] if not o["abstain"] and o["protocol_markdown"].strip()]
    if not usable:
        return None

    score_by_member = {
        item["member"]: (len(state["aggregate_ranking"]) - idx)
        for idx, item in enumerate(state["aggregate_ranking"])
    }

    def key_fn(o: OpinionRecord):
        return (
            score_by_member.get(o["member"], 0),
            o["confidence"],
            len(o["protocol_markdown"]),
        )

    return max(usable, key=key_fn)


async def node_split_reaction(state: ReactionCouncilState) -> dict:
    return {
        "split_parts": split_reaction_smiles(state["reaction_smiles"]),
        "reaction_meta": reaction_notations(state["reaction_smiles"]),
    }


async def node_normalize_components(state: ReactionCouncilState) -> dict:
    split_parts = state["split_parts"]

    reactant_records = [serialize_molecule(smi, "reactant", i) for i, smi in enumerate(split_parts["reactants"])]
    agent_records = [serialize_molecule(smi, "agent", i) for i, smi in enumerate(split_parts["agents"])]
    product_records = [serialize_molecule(smi, "product", i) for i, smi in enumerate(split_parts["products"])]

    invalid_records = [
        rec for rec in (reactant_records + agent_records + product_records)
        if not rec.get("valid", False)
    ]

    return {
        "reactant_records": reactant_records,
        "agent_records": agent_records,
        "product_records": product_records,
        "invalid_records": invalid_records,
    }


async def node_build_prompt(state: ReactionCouncilState) -> dict:
    return {"protocol_prompt": build_protocol_prompt(state)}


async def prepare_council(_: ReactionCouncilState) -> dict:
    if not COUNCIL_MODELS:
        raise ValueError("COUNCIL_MODELS is empty.")
    return {"council_members": list(COUNCIL_MODELS.keys())}


def route_stage1(state: ReactionCouncilState) -> list[Send]:
    return [
        Send("stage1_first_protocol", {"member": member, "protocol_prompt": state["protocol_prompt"]})
        for member in state["council_members"]
    ]


async def stage1_first_protocol(state: Stage1Task, config: RunnableConfig | None = None) -> dict[str, Any]:
    member = state["member"]
    model = COUNCIL_MODELS[member]

    system_prompt = (
        "You are one independent member of an LLM council.\n"
        "The user request already contains the required chemistry task and exact Markdown structure.\n"
        "Answer independently.\n"
        "Do not mention other members.\n"
        "If the request is underspecified, produce the most plausible protocol and state uncertainty honestly.\n"
        "If you truly cannot answer, set abstain=true instead of refusing."
    )

    parsed, raw_text, error = await invoke_structured_with_fallback(
        model=model,
        schema=FirstProtocolOpinion,
        system_prompt=system_prompt,
        user_prompt=state["protocol_prompt"],
        config=config or LF_CONFIG,
    )

    if parsed is None:
        return {
            "opinions": [make_abstaining_opinion(member, error or "unknown_stage1_error")],
            "errors": [{"stage": "stage1", "member": member, "error": error or raw_text[:500]}],
        }

    return {
        "opinions": [{
            "member": member,
            "protocol_markdown": parsed.protocol_markdown.strip(),
            "reasoning": parsed.reasoning.strip(),
            "confidence": clamp01(parsed.confidence),
            "abstain": bool(parsed.abstain),
            "abstain_reason": parsed.abstain_reason.strip(),
            "ok": True,
            "error": "",
        }]
    }


async def prepare_reviews(state: ReactionCouncilState) -> dict[str, Any]:
    usable = [o for o in state["opinions"] if not o["abstain"] and o["protocol_markdown"].strip()]
    labels = next_labels(len(usable))

    anonymous_responses: list[dict[str, str]] = []
    label_to_member: dict[str, str] = {}

    for label, opinion in zip(labels, usable):
        anonymous_responses.append({
            "label": label,
            "protocol_markdown": opinion["protocol_markdown"],
            "reasoning": opinion["reasoning"],
        })
        label_to_member[label] = opinion["member"]

    return {"anonymous_responses": anonymous_responses, "label_to_member": label_to_member}


def route_stage2_or_aggregate(state: ReactionCouncilState) -> list[Send] | str:
    sends: list[Send] = []

    for reviewer in state["council_members"]:
        candidates = [
            item for item in state["anonymous_responses"]
            if state["label_to_member"][item["label"]] != reviewer
        ]
        if candidates:
            sends.append(
                Send(
                    "stage2_peer_review",
                    {
                        "reviewer": reviewer,
                        "protocol_prompt": state["protocol_prompt"],
                        "candidates": candidates,
                        "label_to_member": state["label_to_member"],
                    },
                )
            )

    return sends if sends else "aggregate_reviews"


async def stage2_peer_review(state: Stage2Task, config: RunnableConfig | None = None) -> dict[str, Any]:
    reviewer = state["reviewer"]
    model = COUNCIL_MODELS[reviewer]
    candidates = state["candidates"]
    label_to_member = state["label_to_member"]
    allowed_labels = [c["label"] for c in candidates]

    system_prompt = (
        "You are one member of an LLM council performing anonymized peer review.\n"
        "Review only the other protocols.\n"
        "Judge chemical plausibility, experimental coherence, usefulness, and honesty about uncertainty.\n"
        "Do not speculate about model identities.\n"
        "If you cannot review, set abstain=true."
    )

    user_prompt = (
        f"Original protocol-generation request:\n{state['protocol_prompt']}\n\n"
        "Candidate protocols from other council members:\n\n"
        f"{format_candidates(candidates)}\n\n"
        "Rank the labels from best to worst."
    )

    parsed, raw_text, error = await invoke_structured_with_fallback(
        model=model,
        schema=PeerReview,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        config=config or LF_CONFIG,
    )

    if parsed is None:
        return {
            "reviews": [{
                "reviewer": reviewer,
                "ranked_labels": [],
                "ranked_members": [],
                "top_choice_reason": "",
                "key_concerns": "",
                "abstain": True,
                "abstain_reason": (error or "unknown_stage2_error")[:500],
                "ok": False,
                "error": (error or raw_text[:500])[:500],
            }],
            "errors": [{"stage": "stage2", "member": reviewer, "error": error or raw_text[:500]}],
        }

    ranked_labels = repair_ranked_labels(parsed.ranked_labels, allowed_labels)
    ranked_members = [label_to_member[label] for label in ranked_labels if label in label_to_member]

    return {
        "reviews": [{
            "reviewer": reviewer,
            "ranked_labels": ranked_labels,
            "ranked_members": ranked_members,
            "top_choice_reason": parsed.top_choice_reason.strip(),
            "key_concerns": parsed.key_concerns.strip(),
            "abstain": bool(parsed.abstain),
            "abstain_reason": parsed.abstain_reason.strip(),
            "ok": True,
            "error": "",
        }]
    }


async def aggregate_reviews(state: ReactionCouncilState) -> dict[str, Any]:
    scores = defaultdict(float)
    first_place_votes = defaultdict(int)

    for review in state["reviews"]:
        if review["abstain"] or not review["ranked_labels"]:
            continue

        ranked_members = review["ranked_members"]
        n = len(ranked_members)

        for idx, member in enumerate(ranked_members):
            scores[member] += n - idx
            if idx == 0:
                first_place_votes[member] += 1

    if not scores:
        for opinion in state["opinions"]:
            if not opinion["abstain"] and opinion["protocol_markdown"].strip():
                scores[opinion["member"]] = opinion["confidence"]
                first_place_votes[opinion["member"]] = 0

    ranking = sorted(
        [
            {
                "member": member,
                "points": float(points),
                "first_place_votes": int(first_place_votes[member]),
            }
            for member, points in scores.items()
        ],
        key=lambda x: (x["points"], x["first_place_votes"]),
        reverse=True,
    )

    summary = (
        "; ".join(f"{r['member']}={r['points']:.2f} pts ({r['first_place_votes']} first-place)" for r in ranking)
        if ranking else
        "No usable opinions or reviews were produced."
    )

    return {"aggregate_ranking": ranking, "aggregate_summary": summary}


async def chairman(state: ReactionCouncilState, config: RunnableConfig | None = None) -> dict[str, Any]:
    usable_opinions = [o for o in state["opinions"] if not o["abstain"] and o["protocol_markdown"].strip()]
    abstentions = [o for o in state["opinions"] if o["abstain"]]

    opinions_text = "\n\n".join(
        f"Member: {o['member']}\nProtocol:\n{o['protocol_markdown']}\n\nReasoning: {o['reasoning']}\nConfidence: {o['confidence']}"
        for o in usable_opinions
    ) or "No usable first opinions."

    reviews_text = "\n\n".join(
        f"Reviewer: {r['reviewer']}\nRanked members: {r['ranked_members']}\nTop choice reason: {r['top_choice_reason']}\nKey concerns: {r['key_concerns']}\nAbstain: {r['abstain']}\nAbstain reason: {r['abstain_reason']}"
        for r in state["reviews"]
    ) or "No peer reviews."

    abstentions_text = "\n".join(
        f"{o['member']}: {o['abstain_reason'] or o['error']}" for o in abstentions
    ) or "None."

    system_prompt = (
        "You are the Chairman of an LLM Council.\n"
        "Synthesize the strongest chemistry and protocol details from the council.\n"
        "Your final_protocol_markdown must satisfy the original request exactly.\n"
        "Resolve conflicts explicitly.\n"
        "State uncertainty honestly.\n"
        "Do not mention internal council mechanics."
    )

    user_prompt = (
        f"Original protocol-generation request:\n{state['protocol_prompt']}\n\n"
        f"Stage 1 protocols:\n{opinions_text}\n\n"
        f"Stage 2 peer reviews:\n{reviews_text}\n\n"
        f"Aggregate ranking:\n{state['aggregate_summary']}\n\n"
        f"Abstentions / failures:\n{abstentions_text}\n\n"
        "Produce one final protocol."
    )

    parsed, raw_text, error = await invoke_structured_with_fallback(
        model=CHAIRMAN_MODEL,
        schema=ChairmanDecision,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        config=config or LF_CONFIG,
    )

    if parsed is None:
        best = best_available_member(state)
        if best is None:
            return {
                "final_protocol_markdown": "",
                "chairman_reasoning": "",
                "uncertainty": "Maximum uncertainty.",
                "errors": [{"stage": "chairman", "member": "chairman", "error": error or raw_text[:500]}],
            }

        return {
            "final_protocol_markdown": best["protocol_markdown"],
            "chairman_reasoning": (
                "Chairman synthesis failed, so the system fell back to the top surviving "
                f"stage-1 protocol from {best['member']}."
            ),
            "uncertainty": "Higher than normal because the chairman step failed.",
            "errors": [{"stage": "chairman", "member": "chairman", "error": error or raw_text[:500]}],
        }

    return {
        "final_protocol_markdown": parsed.final_protocol_markdown.strip(),
        "chairman_reasoning": parsed.synthesis.strip(),
        "uncertainty": parsed.uncertainty.strip(),
    }


builder = StateGraph(ReactionCouncilState)
builder.add_node("split_reaction", node_split_reaction)
builder.add_node("normalize_components", node_normalize_components)
builder.add_node("build_prompt", node_build_prompt)
builder.add_node("prepare_council", prepare_council)
builder.add_node("stage1_first_protocol", stage1_first_protocol)
builder.add_node("prepare_reviews", prepare_reviews)
builder.add_node("stage2_peer_review", stage2_peer_review)
builder.add_node("aggregate_reviews", aggregate_reviews)
builder.add_node("chairman", chairman)

builder.add_edge(START, "split_reaction")
builder.add_edge("split_reaction", "normalize_components")
builder.add_edge("normalize_components", "build_prompt")
builder.add_edge("build_prompt", "prepare_council")
builder.add_conditional_edges("prepare_council", route_stage1, ["stage1_first_protocol"])
builder.add_edge("stage1_first_protocol", "prepare_reviews")
builder.add_conditional_edges("prepare_reviews", route_stage2_or_aggregate, ["stage2_peer_review", "aggregate_reviews"])
builder.add_edge("stage2_peer_review", "aggregate_reviews")
builder.add_edge("aggregate_reviews", "chairman")
builder.add_edge("chairman", END)

graph = builder.compile()


async def run_reaction_with_council(
    reaction_smiles: str,
    *,
    config: RunnableConfig | None = None,
) -> dict:
    initial_state: ReactionCouncilState = {
        "reaction_smiles": reaction_smiles,
        "opinions": [],
        "reviews": [],
        "errors": [],
        "anonymous_responses": [],
        "label_to_member": {},
        "aggregate_ranking": [],
        "aggregate_summary": "",
        "final_protocol_markdown": "",
        "chairman_reasoning": "",
        "uncertainty": "",
    }

    result = await graph.ainvoke(initial_state, config=(config or LF_CONFIG))
    _LANGFUSE_CLIENT.flush()
    return result