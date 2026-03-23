"""Search tools: patent check, web search, literature search.

Patent check uses molbloom (local bloom filter, no API needed).
Web search uses SerpAPI (optional, needs SERP_API_KEY).
Literature search uses Semantic Scholar REST API (free, no key required).
"""
from __future__ import annotations

import logging
import time

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

    Uses Semantic Scholar API (free, open access) to find relevant
    papers and return titles, authors, abstracts, and citation counts.

    Args:
        query: Search query describing the topic of interest.
        max_results: Maximum number of results to return (default 5).
    """
    from app.config import settings

    try:
        headers = {}
        if settings.SEMANTIC_SCHOLAR_API_KEY:
            headers["x-api-key"] = settings.SEMANTIC_SCHOLAR_API_KEY

        params = {
            "query": query,
            "limit": min(max_results, 10),
            "fields": "title,authors,abstract,year,citationCount,url,externalIds",
        }

        # Retry with increasing waits — S2 free tier rate-limits aggressively
        _retry_waits = [10, 20, 30, 60, 120]
        max_retries = len(_retry_waits)
        for attempt in range(max_retries):
            r = requests.get(
                f"{_S2_API_BASE}/paper/search",
                params=params,
                headers=headers,
                timeout=15,
            )
            if r.status_code != 429:
                break
            wait = _retry_waits[attempt]
            logger.warning("Semantic Scholar 429, retrying in %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
            time.sleep(wait)

        r.raise_for_status()
        data = r.json()

        papers = data.get("data", [])
        if not papers:
            return "No papers found for this query."

        results = []
        for p in papers:
            authors = ", ".join(a["name"] for a in (p.get("authors") or [])[:3])
            if len(p.get("authors") or []) > 3:
                authors += " et al."
            abstract = p.get("abstract") or "No abstract available."
            if len(abstract) > 300:
                abstract = abstract[:300] + "..."
            # Resolve DOI: prefer externalIds from API, fall back to HTML scraping
            ext_ids = p.get("externalIds") or {}
            doi = ext_ids.get("DOI")
            if not doi:
                paper_url = p.get("url")
                if paper_url and "semanticscholar.org" not in paper_url:
                    doi = _scrape_doi_from_url(paper_url)

            results.append(
                f"- **{p.get('title', 'Untitled')}** ({p.get('year', 'N/A')})\n"
                f"  Authors: {authors}\n"
                f"  Citations: {p.get('citationCount', 0)}\n"
                f"  DOI: {doi or 'N/A'}\n"
                f"  Abstract: {abstract}\n"
                f"  URL: {p.get('url', 'N/A')}"
            )
        return "\n\n".join(results)
    except requests.RequestException as e:
        logger.exception("Semantic Scholar API error")
        return f"Literature search error: {e}"
