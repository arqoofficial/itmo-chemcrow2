import ast
from unittest.mock import MagicMock, patch

from app.tools.search import literature_search, patent_check
from app.tools.utils import split_smiles


def test_patent_check_single(caffeine_smiles):
    result = patent_check.invoke(caffeine_smiles)
    parsed = ast.literal_eval(result)
    assert len(parsed) == 1
    assert parsed[caffeine_smiles] in ("Patented", "Novel")


def test_patent_check_multiple(molpair_dissimilar):
    result = patent_check.invoke(molpair_dissimilar)
    parsed = ast.literal_eval(result)
    mols = split_smiles(molpair_dissimilar)
    assert len(parsed) == len(mols)


def test_patent_check_invalid_iupac(iupac_name):
    result = patent_check.invoke(iupac_name)
    assert result == "Invalid SMILES string"


def test_literature_search_no_conversation_context():
    """Returns an error message when no conversation context is set."""
    from app.tools.rag import _CURRENT_CONV_ID
    _CURRENT_CONV_ID.set(None)

    result = literature_search.invoke("caffeine molecular properties")
    assert "no conversation context" in result.lower()


def test_literature_search_returns_queued_message():
    """Returns a queued message when conversation context is set."""
    with patch("app.tools.search.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=202)
        from app.tools.rag import _CURRENT_CONV_ID
        _CURRENT_CONV_ID.set("conv-abc")

        result = literature_search.invoke("caffeine molecular properties")

    assert isinstance(result, str)
    assert "queued" in result.lower()


def test_literature_search_queues_and_returns_immediately():
    """literature_search should POST to backend and return 'queued' message without blocking."""
    from unittest.mock import patch, MagicMock
    with patch("app.tools.search.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=202)
        # Set conversation context
        from app.tools.rag import _CURRENT_CONV_ID
        _CURRENT_CONV_ID.set("test-conv-123")

        result = literature_search.invoke({"query": "aspirin synthesis", "max_results": 3})

    assert "queued" in result.lower()
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs.get("json") or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"])
    assert payload["type"] == "s2_search"
    assert payload["conversation_id"] == "test-conv-123"
    assert payload["query"] == "aspirin synthesis"
