import logging
import os
import tempfile

from scidownl import scihub_download

logger = logging.getLogger(__name__)


class FetchError(Exception):
    pass


def fetch_article(doi: str) -> bytes:
    """Download a PDF for the given DOI from sci-hub. Returns raw PDF bytes."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        logger.info("Fetching DOI %s via sci-hub", doi)
        scihub_download(doi, paper_type="doi", scihub_url="https://sci-hub.ru", out=tmp_path)

        size = os.path.getsize(tmp_path)
        if size == 0:
            raise FetchError("Downloaded file is empty — article not found on sci-hub")

        with open(tmp_path, "rb") as f:
            data = f.read()

        logger.info("Fetched %d bytes for DOI %s", len(data), doi)
        return data

    except FetchError:
        raise
    except Exception as e:
        logger.exception("Failed to fetch DOI %s", doi)
        msg = str(e)
        if "crawling" in msg or "No pdf tag" in msg or "pdf" in msg.lower():
            raise FetchError("Article not available on sci-hub") from e
        raise FetchError(msg) from e
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
