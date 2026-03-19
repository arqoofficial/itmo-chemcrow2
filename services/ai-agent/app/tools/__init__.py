"""Tool registry — temporary minimal version until Task 10 rewrites this."""
from __future__ import annotations

from langchain.tools import BaseTool

from app.tools.rdkit_tools import func_groups, mol_similarity, smiles2weight

ALL_TOOLS: list[BaseTool] = [
    smiles2weight,
    mol_similarity,
    func_groups,
]
