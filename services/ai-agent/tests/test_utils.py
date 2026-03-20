from app.tools.utils import (
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
