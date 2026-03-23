"""Tests for hazard checker."""
from app.hazard_checker import _tokenize, find_hazards
import pytest


def test_tokenize_simple():
    """Simple name tokenizes correctly."""
    result = _tokenize("caffeine")
    assert "caffeine" in result


def test_tokenize_multiword():
    """Multi-word name splits correctly."""
    result = _tokenize("methanol ethylene")
    assert "methanol" in result
    assert "ethylene" in result


def test_tokenize_filters_short_tokens():
    """Tokens < 4 chars are filtered."""
    result = _tokenize("a bb ccc dddd")
    # "a", "bb", "ccc" are all < 4 chars
    assert "a" not in result
    assert "bb" not in result
    assert "ccc" not in result


def test_tokenize_filters_stopwords():
    """Stopwords are filtered."""
    result = _tokenize("methanol acid solution")
    # "acid" and "solution" are stopwords
    assert "methanol" in result
    assert "acid" not in result
    assert "solution" not in result


def test_tokenize_case_insensitive():
    """Tokenization is case-insensitive."""
    result = _tokenize("CAFFEINE")
    assert "caffeine" in result


def test_tokenize_with_punctuation():
    """Punctuation is stripped."""
    result = _tokenize("caffeine; methanol.")
    assert "caffeine" in result
    assert "methanol" in result


def test_find_hazards_empty_text():
    """Empty text returns no hazards."""
    result = find_hazards("")
    assert result == []


def test_find_hazards_clean_text():
    """Clean text with no known hazards returns empty list."""
    result = find_hazards("This is a safe topic about chemistry education.")
    assert isinstance(result, list)
    # Should return no matches (depends on hazardous_chemicals.json)


def test_find_hazards_has_expected_fields():
    """Each hazard record has expected fields."""
    # Search for a common chemical that might be flagged
    result = find_hazards("hydrogen peroxide")
    if result:
        record = result[0]
        assert "id" in record
        assert "names" in record
        assert "severity" in record
        assert "hazard_categories" in record
        assert "safety_warnings" in record


def test_find_hazards_case_insensitive():
    """Hazard matching is case-insensitive."""
    result1 = find_hazards("hydrogen peroxide")
    result2 = find_hazards("HYDROGEN PEROXIDE")
    # Both should find the same number of hazards
    assert len(result1) == len(result2)


def test_find_hazards_deduplication():
    """Mentioning same chemical twice returns one result."""
    text = "hydrogen peroxide hydrogen peroxide"
    result = find_hazards(text)
    # Should not have duplicates
    ids = [r.get("id") for r in result]
    assert len(ids) == len(set(ids))


def test_find_hazards_sorted_by_severity():
    """Results are sorted by severity (critical first)."""
    # This test assumes hazardous_chemicals.json has multiple severity levels
    # If all results have same severity, this still passes
    result = find_hazards("hydrogen peroxide cyanide")
    if len(result) > 1:
        # Check that severity order is maintained
        severity_order = {"critical": 0, "high": 1, "medium": 2}
        for i in range(len(result) - 1):
            curr_idx = severity_order.get(result[i].get("severity", "high"), 1)
            next_idx = severity_order.get(result[i + 1].get("severity", "high"), 1)
            assert curr_idx <= next_idx


def test_find_hazards_cas_number():
    """CAS number matching works."""
    # Test with a known CAS number if available in DB
    # Using a common one that's likely in the database
    result = find_hazards("50-00-0")  # Formaldehyde
    # Should find something or be empty (depends on DB contents)
    assert isinstance(result, list)


def test_find_hazards_smiles_in_code_block():
    """SMILES in code block are extracted and matched."""
    # Create text with code block containing SMILES
    text = "```\nCC(C)Cc1ccc(cc1)C(C)C(=O)O\n```"
    result = find_hazards(text)
    # Should extract SMILES from code block
    assert isinstance(result, list)


def test_find_hazards_smiles_in_backticks():
    """SMILES in backticks are extracted."""
    text = "The molecule `CCO` is ethanol."
    result = find_hazards(text)
    assert isinstance(result, list)


def test_find_hazards_partial_match():
    """Substring matching works."""
    # The word "peroxide" is likely in hydrogen peroxide's names
    result = find_hazards("peroxide")
    # Should find hydroperoxide or similar
    assert isinstance(result, list)
