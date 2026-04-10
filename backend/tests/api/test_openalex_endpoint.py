"""Direct tests for /internal/openalex-search endpoint.

CRITICAL TEST GAP: This endpoint was untested. These tests verify:
1. Valid OpenAlex response parsing
2. Missing abstract/authors handling
3. Timeout behavior
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def valid_openalex_response():
    """Realistic OpenAlex API response with multiple papers."""
    return {
        "results": [
            {
                "id": "https://openalex.org/W123456789",
                "title": "Green Chemistry Methods for Sustainable Synthesis",
                "publication_year": 2023,
                "doi": "10.1234/gcm.2023",
                "abstract": "This study presents novel environmentally-friendly synthetic routes using catalytic methods and renewable feedstocks.",
                "cited_by_count": 45,
                "authorships": [
                    {
                        "author": {"display_name": "Alice Johnson"},
                        "institutions": [{"display_name": "MIT"}],
                    },
                    {
                        "author": {"display_name": "Bob Smith"},
                        "institutions": [{"display_name": "Stanford"}],
                    },
                ],
            },
            {
                "id": "https://openalex.org/W987654321",
                "title": "Machine Learning in Drug Discovery",
                "publication_year": 2022,
                "doi": "10.5678/mldd.2022",
                "abstract": "We present a deep learning approach for predicting molecular properties.",
                "cited_by_count": 120,
                "authorships": [
                    {
                        "author": {"display_name": "Carol White"},
                        "institutions": [{"display_name": "Harvard"}],
                    },
                ],
            },
        ]
    }


def test_openalex_search_valid_response(client, valid_openalex_response):
    """Test valid OpenAlex response parsing."""
    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = valid_openalex_response
        mock_get.return_value = mock_response

        resp = client.post(
            "/internal/openalex-search",
            json={"query": "green chemistry", "max_results": 10},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "papers" in data
    assert len(data["papers"]) == 2

    # Verify first paper
    paper1 = data["papers"][0]
    assert paper1["title"] == "Green Chemistry Methods for Sustainable Synthesis"
    assert paper1["doi"] == "10.1234/gcm.2023"
    assert paper1["year"] == 2023
    assert "Alice Johnson" in paper1["authors"]
    assert "Bob Smith" in paper1["authors"]
    assert paper1["citation_count"] == 45
    assert "environmentally-friendly" in paper1["abstract"]

    # Verify second paper
    paper2 = data["papers"][1]
    assert paper2["title"] == "Machine Learning in Drug Discovery"
    assert paper2["citation_count"] == 120


def test_openalex_search_missing_abstract(client):
    """Test handling of papers with missing abstract."""
    response = {
        "results": [
            {
                "id": "https://openalex.org/W111",
                "title": "Paper Without Abstract",
                "publication_year": 2023,
                "doi": "10.1111/test.2023",
                "abstract": None,  # Missing abstract
                "cited_by_count": 5,
                "authorships": [
                    {"author": {"display_name": "Author One"}},
                ],
            },
        ]
    }

    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = response
        mock_get.return_value = mock_response

        resp = client.post(
            "/internal/openalex-search",
            json={"query": "test", "max_results": 5},
        )

    assert resp.status_code == 200
    paper = resp.json()["papers"][0]
    assert paper["abstract"] == ""  # Should be empty string, not None


def test_openalex_search_missing_authors(client):
    """Test handling of papers with no authorships."""
    response = {
        "results": [
            {
                "id": "https://openalex.org/W222",
                "title": "Anonymous Paper",
                "publication_year": 2023,
                "doi": "10.2222/anon.2023",
                "abstract": "Some abstract",
                "cited_by_count": 10,
                "authorships": [],  # Empty authorships
            },
        ]
    }

    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = response
        mock_get.return_value = mock_response

        resp = client.post(
            "/internal/openalex-search",
            json={"query": "test", "max_results": 5},
        )

    assert resp.status_code == 200
    paper = resp.json()["papers"][0]
    assert paper["authors"] == "Unknown"


def test_openalex_search_missing_doi(client):
    """Test handling of papers without DOI."""
    response = {
        "results": [
            {
                "id": "https://openalex.org/W333",
                "title": "No DOI Paper",
                "publication_year": 2023,
                "doi": None,  # Missing DOI
                "abstract": "Some abstract",
                "cited_by_count": 3,
                "authorships": [
                    {"author": {"display_name": "Test Author"}},
                ],
            },
        ]
    }

    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = response
        mock_get.return_value = mock_response

        resp = client.post(
            "/internal/openalex-search",
            json={"query": "test", "max_results": 5},
        )

    assert resp.status_code == 200
    paper = resp.json()["papers"][0]
    assert paper["doi"] is None


def test_openalex_search_missing_year(client):
    """Test handling of papers without publication year."""
    response = {
        "results": [
            {
                "id": "https://openalex.org/W444",
                "title": "Undated Paper",
                "publication_year": None,
                "doi": "10.4444/undated.year",
                "abstract": "Abstract",
                "cited_by_count": 2,
                "authorships": [
                    {"author": {"display_name": "Author"}},
                ],
            },
        ]
    }

    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = response
        mock_get.return_value = mock_response

        resp = client.post(
            "/internal/openalex-search",
            json={"query": "test", "max_results": 5},
        )

    assert resp.status_code == 200
    paper = resp.json()["papers"][0]
    # Year defaults to "N/A" if None, or None if API doesn't provide it
    assert paper["year"] in ("N/A", None)


def test_openalex_search_empty_results(client):
    """Test API returning no results."""
    response = {"results": []}

    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = response
        mock_get.return_value = mock_response

        resp = client.post(
            "/internal/openalex-search",
            json={"query": "nonexistent topic xyz", "max_results": 5},
        )

    assert resp.status_code == 200
    assert resp.json()["papers"] == []


def test_openalex_search_timeout(client):
    """Test timeout behavior when OpenAlex API is slow."""
    with patch("httpx.get") as mock_get:
        import httpx
        mock_get.side_effect = httpx.TimeoutException("Request timeout")

        resp = client.post(
            "/internal/openalex-search",
            json={"query": "test", "max_results": 5},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["papers"] == []
    assert "error" in data
    assert "timeout" in data["error"].lower() or "connection" in data["error"].lower()


def test_openalex_search_http_error(client):
    """Test HTTP error handling (429, 503, etc)."""
    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("429 Too Many Requests")
        mock_get.return_value = mock_response

        resp = client.post(
            "/internal/openalex-search",
            json={"query": "test", "max_results": 5},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["papers"] == []
    assert "error" in data


def test_openalex_search_api_key_missing(client):
    """Test behavior when API key is not configured."""
    from app.core import config

    with patch.object(config.settings, "OPENALEX_API_KEY", ""):
        resp = client.post(
            "/internal/openalex-search",
            json={"query": "test", "max_results": 5},
        )

    assert resp.status_code == 200
    assert resp.json()["papers"] == []


def test_openalex_search_multiple_authors(client):
    """Test paper with multiple authors is formatted correctly."""
    response = {
        "results": [
            {
                "id": "https://openalex.org/W555",
                "title": "Multi-Author Paper",
                "publication_year": 2023,
                "doi": "10.5555/multi.2023",
                "abstract": "A collaborative work",
                "cited_by_count": 15,
                "authorships": [
                    {"author": {"display_name": "First Author"}},
                    {"author": {"display_name": "Second Author"}},
                    {"author": {"display_name": "Third Author"}},
                ],
            },
        ]
    }

    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = response
        mock_get.return_value = mock_response

        resp = client.post(
            "/internal/openalex-search",
            json={"query": "collaboration", "max_results": 5},
        )

    assert resp.status_code == 200
    paper = resp.json()["papers"][0]
    authors = paper["authors"]
    assert "First Author" in authors
    assert "Second Author" in authors
    assert "Third Author" in authors


def test_openalex_search_respects_max_results(client):
    """Test that only requested max_results are returned."""
    response = {
        "results": [
            {
                "id": f"https://openalex.org/W{i}",
                "title": f"Paper {i}",
                "publication_year": 2023,
                "doi": f"10.{i}/paper.2023",
                "abstract": "Abstract",
                "cited_by_count": i,
                "authorships": [{"author": {"display_name": "Author"}}],
            }
            for i in range(1, 11)  # 10 papers
        ]
    }

    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = response
        mock_get.return_value = mock_response

        # Request only 3 papers
        resp = client.post(
            "/internal/openalex-search",
            json={"query": "test", "max_results": 3},
        )

    # Note: This test verifies the endpoint passes max_results to API
    # The API response filtering is on the OpenAlex API side
    assert resp.status_code == 200

    # Verify correct params were passed to OpenAlex API
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["params"]["per_page"] == 3
