from unittest.mock import MagicMock, patch

from app.tools.converters import query2cas_tool, query2smiles_tool, smiles2name_tool


@patch("app.tools.utils.requests.get")
def test_query2smiles_name(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "PropertyTable": {
            "Properties": [{"IsomericSMILES": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"}]
        }
    }
    mock_get.return_value = mock_resp

    result = query2smiles_tool.invoke("caffeine")
    assert "n" in result.lower()  # caffeine SMILES contains nitrogen


def test_query2smiles_passthrough(caffeine_smiles):
    # Valid SMILES should pass through without API call
    result = query2smiles_tool.invoke(caffeine_smiles)
    assert result == caffeine_smiles


def test_query2smiles_multiple(molpair_dissimilar):
    result = query2smiles_tool.invoke(molpair_dissimilar)
    assert "one molecule at a time" in result


@patch("app.tools.utils.requests.get")
def test_query2cas_smiles(mock_get):
    mock_cid_resp = MagicMock()
    mock_cid_resp.json.return_value = {"IdentifierList": {"CID": [2519]}}

    mock_data_resp = MagicMock()
    mock_data_resp.json.return_value = {
        "Record": {
            "Section": [
                {
                    "TOCHeading": "Names and Identifiers",
                    "Section": [
                        {
                            "TOCHeading": "Other Identifiers",
                            "Section": [
                                {
                                    "TOCHeading": "CAS",
                                    "Information": [
                                        {
                                            "Value": {
                                                "StringWithMarkup": [
                                                    {"String": "58-08-2"}
                                                ]
                                            }
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }
    mock_get.side_effect = [mock_cid_resp, mock_data_resp]

    result = query2cas_tool.invoke("CN1C=NC2=C1C(=O)N(C(=O)N2C)C")
    assert result == "58-08-2"


@patch("app.tools.utils.requests.get")
def test_query2cas_invalid(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.side_effect = KeyError("IdentifierList")
    mock_get.return_value = mock_resp

    result = query2cas_tool.invoke("nomol")
    assert "no Pubchem" in result.lower() or "invalid" in result.lower()


@patch("app.tools.utils.requests.get")
def test_smiles2name_caffeine(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "InformationList": {
            "Information": [{"Synonym": ["caffeine", "58-08-2", "1,3,7-trimethylxanthine"]}]
        }
    }
    mock_get.return_value = mock_resp

    result = smiles2name_tool.invoke("CN1C=NC2=C1C(=O)N(C(=O)N2C)C")
    assert "caffeine" in result.lower()


def test_smiles2name_invalid():
    result = smiles2name_tool.invoke("nonsense")
    assert "Error" in result
