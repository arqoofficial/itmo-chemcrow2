from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _make_s2_paper(title="Test Paper", doi="10.1234/test"):
    return {
        "title": title,
        "authors": [{"name": "Alice"}, {"name": "Bob"}],
        "abstract": "A test abstract.",
        "year": 2024,
        "citationCount": 10,
        "url": "https://semanticscholar.org/paper/abc",
        "externalIds": {"DOI": doi},
    }


def test_s2_search_returns_papers():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [_make_s2_paper()]}

    with patch("app.main.requests.get", return_value=mock_resp):
        resp = client.post("/internal/s2-search", json={"query": "aspirin synthesis", "max_results": 3})

    assert resp.status_code == 200
    body = resp.json()
    assert "papers" in body
    assert len(body["papers"]) == 1
    assert body["papers"][0]["title"] == "Test Paper"
    assert body["papers"][0]["doi"] == "10.1234/test"


def test_s2_search_empty_returns_empty_list():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}

    with patch("app.main.requests.get", return_value=mock_resp):
        resp = client.post("/internal/s2-search", json={"query": "nonexistent", "max_results": 5})

    assert resp.status_code == 200
    assert resp.json()["papers"] == []


def test_s2_search_retries_on_429():
    """Endpoint retries when S2 returns 429, then returns papers on success."""
    rate_limited = MagicMock()
    rate_limited.status_code = 429

    success = MagicMock()
    success.status_code = 200
    success.json.return_value = {"data": [_make_s2_paper()]}

    with patch("app.main.requests.get", side_effect=[rate_limited, success]), \
         patch("time.sleep"):  # don't actually sleep in tests
        resp = client.post("/internal/s2-search", json={"query": "aspirin", "max_results": 3})

    assert resp.status_code == 200
    assert len(resp.json()["papers"]) == 1


def test_s2_search_response_has_required_fields():
    """Each paper in response must have all required fields."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [_make_s2_paper()]}

    with patch("app.main.requests.get", return_value=mock_resp):
        resp = client.post("/internal/s2-search", json={"query": "test", "max_results": 1})

    paper = resp.json()["papers"][0]
    for field in ("title", "authors", "year", "doi", "abstract", "citation_count", "url"):
        assert field in paper, f"Missing field: {field}"
