# Literature Search DOI Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich `literature_search` tool output with DOI by (1) requesting `externalIds` from the Semantic Scholar API and (2) falling back to HTML scraping of the paper URL when the API does not provide one.

**Architecture:** Two-stage DOI resolution. First, add `externalIds` to the S2 API request — this gives DOI for the majority of papers with zero extra HTTP calls. For papers still missing a DOI, fetch the paper's HTML page and extract the DOI from standard metadata patterns (`citation_doi` meta tag, `doi.org` link, bare DOI pattern). The DOI is appended to each paper entry in the tool output.

**Tech Stack:** Python stdlib `re`, `requests` (already a dependency), Semantic Scholar Graph API v1.

---

## File Map

| File | Change |
|------|--------|
| `services/ai-agent/app/tools/utils.py` | Add `import re`; add `_DOI_RE` constant and `_scrape_doi_from_url()` helper — kept here (not in `search.py`) so the future article-download pipeline can reuse it without importing search logic |
| `services/ai-agent/app/tools/search.py` | Import `_scrape_doi_from_url` from `utils`; update API `fields` param; add DOI resolution logic; include DOI in output |
| `services/ai-agent/tests/test_search.py` | Fix existing mock to avoid regression; add tests for `_scrape_doi_from_url` and updated `literature_search` output |

---

### Task 1: Add DOI scraping helper with tests

**Files:**
- Modify: `services/ai-agent/app/tools/utils.py`
- Modify: `services/ai-agent/tests/test_search.py`

- [ ] **Step 1: Write the failing tests for `_scrape_doi_from_url`**

Add these tests to `services/ai-agent/tests/test_search.py`:

```python
from app.tools.utils import _scrape_doi_from_url


@patch("app.tools.utils.requests.get")
def test_scrape_doi_citation_meta_tag(mock_get):
    """Extracts DOI from citation_doi meta tag (content before name attr)."""
    mock_get.return_value = MagicMock(
        ok=True,
        text='<html><meta name="citation_doi" content="10.1234/test.paper"/></html>',
    )
    assert _scrape_doi_from_url("https://example.com/paper") == "10.1234/test.paper"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_citation_meta_tag_reversed(mock_get):
    """Extracts DOI from citation_doi meta tag (name before content attr)."""
    mock_get.return_value = MagicMock(
        ok=True,
        text='<meta content="10.1234/reversed.paper" name="citation_doi"/>',
    )
    assert _scrape_doi_from_url("https://example.com/paper") == "10.1234/reversed.paper"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_citation_meta_tag_wins_over_doi_org(mock_get):
    """citation_doi meta tag takes priority over doi.org link."""
    mock_get.return_value = MagicMock(
        ok=True,
        text=(
            '<meta name="citation_doi" content="10.1111/priority"/>'
            '<a href="https://doi.org/10.2222/secondary">link</a>'
        ),
    )
    assert _scrape_doi_from_url("https://example.com/paper") == "10.1111/priority"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_doi_org_link(mock_get):
    """Extracts DOI from a doi.org hyperlink when no meta tag present."""
    mock_get.return_value = MagicMock(
        ok=True,
        text='<a href="https://doi.org/10.5678/another.paper">Full text</a>',
    )
    assert _scrape_doi_from_url("https://example.com/paper") == "10.5678/another.paper"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_bare_pattern(mock_get):
    """Extracts DOI from bare DOI pattern when no meta tag or doi.org link present."""
    mock_get.return_value = MagicMock(
        ok=True,
        text="See DOI: 10.9999/bare.doi.here for details",
    )
    assert _scrape_doi_from_url("https://example.com/paper") == "10.9999/bare.doi.here"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_strips_trailing_punctuation(mock_get):
    """Trailing punctuation (period, comma) is stripped from bare DOI matches."""
    mock_get.return_value = MagicMock(
        ok=True,
        text="Reference: 10.9999/doi.with.trailing.",
    )
    doi = _scrape_doi_from_url("https://example.com/paper")
    assert doi == "10.9999/doi.with.trailing"


@patch("app.tools.utils.requests.get")
def test_scrape_doi_not_found(mock_get):
    """Returns None when no DOI is present."""
    mock_get.return_value = MagicMock(ok=True, text="<html>No DOI here</html>")
    assert _scrape_doi_from_url("https://example.com/paper") is None


@patch("app.tools.utils.requests.get")
def test_scrape_doi_http_error(mock_get):
    """Returns None on non-OK HTTP response."""
    mock_get.return_value = MagicMock(ok=False)
    assert _scrape_doi_from_url("https://example.com/paper") is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd services/ai-agent
uv run pytest tests/test_search.py::test_scrape_doi_citation_meta_tag -v
```
Expected: `ImportError` — `_scrape_doi_from_url` does not exist yet.

