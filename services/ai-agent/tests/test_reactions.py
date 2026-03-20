from unittest.mock import MagicMock, patch

from app.tools.reactions import reaction_predict, reaction_retrosynthesis


@patch("app.tools.reactions.requests.post")
def test_reaction_predict_valid(mock_post):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"product": ["CCO"]}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    result = reaction_predict.invoke("CC=O.[H][H]")
    assert result == "CCO"


@patch("app.tools.reactions.requests.post")
def test_reaction_predict_invalid(mock_post):
    result = reaction_predict.invoke("not_smiles")
    assert "Incorrect input" in result
    mock_post.assert_not_called()


@patch("app.tools.reactions.requests.post")
def test_retrosynthesis_valid(mock_post):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {
            "metadata": {"mapped_reaction_smiles": "CCO>>CC=O.O"},
            "children": [],
        }
    ]
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    result = reaction_retrosynthesis.invoke("CCO")
    assert isinstance(result, str)
    assert len(result) > 0
