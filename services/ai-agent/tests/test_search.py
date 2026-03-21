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
    mock_resp.status_code = 200
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
                "externalIds": {"DOI": "10.0000/mock.doi"},
            }
        ]
    }
    mock_get.return_value = mock_resp

    result = literature_search.invoke("caffeine molecular properties")
    assert isinstance(result, str)
    assert "Caffeine and Health" in result


@patch("app.tools.search.requests.get")
def test_literature_search_doi_from_api(mock_get):
    """DOI from externalIds is shown directly without HTML fetch."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {
                "title": "Caffeine and Health",
                "authors": [{"name": "Smith J"}],
                "abstract": "A review of caffeine effects.",
                "year": 2023,
                "citationCount": 42,
                "url": "https://www.semanticscholar.org/paper/abc123",
                "externalIds": {"DOI": "10.1016/j.caffeine.2023.001"},
            }
        ]
    }
    mock_get.return_value = mock_resp

    result = literature_search.invoke("caffeine molecular properties")
    assert "10.1016/j.caffeine.2023.001" in result
    # Only one requests.get call — no HTML fetch needed
    mock_get.assert_called_once()


@patch("app.tools.search.requests.get")
def test_literature_search_doi_from_html_fallback(mock_get):
    """Falls back to HTML scraping when externalIds is empty."""
    s2_resp = MagicMock()
    s2_resp.status_code = 200
    s2_resp.raise_for_status = MagicMock()
    s2_resp.json.return_value = {
        "data": [
            {
                "title": "No DOI in API",
                "authors": [{"name": "Jones A"}],
                "abstract": "Abstract text.",
                "year": 2022,
                "citationCount": 5,
                "url": "https://pubs.acs.org/doi/10.1021/fallback",
                "externalIds": {},
            }
        ]
    }

    html_resp = MagicMock()
    html_resp.ok = True
    html_resp.text = '<meta name="citation_doi" content="10.9999/fallback.doi"/>'

    mock_get.side_effect = [s2_resp, html_resp]

    result = literature_search.invoke("some chemistry topic")
    assert "10.9999/fallback.doi" in result
    assert mock_get.call_count == 2  # S2 API + HTML fetch


@patch("app.tools.search.requests.get")
def test_literature_search_doi_from_html_fallback_null_external_ids(mock_get):
    """Falls back to HTML scraping when externalIds key is absent entirely."""
    s2_resp = MagicMock()
    s2_resp.status_code = 200
    s2_resp.raise_for_status = MagicMock()
    s2_resp.json.return_value = {
        "data": [
            {
                "title": "Old Paper No IDs",
                "authors": [],
                "abstract": "Old paper.",
                "year": 2005,
                "citationCount": 1,
                "url": "https://pubs.acs.org/doi/10.1021/oldpaper",
                # externalIds key intentionally absent
            }
        ]
    }

    html_resp = MagicMock()
    html_resp.ok = True
    html_resp.text = '<a href="https://doi.org/10.8888/old.paper">link</a>'

    mock_get.side_effect = [s2_resp, html_resp]

    result = literature_search.invoke("old chemistry")
    assert "10.8888/old.paper" in result


@patch("app.tools.search.requests.get")
def test_literature_search_doi_not_available(mock_get):
    """Shows 'DOI: N/A' gracefully when no DOI found anywhere."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {
                "title": "No DOI Paper",
                "authors": [],
                "abstract": None,
                "year": 2020,
                "citationCount": 0,
                "url": "https://www.semanticscholar.org/paper/nodoi",
                "externalIds": {},
            }
        ]
    }

    html_resp = MagicMock(ok=True, text="<html>No DOI here</html>")
    mock_get.side_effect = [mock_resp, html_resp]

    result = literature_search.invoke("obscure topic")
    assert "DOI: N/A" in result