- [ ] **Step 3: Implement `_scrape_doi_from_url` in `utils.py`**

Add `import re` and `import logging` to `app/tools/utils.py` imports if not already present.

Add a `logger = logging.getLogger(__name__)` line if not already present.

Add the `_DOI_RE` constant and `_scrape_doi_from_url` function at the bottom of `utils.py`:

```python
# Matches bare DOI strings, e.g. 10.1234/something
# Trailing punctuation characters are stripped separately after matching.
_DOI_RE = re.compile(r'\b(10\.\d{4,}/[^\s"\'<>]+)')


def _scrape_doi_from_url(url: str) -> str | None:
    """Fetch an article page and extract its DOI.

    Tries (in order):
    1. ``<meta name="citation_doi">`` tag — used by most publishers
    2. ``doi.org`` hyperlink anywhere in the page
    3. Any bare DOI pattern (``10.xxxx/...``) in the HTML
    """
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if not resp.ok:
            return None
        html = resp.text

        # citation_doi meta tag — content attr can appear before or after name attr
        for pattern in (
            r'<meta[^>]+name=["\']citation_doi["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_doi["\']',
        ):
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                return m.group(1).strip()

        # doi.org hyperlink
        m = re.search(r'https?://doi\.org/(10\.\d{4,}/[^\s"\'<>]+)', html)
        if m:
            return m.group(1).strip()

        # Bare DOI anywhere in the page; strip trailing punctuation
        m = _DOI_RE.search(html)
        if m:
            return m.group(1).rstrip(".,;)")

    except Exception:
        logger.exception("DOI scraping failed for %s", url)
    return None
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd services/ai-agent
uv run pytest tests/test_search.py::test_scrape_doi_citation_meta_tag tests/test_search.py::test_scrape_doi_citation_meta_tag_reversed tests/test_search.py::test_scrape_doi_citation_meta_tag_wins_over_doi_org tests/test_search.py::test_scrape_doi_doi_org_link tests/test_search.py::test_scrape_doi_bare_pattern tests/test_search.py::test_scrape_doi_strips_trailing_punctuation tests/test_search.py::test_scrape_doi_not_found tests/test_search.py::test_scrape_doi_http_error -v
```
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add services/ai-agent/app/tools/search.py services/ai-agent/tests/test_search.py
git commit -m "feat(search): add _scrape_doi_from_url helper with tests"
```

---

### Task 2: Integrate DOI into `literature_search` output

**Files:**
- Modify: `services/ai-agent/app/tools/search.py`
- Modify: `services/ai-agent/tests/test_search.py`

- [ ] **Step 1: Fix the existing `test_literature_search` to prevent regression crash**

The existing mock does not set `externalIds` or `status_code`. After the implementation change, the code will call `_scrape_doi_from_url` on the mock URL, which triggers a second `requests.get`. Because `mock_get.return_value` is set, the second call returns the same mock object — but `resp.text` is a `MagicMock`, not a string, causing `re.search` to raise `TypeError`.

**Required fix**: add `"externalIds": {"DOI": "10.0000/mock.doi"}` and `"status_code": 200` to the existing mock paper dict in `test_literature_search`:

```python
# In the existing test_literature_search mock, change:
mock_resp.json.return_value = {
    "data": [
        {
            "title": "Caffeine and Health",
            "authors": [{"name": "Smith J"}],
            "abstract": "A review of caffeine effects.",
            "year": 2023,
            "citationCount": 42,
            "url": "https://example.com/paper",
            "externalIds": {"DOI": "10.0000/mock.doi"},  # added
        }
    ]
}
mock_resp.status_code = 200  # added
```

Run the existing test to confirm it still passes before proceeding:

```bash
cd services/ai-agent
uv run pytest tests/test_search.py::test_literature_search -v
```
Expected: PASS (no change to behaviour yet, just future-proofing the mock).

- [ ] **Step 2: Write failing tests for DOI in tool output**

Add to `services/ai-agent/tests/test_search.py`:

```python
@patch("app.tools.search.requests.get")
def test_literature_search_doi_from_api(mock_get):
    """DOI from externalIds is shown directly without HTML fetch."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {
                "title": "Caffeine and Health",
                "authors": [{"name": "Smith J"}],
                "abstract": "A review of caffeine effects.",
                "year": 2023,
                "citationCount": 42,
                "url": "https://www.semanticscholar.org/paper/abc123",
                "externalIds": {"DOI": "10.1016/j.caffeine.2023.001"},
            }
        ]
    }
    mock_get.return_value = mock_resp

    result = literature_search.invoke("caffeine molecular properties")
    assert "10.1016/j.caffeine.2023.001" in result
    # Only one requests.get call — no HTML fetch needed
    mock_get.assert_called_once()


@patch("app.tools.search.requests.get")
def test_literature_search_doi_from_html_fallback(mock_get):
    """Falls back to HTML scraping when externalIds is empty."""
    s2_resp = MagicMock()
    s2_resp.status_code = 200
    s2_resp.raise_for_status = MagicMock()
    s2_resp.json.return_value = {
        "data": [
            {
                "title": "No DOI in API",
                "authors": [{"name": "Jones A"}],
                "abstract": "Abstract text.",
                "year": 2022,
                "citationCount": 5,
                "url": "https://www.semanticscholar.org/paper/xyz999",
                "externalIds": {},
            }
        ]
    }

    html_resp = MagicMock()
    html_resp.ok = True
    html_resp.text = '<meta name="citation_doi" content="10.9999/fallback.doi"/>'

    mock_get.side_effect = [s2_resp, html_resp]

    result = literature_search.invoke("some chemistry topic")
    assert "10.9999/fallback.doi" in result
    assert mock_get.call_count == 2  # S2 API + HTML fetch


@patch("app.tools.search.requests.get")
def test_literature_search_doi_from_html_fallback_null_external_ids(mock_get):
    """Falls back to HTML scraping when externalIds key is absent entirely."""
    s2_resp = MagicMock()
    s2_resp.status_code = 200
    s2_resp.raise_for_status = MagicMock()
    s2_resp.json.return_value = {
        "data": [
            {
                "title": "Old Paper No IDs",
                "authors": [],
                "abstract": "Old paper.",
                "year": 2005,
                "citationCount": 1,
                "url": "https://www.semanticscholar.org/paper/old",
                # externalIds key intentionally absent
            }
        ]
    }

    html_resp = MagicMock()
    html_resp.ok = True
    html_resp.text = '<a href="https://doi.org/10.8888/old.paper">link</a>'

    mock_get.side_effect = [s2_resp, html_resp]

    result = literature_search.invoke("old chemistry")
    assert "10.8888/old.paper" in result


@patch("app.tools.search.requests.get")
def test_literature_search_doi_not_available(mock_get):
    """Shows 'DOI: N/A' gracefully when no DOI found anywhere."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {
                "title": "No DOI Paper",
                "authors": [],
                "abstract": None,
                "year": 2020,
                "citationCount": 0,
                "url": "https://www.semanticscholar.org/paper/nodoi",
                "externalIds": {},
            }
        ]
    }

    html_resp = MagicMock(ok=True, text="<html>No DOI here</html>")
    mock_get.side_effect = [mock_resp, html_resp]

    result = literature_search.invoke("obscure topic")
    assert "DOI: N/A" in result
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
cd services/ai-agent
uv run pytest tests/test_search.py::test_literature_search_doi_from_api -v
```
Expected: FAIL — `externalIds` not in API request fields and DOI not in output.

- [ ] **Step 4: Update `literature_search` to request `externalIds` and resolve DOI**

First, add the import to `search.py` (near the top, with other local imports):

```python
from app.tools.utils import _scrape_doi_from_url
```

Then, change the `fields` value inside the `params` dict:

```python
# Before
"fields": "title,authors,abstract,year,citationCount,url",

