"""Search tools: patent check, web search, literature search.

Patent check uses molbloom (local bloom filter, no API needed).
Web search uses SerpAPI (optional, needs SERP_API_KEY).
Literature search uses Semantic Scholar REST API (free, no key required).
"""
from __future__ import annotations

import logging
import time

import httpx
import molbloom
import requests
from langchain.tools import tool

from app.tools.utils import _scrape_doi_from_url, is_multiple_smiles, is_smiles, split_smiles

logger = logging.getLogger(__name__)

_S2_API_BASE = "https://api.semanticscholar.org/graph/v1"


@tool
def patent_check(smiles: str) -> str:
    """Input SMILES, returns if molecule is patented. Multiple SMILES can be separated by a period.

    Args:
        smiles: A SMILES string. Multiple molecules can be separated by '.'.
    """
    if is_multiple_smiles(smiles):
        smiles_list = split_smiles(smiles)
    elif is_smiles(smiles):
        smiles_list = [smiles]
    else:
        return "Invalid SMILES string"
    try:
        output_dict = {}
        for smi in smiles_list:
            r = molbloom.buy(smi, canonicalize=True, catalog="surechembl")
            output_dict[smi] = "Patented" if r else "Novel"
        return str(output_dict)
    except Exception:
        return "Invalid SMILES string"


@tool
def web_search(query: str) -> str:
    """Input a specific question, returns an answer from web search.

    Do not mention any specific molecule names, but use more general
    features to formulate your questions.

    Args:
        query: A search query string.
    """
    from app.config import settings

    if not settings.SERP_API_KEY:
        return "No SerpAPI key found. This tool may not be used without a SerpAPI key."
    try:
        from langchain_community.utilities import SerpAPIWrapper

        wrapper = SerpAPIWrapper(serpapi_api_key=settings.SERP_API_KEY)
        return wrapper.run(query)
    except Exception:
        return "No results, try another search"


@tool
def literature_search(query: str, max_results: int = 5) -> str:
    """Search scientific literature for chemistry-related papers.

    Results are delivered asynchronously — you will receive them as a background
    update in this conversation shortly after calling this tool.

    Args:
        query: Search query describing the topic of interest.
        max_results: Maximum number of results to return (default 5).
    """
    from app.config import settings
    from app.tools.rag import _CURRENT_CONV_ID

    conversation_id = _CURRENT_CONV_ID.get(None)
    if not conversation_id:
        return "Literature search unavailable: no conversation context."

    try:
        httpx.post(
            f"{settings.BACKEND_INTERNAL_URL}/internal/queue-background-tool",
            json={
                "type": "s2_search",
                "conversation_id": conversation_id,
                "query": query,
                "max_results": max_results,
            },
            timeout=5,
        )
        return "Literature search queued. Results will appear in this conversation shortly."
    except Exception:
        logger.exception("Failed to queue literature search")
        return "Literature search unavailable: could not reach the queue endpoint."


@tool
def openalex_search(query: str, max_results: int = 5) -> str:
    """Search OpenAlex for scientific papers and research works.

    OpenAlex provides free access to 250M+ scholarly research papers with
    comprehensive metadata. Results are delivered asynchronously — you will
    receive them as a background update in this conversation shortly after
    calling this tool.

    Args:
        query: Search query describing the topic of interest.
        max_results: Maximum number of results to return (default 5).
    """
    from app.config import settings
    from app.tools.rag import _CURRENT_CONV_ID

    if not settings.OPENALEX_API_KEY:
        return "OpenAlex search unavailable: API key not configured. Using Semantic Scholar instead."

    conversation_id = _CURRENT_CONV_ID.get(None)
    if not conversation_id:
        return "OpenAlex search unavailable: no conversation context."

    try:
        httpx.post(
            f"{settings.BACKEND_INTERNAL_URL}/internal/queue-background-tool",
            json={
                "type": "openalex_search",
                "conversation_id": conversation_id,
                "query": query,
                "max_results": max_results,
            },
            timeout=5,
        )
        return "OpenAlex search queued. Results will appear in this conversation shortly."
    except Exception:
        logger.exception("Failed to queue OpenAlex search")
        return "OpenAlex search unavailable: could not reach the queue endpoint."
