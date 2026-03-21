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


@patch("app.tools.search.requests.get")
def test_literature_search(mock_get):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {
                "title": "Caffeine and Health",
                "authors": [{"name": "Smith J"}],
                "abstract": "A review of caffeine effects.",
                "year": 2023,
                "citationCount": 42,
                "url": "https://example.com/paper",
            }
        ]
    }
    mock_get.return_value = mock_resp

    result = literature_search.invoke("caffeine molecular properties")
    assert isinstance(result, str)
    assert "Caffeine and Health" in result
