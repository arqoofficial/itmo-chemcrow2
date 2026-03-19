from __future__ import annotations

from langchain.tools import tool


@tool
def literature_search(query: str, max_results: int = 5) -> dict:
    """Search scientific literature for chemistry-related papers and articles.

    Args:
        query: Search query describing the topic of interest.
        max_results: Maximum number of results to return (default 5).

    Returns:
        Dictionary with search results including titles, authors, and abstracts.
    """
    # TODO: integrate with PubChem, CrossRef, or Semantic Scholar API
    return {
        "query": query,
        "max_results": max_results,
        "status": "stub",
        "message": "Literature search service not yet connected. "
        "This tool will search PubChem, CrossRef, and Semantic Scholar.",
    }
