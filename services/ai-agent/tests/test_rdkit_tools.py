from app.tools.rdkit_tools import func_groups, mol_similarity, smiles2weight


def test_smiles2weight(caffeine_smiles):
    result = smiles2weight.invoke(caffeine_smiles)
    mw = float(result)
    assert abs(mw - 194.0) < 1.0


def test_smiles2weight_invalid():
    result = smiles2weight.invoke("invalid_smiles_xxx")
    assert result == "Invalid SMILES string"


def test_mol_similarity_dissimilar():
    result = mol_similarity.invoke({
        "smiles1": "O=C1N(C)C(C2=C(N=CN2C)N1C)=O",
        "smiles2": "CC(C)c1ccccc1",
    })
    assert "not similar" in result.lower()


def test_mol_similarity_similar():
    result = mol_similarity.invoke({
        "smiles1": "O=C1N(C)C(C2=C(N=CN2C)N1C)=O",
        "smiles2": "O=C1N(C)C(C2=C(N=CN2C)N1CCC)=O",
    })
    assert "similar" in result.lower()


def test_mol_similarity_identical(caffeine_smiles):
    result = mol_similarity.invoke({
        "smiles1": caffeine_smiles,
        "smiles2": caffeine_smiles,
    })
    assert "Identical" in result


def test_func_groups(caffeine_smiles):
    result = func_groups.invoke(caffeine_smiles)
    assert "ketones" in result.lower()


def test_func_groups_invalid():
    result = func_groups.invoke("not_a_smiles")
    assert "Wrong argument" in result
