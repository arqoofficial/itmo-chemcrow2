"""Tool registry with conditional loading based on available API keys."""
from __future__ import annotations

import logging

from langchain.tools import BaseTool

logger = logging.getLogger(__name__)


def get_all_tools() -> list[BaseTool]:
    """Build tool list, conditionally including tools that need API keys.

    Imports are inside the function to handle missing dependencies gracefully.
    """
    from app.config import settings

    tools: list[BaseTool] = []

    # Core tools (RDKit, PubChem — always available)
    try:
        from app.tools.admet import smiles_to_admet
        from app.tools.converters import (
            query2cas_tool,
            query2smiles_tool,
            smiles2name_tool,
        )
        from app.tools.rdkit_tools import func_groups, mol_similarity, smiles2weight
        from app.tools.safety import (
            control_chem_check,
            explosive_check,
            similar_control_chem_check,
        )

        tools.extend([
            query2smiles_tool, query2cas_tool, smiles2name_tool,
            smiles2weight, mol_similarity, func_groups,
            control_chem_check, similar_control_chem_check, explosive_check,
            smiles_to_admet,
        ])
    except ImportError:
        logger.exception("Failed to load core chemistry tools (rdkit missing?)")

    # Search tools (molbloom + Semantic Scholar)
    try:
        from app.tools.search import literature_search, patent_check, web_search

        tools.extend([patent_check, literature_search])

        if settings.SERP_API_KEY:
            tools.append(web_search)
            logger.info("WebSearch tool enabled (SERP_API_KEY set)")
    except ImportError:
        logger.exception("Failed to load search tools (molbloom missing?)")

    # Protocol review tool
    try:
        from app.tools.protocol_review import protocol_review

        tools.append(protocol_review)
        logger.info("ProtocolReview tool enabled")
    except ImportError:
        logger.exception("Failed to load protocol review tool")

    # Reaction tools (local Docker containers)
    try:
        from app.tools.reactions import reaction_predict, reaction_retrosynthesis

        tools.extend([reaction_predict, reaction_retrosynthesis])
    except ImportError:
        logger.exception("Failed to load reaction tools")

    # RAG tool (local corpus + hybrid retrieval)
    try:
        from app.tools.rag import rag_search

        tools.append(rag_search)
    except ImportError:
        logger.exception("Failed to load RAG tool")

    # Optional: molecule pricing (needs CHEMSPACE_API_KEY)
    if settings.CHEMSPACE_API_KEY:
        try:
            from app.tools.chemspace import get_molecule_price

            tools.append(get_molecule_price)
            logger.info("GetMoleculePrice tool enabled (CHEMSPACE_API_KEY set)")
        except ImportError:
            logger.exception("Failed to load chemspace tool")

    logger.info("Loaded %d tools", len(tools))
    return tools


ALL_TOOLS = get_all_tools()