# After
"fields": "title,authors,abstract,year,citationCount,url,externalIds",
```

Replace the `results.append(...)` call with the DOI-aware version:

```python
# Resolve DOI: prefer externalIds from API, fall back to HTML scraping
ext_ids = p.get("externalIds") or {}
doi = ext_ids.get("DOI")
if not doi:
    paper_url = p.get("url")
    if paper_url:
        doi = _scrape_doi_from_url(paper_url)

results.append(
    f"- **{p.get('title', 'Untitled')}** ({p.get('year', 'N/A')})\n"
    f"  Authors: {authors}\n"
    f"  Citations: {p.get('citationCount', 0)}\n"
    f"  DOI: {doi or 'N/A'}\n"
    f"  Abstract: {abstract}\n"
    f"  URL: {p.get('url', 'N/A')}"
)
```

- [ ] **Step 5: Run all search tests**

```bash
cd services/ai-agent
uv run pytest tests/test_search.py -v
```
Expected: all tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add services/ai-agent/app/tools/search.py services/ai-agent/tests/test_search.py
git commit -m "feat(search): add DOI to literature_search output via API + HTML scraping"
```

---

## Validation

After both tasks:

```bash
cd services/ai-agent
uv run pytest tests/test_search.py -v
```

Expected: all tests green (8 scraper unit tests + 4 integration-level tool tests + original tests).

To manually verify end-to-end:

```python
from app.tools.search import literature_search
print(literature_search.invoke("indole synthesis palladium catalysis"))
```

Each paper entry should now show a `DOI:` line with either a real DOI string or `N/A`.
