import ast
from unittest.mock import MagicMock, patch

from app.tools.search import literature_search, patent_check
from app.tools.utils import _scrape_doi_from_url, split_smiles


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


@patch("app.tools.utils.requests.get")
def test_scrape_doi_citation_meta_tag(mock_get):
    """Extracts DOI from citation_doi meta tag (content before name attr)."""
    mock_get.return_value = MagicMock(
        ok=True,
        text='<html><meta name="citation_doi" content="10.1234/test.paper"/></html>',
    )
    assert _scrape_doi_from_url("https://example.com/paper") == "10.1234/test.paper"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_citation_meta_tag_reversed(mock_get):
    """Extracts DOI from citation_doi meta tag (name before content attr)."""
    mock_get.return_value = MagicMock(
        ok=True,
        text='<meta content="10.1234/reversed.paper" name="citation_doi"/>',
    )
    assert _scrape_doi_from_url("https://example.com/paper") == "10.1234/reversed.paper"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_citation_meta_tag_wins_over_doi_org(mock_get):
    """citation_doi meta tag takes priority over doi.org link."""
    mock_get.return_value = MagicMock(
        ok=True,
        text=(
            '<meta name="citation_doi" content="10.1111/priority"/>'
            '<a href="https://doi.org/10.2222/secondary">link</a>'
        ),
    )
    assert _scrape_doi_from_url("https://example.com/paper") == "10.1111/priority"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_doi_org_link(mock_get):
    """Extracts DOI from a doi.org hyperlink when no meta tag present."""
    mock_get.return_value = MagicMock(
        ok=True,
        text='<a href="https://doi.org/10.5678/another.paper">Full text</a>',
    )
    assert _scrape_doi_from_url("https://example.com/paper") == "10.5678/another.paper"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_bare_pattern(mock_get):
    """Extracts DOI from bare DOI pattern when no meta tag or doi.org link present."""
    mock_get.return_value = MagicMock(
        ok=True,
        text="See DOI: 10.9999/bare.doi.here for details",
    )
    assert _scrape_doi_from_url("https://example.com/paper") == "10.9999/bare.doi.here"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_strips_trailing_punctuation(mock_get):
    """Trailing punctuation (period, comma) is stripped from bare DOI matches."""
    mock_get.return_value = MagicMock(
        ok=True,
        text="Reference: 10.9999/doi.with.trailing.",
    )
    doi = _scrape_doi_from_url("https://example.com/paper")
    assert doi == "10.9999/doi.with.trailing"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_not_found(mock_get):
    """Returns None when no DOI is present."""
    mock_get.return_value = MagicMock(ok=True, text="<html>No DOI here</html>")
    assert _scrape_doi_from_url("https://example.com/paper") is None


@patch("app.tools.utils.requests.get")
def test_scrape_doi_http_error(mock_get):
    """Returns None on non-OK HTTP response."""
    mock_get.return_value = MagicMock(ok=False)
    assert _scrape_doi_from_url("https://example.com/paper") is None
