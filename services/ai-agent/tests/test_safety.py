from unittest.mock import MagicMock, patch

from app.tools.safety import (
    control_chem_check,
    explosive_check,
    similar_control_chem_check,
)


def test_control_chem_check_controlled_cas():
    result = control_chem_check.invoke("10025-87-3")
    assert "appears in a list" in result


def test_control_chem_check_controlled_smiles():
    result = control_chem_check.invoke("O=P(Cl)(Cl)Cl")
    assert "appears in a list" in result


def test_control_chem_check_safe_smiles():
    result = control_chem_check.invoke("CC(=O)C")  # acetone
    assert "appears in a list" not in result


def test_similar_control_chem_check_safe(acetone_smiles):
    result = similar_control_chem_check.invoke(acetone_smiles)
    assert "similarity" in result


def test_similar_control_chem_check_invalid():
    result = similar_control_chem_check.invoke("not_a_smiles")
    assert "valid SMILES" in result


@patch("app.tools.safety.requests.get")
def test_explosive_check_tnt(mock_get):
    # Mock PubChem CID lookup
    mock_cid_resp = MagicMock()
    mock_cid_resp.json.return_value = {"IdentifierList": {"CID": [8376]}}

    # Mock PubChem compound data with explosive GHS
    mock_data_resp = MagicMock()
    mock_data_resp.json.return_value = {
        "Record": {
            "Section": [
                {
                    "TOCHeading": "Chemical Safety",
                    "Information": [
                        {
                            "Value": {
                                "StringWithMarkup": [
                                    {
                                        "Markup": [
                                            {"Extra": "Explosive"},
                                            {"Extra": "Flammable"},
                                        ]
                                    }
                                ]
                            }
                        }
                    ],
                }
            ]
        }
    }
    mock_get.side_effect = [mock_cid_resp, mock_data_resp]

    result = explosive_check.invoke("118-96-7")
    assert result == "Molecule is explosive"


@patch("app.tools.safety.requests.get")
def test_explosive_check_nonexplosive(mock_get):
    mock_cid_resp = MagicMock()
    mock_cid_resp.json.return_value = {"IdentifierList": {"CID": [24813]}}

    mock_data_resp = MagicMock()
    mock_data_resp.json.return_value = {
        "Record": {
            "Section": [
                {
                    "TOCHeading": "Chemical Safety",
                    "Information": [
                        {
                            "Value": {
                                "StringWithMarkup": [
                                    {
                                        "Markup": [
                                            {"Extra": "Corrosive"},
                                            {"Extra": "Acute Toxic"},
                                        ]
                                    }
                                ]
                            }
                        }
                    ],
                }
            ]
        }
    }
    mock_get.side_effect = [mock_cid_resp, mock_data_resp]

    result = explosive_check.invoke("10025-87-3")
    assert result == "Molecule is not known to be explosive"


def test_explosive_check_smiles_rejected():
    result = explosive_check.invoke("CC(=O)C")
    assert "valid CAS number" in result
