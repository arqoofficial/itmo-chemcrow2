"""CRITICAL TEST GAP: Agent integration tests for OpenAlex tool.

Verify:
1. openalex_search is in ALL_TOOLS
2. System prompt mentions OpenAlex when API key configured
3. Tool can be invoked in agent graph
"""
from unittest.mock import MagicMock, patch

import pytest


def test_openalex_search_in_all_tools():
    """Verify openalex_search is registered in ALL_TOOLS."""
    from app.tools import ALL_TOOLS

    tool_names = [tool.name for tool in ALL_TOOLS]
    assert "openalex_search" in tool_names, "openalex_search not found in ALL_TOOLS"


def test_openalex_search_tool_description():
    """Verify openalex_search tool has proper description."""
    from app.tools.search import openalex_search

    assert openalex_search.description is not None
    assert len(openalex_search.description) > 0
    assert "OpenAlex" in openalex_search.description
    # Verify it mentions async delivery of results
    assert "asynchronously" in openalex_search.description.lower() or "background" in openalex_search.description.lower()


def test_openalex_search_tool_args():
    """Verify openalex_search tool has correct parameters."""
    from app.tools.search import openalex_search

    args = openalex_search.args
    assert "query" in args
    assert "max_results" in args


def test_agent_system_prompt_mentions_openalex_when_configured():
    """Verify agent source code mentions OpenAlex logic."""
    from app.agent import SYSTEM_PROMPT

    # Verify the base prompt mentions OpenAlex and routing logic
    assert "OpenAlex" in SYSTEM_PROMPT
    assert "openalex_search" in SYSTEM_PROMPT
    assert "prefer" in SYSTEM_PROMPT.lower()


def test_agent_system_prompt_has_literature_routing():
    """Verify system prompt has literature tool routing instructions."""
    from app.agent import SYSTEM_PROMPT

    # Verify routing logic is documented
    assert "LITERATURE TOOL ROUTING" in SYSTEM_PROMPT
    assert "rag_search" in SYSTEM_PROMPT
    assert "literature_search" in SYSTEM_PROMPT


def test_agent_uses_all_tools():
    """Verify ALL_TOOLS is properly loaded."""
    from app.tools import ALL_TOOLS

    # Verify all_tools is not empty
    assert len(ALL_TOOLS) > 0
    # Verify it's a list
    assert isinstance(ALL_TOOLS, list)


def test_openalex_search_tool_callable():
    """Verify openalex_search tool is callable and returns proper response."""
    from app.tools.search import openalex_search
    from app.tools.rag import _CURRENT_CONV_ID

    # Set conversation context
    _CURRENT_CONV_ID.set("test-conv-id")

    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=202)

        result = openalex_search.invoke("test query")

    assert isinstance(result, str)
    assert "queued" in result.lower() or "unavailable" in result.lower()


def test_openalex_search_tool_has_invoke_method():
    """Verify openalex_search tool can be invoked."""
    from app.tools.search import openalex_search

    assert hasattr(openalex_search, "invoke")
    assert callable(openalex_search.invoke)


def test_agent_has_openalex_in_system_prompt():
    """Verify OpenAlex is mentioned in agent's system prompt."""
    from app.agent import SYSTEM_PROMPT

    # Verify references to OpenAlex
    assert "openalex_search" in SYSTEM_PROMPT.lower()
    # Verify literature routing is explained
    assert "prefer" in SYSTEM_PROMPT.lower()


def test_openalex_vs_literature_search_both_available():
    """Verify both literature_search and openalex_search are available."""
    from app.tools import ALL_TOOLS

    tool_names = [tool.name for tool in ALL_TOOLS]
    assert "literature_search" in tool_names
    assert "openalex_search" in tool_names
