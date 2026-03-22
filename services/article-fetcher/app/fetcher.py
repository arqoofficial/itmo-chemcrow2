import logging
import os
import re
import subprocess
import tempfile

logger = logging.getLogger(__name__)

_SCIHUB_MIRRORS = [
    "https://sci-hub.ru",
    "https://sci-hub.ee",
]
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


def _extract_pdf_url(html: str, mirror: str) -> str:
    """Extract PDF URL from a sci-hub page.

    Handles two known layouts:
    - <meta name="citation_pdf_url" content="..."> (older layout)
    - <iframe src="//...pdf..."> (newer layout, PDF served from CDN)
    """
    # Layout 1: citation_pdf_url meta tag (both attribute orders)
    match = re.search(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']', html)
    if not match:
        match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']', html)

    # Layout 2: iframe whose src ends with .pdf (strip fragment); allow spaces around =
    if not match:
        match = re.search(r'<iframe[^>]+src\s*=\s*["\']([^"\']+\.pdf[^"\']*)["\']', html, re.IGNORECASE)

    if not match:
        return None

    pdf_path = match.group(1).split("#")[0]  # strip #view=FitH etc.
    if pdf_path.startswith("//"):
        return "https:" + pdf_path
    if pdf_path.startswith("/"):
        return mirror + pdf_path
    return pdf_path


def fetch_article(doi: str) -> bytes:
    """Download a PDF for the given DOI from sci-hub. Tries mirrors in order."""
    last_error: Exception = FetchError("No mirrors configured")

    for mirror in _SCIHUB_MIRRORS:
        logger.info("Trying mirror %s for DOI %s", mirror, doi)
        try:
            page_bytes = _curl_get_bytes("%s/%s" % (mirror, doi))
        except FetchError as e:
            logger.warning("Mirror %s unreachable for DOI %s: %s", mirror, doi, e)
            last_error = e
            continue
        except Exception as e:
            logger.warning("Mirror %s failed for DOI %s", mirror, doi, exc_info=True)
            last_error = FetchError("Failed to reach %s" % mirror)
            continue

        html = page_bytes.decode("utf-8", errors="replace")
        pdf_url = _extract_pdf_url(html, mirror)

        if not pdf_url:
            logger.warning("No PDF URL found on mirror %s for DOI %s", mirror, doi)
            last_error = FetchError("Article not available on sci-hub")
            continue

        logger.info("Found PDF URL for DOI %s: %s", doi, pdf_url)

        try:
            pdf_bytes = _curl_get_bytes(pdf_url)
        except FetchError as e:
            logger.warning("PDF download failed from %s for DOI %s: %s", pdf_url, doi, e)
            last_error = e
            continue
        except Exception as e:
            logger.warning("PDF download failed from %s for DOI %s", pdf_url, doi, exc_info=True)
            last_error = FetchError("Failed to download PDF")
            continue

        if len(pdf_bytes) == 0 or not pdf_bytes.startswith(b"%PDF"):
            logger.warning("Invalid PDF from %s for DOI %s", mirror, doi)
            last_error = FetchError("Downloaded file is not a valid PDF")
            continue

        logger.info("Fetched %d bytes for DOI %s via %s", len(pdf_bytes), doi, mirror)
        return pdf_bytes

    raise last_error
