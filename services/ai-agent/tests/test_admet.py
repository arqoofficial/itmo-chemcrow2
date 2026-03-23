"""Tests for ADMET prediction tool."""
from app.tools.admet import (
    _bucket,
    _clip01,
    _has_substructure,
    _lipinski_violations,
    _predict_admet,
    smiles_to_admet,
)
import json
import pytest
from rdkit import Chem


def test_clip01_valid():
    assert _clip01(0.5) == 0.5
    assert _clip01(0.333) == 0.333
    assert _clip01(0.999) == 0.999


def test_clip01_below_zero():
    assert _clip01(-0.5) == 0.0


def test_clip01_above_one():
    assert _clip01(1.5) == 1.0


def test_clip01_exactly_zero():
    assert _clip01(0.0) == 0.0


def test_clip01_exactly_one():
    assert _clip01(1.0) == 1.0


def test_bucket_low():
    assert _bucket(0.1) == "low"
    assert _bucket(0.34) == "low"


def test_bucket_medium():
    assert _bucket(0.5) == "medium"


def test_bucket_high():
    assert _bucket(0.67) == "high"
    assert _bucket(0.99) == "high"


def test_lipinski_violations_compliant():
    """Caffeine-like small molecule."""
    desc = {
        "MolWt": 194.0,
        "MolLogP": 0.2,
        "HBD": 1,
        "HBA": 4,
    }
    assert _lipinski_violations(desc) == 0


def test_lipinski_violations_high_mw():
    """Molecule exceeds molecular weight limit (500)."""
    desc = {
        "MolWt": 550.0,
        "MolLogP": 2.0,
        "HBD": 1,
        "HBA": 5,
    }
    assert _lipinski_violations(desc) >= 1


def test_lipinski_violations_high_logp():
    """Molecule exceeds logP limit (5)."""
    desc = {
        "MolWt": 300.0,
        "MolLogP": 6.0,
        "HBD": 1,
        "HBA": 5,
    }
    assert _lipinski_violations(desc) >= 1


def test_has_substructure_nitro(caffeine_smiles):
    """Caffeine does not have nitro group."""
    mol = Chem.MolFromSmiles(caffeine_smiles)
    from app.tools.admet import _NITRO_RE
    assert _has_substructure(mol, _NITRO_RE) is False


def test_has_substructure_none_pattern():
    """None pattern always returns False."""
    mol = Chem.MolFromSmiles("C")
    assert _has_substructure(mol, None) is False


def test_predict_admet_valid_smiles(caffeine_smiles):
    """Valid SMILES returns complete dict."""
    result = _predict_admet(caffeine_smiles)
    assert isinstance(result, dict)
    assert "canonical_smiles" in result
    assert "descriptors" in result
    assert "admet" in result
    assert "warnings" in result
    assert "lipinski_violations" in result
    assert "feature_flags" in result


def test_predict_admet_empty_smiles():
    """Empty SMILES raises ValueError."""
    with pytest.raises(ValueError, match="empty"):
        _predict_admet("")


def test_predict_admet_invalid_smiles():
    """Invalid SMILES raises ValueError."""
    with pytest.raises(ValueError, match="Wrong SMILES"):
        _predict_admet("invalid_molecule")


def test_predict_admet_mixture_smiles():
    """Mixture SMILES (with '.') raises ValueError."""
    with pytest.raises(ValueError, match="single molecule"):
        _predict_admet("CC.CC")


def test_predict_admet_reaction_smiles():
    """Reaction SMILES (with '>') raises ValueError."""
    with pytest.raises(ValueError, match="single molecule"):
        _predict_admet("C>CC")


def test_predict_admet_too_long():
    """Overly long SMILES raises ValueError."""
    with pytest.raises(ValueError, match="too long"):
        _predict_admet("C" * 5001)


def test_predict_admet_too_many_atoms():
    """Molecule with >200 heavy atoms raises ValueError."""
    # Create a long carbon chain with 250 atoms
    long_chain = "C" * 250
    with pytest.raises(ValueError, match="Too many heavy atoms"):
        _predict_admet(long_chain)


def test_predict_admet_descriptors_are_correct_type(caffeine_smiles):
    """Descriptors dict has correct types."""
    result = _predict_admet(caffeine_smiles)
    desc = result["descriptors"]
    assert isinstance(desc["MolWt"], float)
    assert isinstance(desc["HBD"], int)
    assert isinstance(desc["HBA"], int)
    assert 0 <= desc["MolWt"] <= 1000


def test_smiles_to_admet_valid(caffeine_smiles):
    """Valid SMILES returns JSON string."""
    result = smiles_to_admet.invoke({"smiles": caffeine_smiles})
    assert isinstance(result, str)
    # Should be valid JSON
    data = json.loads(result)
    assert "canonical_smiles" in data


def test_smiles_to_admet_invalid():
    """Invalid SMILES returns error string."""
    result = smiles_to_admet.invoke({"smiles": "invalid"})
    assert result.startswith("Error:")


def test_smiles_to_admet_empty():
    """Empty SMILES returns error string."""
    result = smiles_to_admet.invoke({"smiles": ""})
    assert result.startswith("Error:")


def test_smiles_to_admet_mixture():
    """Mixture SMILES returns error string."""
    result = smiles_to_admet.invoke({"smiles": "CC.CC"})
    assert result.startswith("Error:")
