from __future__ import annotations

from langchain.tools import tool


@tool
def predict_properties(smiles: str) -> dict:
    """Predict molecular properties (logP, molecular weight, TPSA, etc.) from a SMILES string.

    Args:
        smiles: A valid SMILES string representing a molecule.

    Returns:
        Dictionary with predicted molecular properties.
    """
    # TODO: integrate with chem-tools MCP service
    return {
        "smiles": smiles,
        "status": "stub",
        "message": "Property prediction service not yet connected. "
        "This tool will compute logP, MW, TPSA, HBD/HBA and other descriptors.",
    }
