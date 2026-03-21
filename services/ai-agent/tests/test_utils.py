from unittest.mock import MagicMock, patch

from app.tools.utils import (
    _scrape_doi_from_url,
    canonical_smiles,
    is_cas,
    is_multiple_smiles,
    is_smiles,
    largest_mol,
    split_smiles,
    tanimoto,
)


def test_is_smiles_valid(caffeine_smiles):
    assert is_smiles(caffeine_smiles) is True


def test_is_smiles_invalid():
    assert is_smiles("not_a_molecule") is False


def test_is_smiles_empty():
    assert is_smiles("") is False


def test_is_multiple_smiles(molpair_dissimilar):
    assert is_multiple_smiles(molpair_dissimilar) is True


def test_is_not_multiple_smiles(caffeine_smiles):
    assert is_multiple_smiles(caffeine_smiles) is False


def test_split_smiles(molpair_dissimilar):
    parts = split_smiles(molpair_dissimilar)
    assert len(parts) == 2


def test_is_cas_valid():
    assert is_cas("58-08-2") is True


def test_is_cas_invalid():
    assert is_cas("caffeine") is False


def test_canonical_smiles(caffeine_smiles):
    result = canonical_smiles(caffeine_smiles)
    assert isinstance(result, str)
    assert result != "Invalid SMILES string"


def test_canonical_smiles_invalid():
    assert canonical_smiles("invalid") == "Invalid SMILES string"


def test_tanimoto_similar(molpair_similar):
    s1, s2 = molpair_similar.split(".")
    sim = tanimoto(s1, s2)
    assert isinstance(sim, float)
    assert sim > 0.6


def test_tanimoto_dissimilar(molpair_dissimilar):
    s1, s2 = molpair_dissimilar.split(".")
    sim = tanimoto(s1, s2)
    assert isinstance(sim, float)
    assert sim < 0.5


def test_tanimoto_invalid():
    result = tanimoto("invalid", "also_invalid")
    assert isinstance(result, str)  # error string


def test_largest_mol():
    smi = "O.CCO.CCCCCC"
    assert largest_mol(smi) == "CCCCCC"


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
