import pytest


@pytest.fixture
def caffeine_smiles():
    """Caffeine SMILES."""
    return "O=C1N(C)C(C2=C(N=CN2C)N1C)=O"


@pytest.fixture
def caffeine_cas():
    return "58-08-2"


@pytest.fixture
def acetone_smiles():
    return "CC(=O)C"


@pytest.fixture
def ibuprofen_smiles():
    return "CC(C)Cc1ccc(cc1)C(C)C(=O)O"


@pytest.fixture
def molpair_dissimilar():
    """Caffeine + cumene — dissimilar pair."""
    return "O=C1N(C)C(C2=C(N=CN2C)N1C)=O.CC(C)c1ccccc1"


@pytest.fixture
def molpair_similar():
    """Caffeine + caffeine analog — similar pair."""
    return "O=C1N(C)C(C2=C(N=CN2C)N1C)=O.O=C1N(C)C(C2=C(N=CN2C)N1CCC)=O"


@pytest.fixture
def iupac_name():
    return "4-(4-hydroxyphenyl)butan-2-one"
