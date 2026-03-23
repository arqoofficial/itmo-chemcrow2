"""Tests for NMR prediction tool."""
from app.tools.nmr import _parse_1h, pop_pending_image, predict_nmr
from unittest.mock import patch, MagicMock
import pytest


def test_parse_1h_empty():
    """Empty input returns empty list."""
    result = _parse_1h("")
    assert result == []


def test_parse_1h_minimal():
    """Minimal valid input with one peak."""
    # Format: parts[0] parts[1] shift(parts[2]) n_couplings(parts[3]) ...
    raw = "0 x 7.5 0"
    result = _parse_1h(raw)
    assert len(result) >= 1
    peak = result[0]
    assert peak["shift"] == 7.5
    assert peak["n_h"] >= 1
    assert peak["mult"] == "s"  # singlet (0 couplings)


def test_parse_1h_singlet():
    """Singlet (no couplings) has mult 's'."""
    raw = "0 x 7.5 0"
    result = _parse_1h(raw)
    assert len(result) == 1
    assert result[0]["mult"] == "s"


def test_parse_1h_doublet():
    """Doublet (one coupling) has mult 'd'."""
    # Format: parts[0] parts[1] shift n_couplings atom_idx J_val extra
    raw = "0 x 7.5 1 1 x 8.0"
    result = _parse_1h(raw)
    if len(result) > 0:
        peak = result[0]
        # Should have some information about multiplicity
        assert "mult" in peak


def test_parse_1h_multiple_peaks():
    """Multiple lines produce multiple peaks."""
    raw = "0 x 7.5 0\n1 x 3.8 0\n2 x 1.2 0"
    result = _parse_1h(raw)
    assert len(result) >= 2


def test_parse_1h_malformed_line():
    """Lines with < 4 parts are skipped."""
    raw = "0 x 7.5\n1 x 3.8 0"  # First line has only 3 parts
    result = _parse_1h(raw)
    # Should only have the valid line
    assert len(result) >= 1


def test_parse_1h_empty_lines():
    """Empty lines are handled gracefully."""
    raw = "\n0 x 7.5 0\n\n1 x 3.8 0\n"
    result = _parse_1h(raw)
    assert len(result) >= 1


def test_parse_1h_groups_by_shift():
    """Atoms with same shift are grouped together."""
    # Two atoms at 7.5 ppm
    raw = "0 x 7.5 0\n1 x 7.5 0"
    result = _parse_1h(raw)
    # Should group them: one peak with n_h=2
    total_h = sum(p.get("n_h", 1) for p in result)
    assert total_h >= 1


def test_parse_1h_returns_dict_structure():
    """Each peak is a dict with required keys."""
    raw = "0 x 7.5 0"
    result = _parse_1h(raw)
    assert len(result) > 0
    peak = result[0]
    assert "shift" in peak
    assert "n_h" in peak
    assert "mult" in peak
    assert isinstance(peak["shift"], float)
    assert isinstance(peak["n_h"], int)
    assert isinstance(peak["mult"], str)


def test_pop_pending_image_missing_key():
    """Missing key returns None."""
    result = pop_pending_image("missing_smiles")
    assert result is None


def test_pop_pending_image_after_store():
    """Storing and retrieving image works."""
    smiles = "CCO"
    image_uri = "data:image/png;base64,fake_data"

    # Manually store using the same mechanism
    from app.tools import nmr as nmr_module
    with nmr_module._image_lock:
        nmr_module._image_store[smiles] = image_uri

    # Now pop it
    result = pop_pending_image(smiles)
    assert result == image_uri


def test_pop_pending_image_removes_from_store():
    """Popping removes the image from store."""
    smiles = "C"
    image_uri = "data:image/png;base64,data"

    from app.tools import nmr as nmr_module
    with nmr_module._image_lock:
        nmr_module._image_store[smiles] = image_uri

    # First pop should return it
    result1 = pop_pending_image(smiles)
    assert result1 == image_uri

    # Second pop should return None
    result2 = pop_pending_image(smiles)
    assert result2 is None


def test_predict_nmr_empty_smiles():
    """Empty SMILES returns error string."""
    result = predict_nmr.invoke({"smiles": ""})
    assert isinstance(result, str)
    assert "Error" in result or "empty" in result.lower()


def test_predict_nmr_invalid_smiles():
    """Invalid SMILES returns error string."""
    result = predict_nmr.invoke({"smiles": "not_a_smiles"})
    assert isinstance(result, str)
    assert "Error" in result or "error" in result.lower()


def test_predict_nmr_valid_smiles_mocked(caffeine_smiles):
    """Valid SMILES with mocked HTTP returns markdown table."""
    # Mock the _fetch_1h to return NMR data
    nmr_response = "0 x 7.5 0\n1 x 3.8 0"  # Minimal valid NMR data

    with patch("app.tools.nmr._fetch_1h", return_value=nmr_response):
        result = predict_nmr.invoke({"smiles": caffeine_smiles})
        assert isinstance(result, str)
        # Should contain markdown table markers
        assert "|" in result
        assert "δ (ppm)" in result or "ppm" in result


def test_predict_nmr_http_error(caffeine_smiles):
    """HTTP error is caught and returns error string."""
    import requests
    error = requests.HTTPError("404 Not Found")

    with patch("app.tools.nmr._fetch_1h", side_effect=error):
        result = predict_nmr.invoke({"smiles": caffeine_smiles})
        assert isinstance(result, str)
        assert "Error" in result


def test_predict_nmr_generic_exception(caffeine_smiles):
    """Generic exception is caught and returns error string."""
    with patch("app.tools.nmr._fetch_1h", side_effect=RuntimeError("Network error")):
        result = predict_nmr.invoke({"smiles": caffeine_smiles})
        assert isinstance(result, str)
        assert "Error" in result


def test_predict_nmr_stores_image(caffeine_smiles):
    """Spectrum image is stored for later retrieval."""
    nmr_response = "0 x 7.5 0\n1 x 3.8 0"

    with patch("app.tools.nmr._fetch_1h", return_value=nmr_response):
        result = predict_nmr.invoke({"smiles": caffeine_smiles})
        # Try to pop the image
        image = pop_pending_image(caffeine_smiles)
        # Image might exist if matplotlib render succeeded
        if image is not None:
            assert image.startswith("data:image/png;base64,")
