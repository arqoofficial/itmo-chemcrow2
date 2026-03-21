"""Reaction prediction and retrosynthesis tools.

Uses local Docker containers:
- reaction-predict (port 8051): forward reaction prediction
- retrosynthesis (port 8052): retrosynthetic analysis

Container images: doncamilom/rxnpred, doncamilom/retrosynthesis
"""
from __future__ import annotations

import json
import logging

import requests
from langchain.tools import tool

from app.tools.utils import is_smiles

logger = logging.getLogger(__name__)


def _clean_retro_actions(d: dict) -> list[dict]:
    """Extract reaction steps from retrosynthesis tree."""
    results = []
    if "metadata" in d:
        if "mapped_reaction_smiles" in d["metadata"]:
            r = d["metadata"]["mapped_reaction_smiles"].split(">>")
            results.append({"reactants": r[1], "products": r[0]})
    if "children" in d:
        for c in d["children"]:
            results.extend(_clean_retro_actions(c))
    return results


def _format_synthesis_steps(paths: list[dict]) -> str:
    """Format retrosynthesis paths into readable text."""
    if not paths:
        return "No retrosynthetic paths found."

    path = paths[0]
    rxns = _clean_retro_actions(path)
    if not rxns:
        return f"Retrosynthesis result (raw): {json.dumps(path, indent=2)}"

    lines = [f"Retrosynthetic analysis found {len(rxns)} step(s):\n"]
    for i, rxn in enumerate(rxns, 1):
        lines.append(f"Step {i}: {rxn['reactants']} → {rxn['products']}")
    return "\n".join(lines)


@tool
def reaction_predict(reactants: str) -> str:
    """Predict the outcome of a chemical reaction.

    Takes as input the SMILES of the reactants separated by a dot '.', returns SMILES of the products.

    Args:
        reactants: SMILES of reactants separated by '.', e.g. 'CC=O.[H][H]'.
    """
    from app.config import settings

    if not is_smiles(reactants):
        return "Incorrect input."
    try:
        response = requests.post(
            f"{settings.REACTION_PREDICT_URL}/api/v1/run",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"smiles": reactants}),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["product"][0]
    except Exception:
        logger.exception("Reaction prediction error")
        return "Error in prediction. The reaction prediction service may not be available."


@tool
def reaction_retrosynthesis(smiles: str) -> str:
    """Obtain the synthetic route to a chemical compound.

    Takes as input the SMILES of the product, returns the synthesis steps.

    Args:
        smiles: SMILES of the target molecule.
    """
    from app.config import settings

    if not is_smiles(smiles):
        return "Incorrect input."
    try:
        response = requests.post(
            f"{settings.RETROSYNTHESIS_URL}/api/v1/run",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"smiles": smiles}),
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        paths = data.get("routes", data) if isinstance(data, dict) else data
        return _format_synthesis_steps(paths)
    except Exception:
        logger.exception("Retrosynthesis error")
        return "Error in retrosynthesis. The retrosynthesis service may not be available."
