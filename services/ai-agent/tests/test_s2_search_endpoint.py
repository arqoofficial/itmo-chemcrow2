import requests as requests_lib
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
         patch("app.main.time.sleep"):  # don't actually sleep in tests
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


# Use a client that does NOT re-raise server exceptions — we want the HTTP 500 response
_error_client = TestClient(app, raise_server_exceptions=False)


def test_s2_search_500_propagates_as_error():
    """S2 returns 500 → raise_for_status raises → FastAPI endpoint returns 500."""
    error_resp = MagicMock()
    error_resp.status_code = 500
    error_resp.raise_for_status.side_effect = requests_lib.HTTPError("500 Server Error")

    with patch("app.main.requests.get", return_value=error_resp):
        resp = _error_client.post("/internal/s2-search", json={"query": "aspirin", "max_results": 3})

    assert resp.status_code == 500


def test_s2_search_403_propagates_as_error():
    """S2 returns 403 (bad API key) → raise_for_status raises → FastAPI endpoint returns 500."""
    error_resp = MagicMock()
    error_resp.status_code = 403
    error_resp.raise_for_status.side_effect = requests_lib.HTTPError("403 Forbidden")

    with patch("app.main.requests.get", return_value=error_resp):
        resp = _error_client.post("/internal/s2-search", json={"query": "aspirin", "max_results": 3})

    assert resp.status_code == 500


def test_s2_search_all_retries_exhausted_returns_error():
    """All 5 retry attempts return 429 (no API key path) → raise_for_status on last → 500."""
    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.raise_for_status.side_effect = requests_lib.HTTPError("429 Too Many Requests")

    # retry_waits=[5,10,20,30,60] → 5 attempts when no API key
    with patch("app.main.requests.get", return_value=rate_limited), \
         patch("app.main.time.sleep"):
        resp = _error_client.post("/internal/s2-search", json={"query": "aspirin", "max_results": 3})

    assert resp.status_code == 500
