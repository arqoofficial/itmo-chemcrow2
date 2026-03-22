import logging
import os
import re
import subprocess
import tempfile

logger = logging.getLogger(__name__)

_SCIHUB_URL = "https://sci-hub.ru"
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_CURL_BASE = ["curl", "-L", "-A", _USER_AGENT, "--max-time", "30", "-s", "-f"]


class FetchError(Exception):
    pass


def _curl_get_bytes(url: str) -> bytes:
    """Fetch URL bytes via curl subprocess."""
    result = subprocess.run(
        [*_CURL_BASE, url],
        capture_output=True,
        timeout=35,
    )
    if result.returncode != 0:
        raise FetchError("curl failed (rc=%d): %s" % (result.returncode, result.stderr.decode(errors="replace")[:200]))
    return result.stdout


def _extract_pdf_url(html: str) -> str:
    """Extract PDF path from sci-hub page citation_pdf_url meta tag."""
    match = re.search(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']', html)
    if not match:
        # Also try reversed attribute order
        match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']', html)
    if not match:
        raise FetchError("Article not available on sci-hub")
    pdf_path = match.group(1)
    if pdf_path.startswith("//"):
        return "https:" + pdf_path
    if pdf_path.startswith("/"):
        return _SCIHUB_URL + pdf_path
    return pdf_path


def fetch_article(doi: str) -> bytes:
    """Download a PDF for the given DOI from sci-hub. Returns raw PDF bytes."""
    logger.info("Fetching DOI %s via sci-hub", doi)

    try:
        page_bytes = _curl_get_bytes("%s/%s" % (_SCIHUB_URL, doi))
    except FetchError:
        raise
    except Exception as e:
        logger.exception("Failed to fetch sci-hub page for DOI %s", doi)
        raise FetchError("Failed to reach sci-hub") from e

    html = page_bytes.decode("utf-8", errors="replace")

    try:
        pdf_url = _extract_pdf_url(html)
    except FetchError:
        raise

    logger.info("Found PDF URL for DOI %s: %s", doi, pdf_url)

    try:
        pdf_bytes = _curl_get_bytes(pdf_url)
    except FetchError:
        raise
    except Exception as e:
        logger.exception("Failed to download PDF for DOI %s from %s", doi, pdf_url)
        raise FetchError("Failed to download PDF from sci-hub") from e

    if len(pdf_bytes) == 0 or not pdf_bytes.startswith(b"%PDF"):
        raise FetchError("Downloaded file is not a valid PDF — article may not be available on sci-hub")

    logger.info("Fetched %d bytes for DOI %s", len(pdf_bytes), doi)
    return pdf_bytes
