"""Parser worker: Docling + LLM cleaning pipeline with MinIO output.

Utility functions are copied verbatim from parse_pdfs.py.
The async ``process_pdf_to_minio`` function replaces file-system output
with MinIO uploads using conversation-scoped object keys.
"""

import asyncio
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, List

from langdetect import DetectorFactory, detect
from langdetect.lang_detect_exception import LangDetectException

if TYPE_CHECKING:
    from app.minio_store import MinioStore

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level defaults
# ---------------------------------------------------------------------------

WINDOW_SIZE: int = 6000
OVERLAP: int = 800
DEFAULT_LANG: str = "en"

# Limit concurrent LLM calls to avoid overwhelming the API endpoint.
# At 4 concurrent calls, a 15-window paper completes in ≤4 batches.
LLM_CONCURRENCY: int = 4
# Per-window LLM timeout in seconds.  On timeout the raw Docling text is used
# so the overall job never fails due to a slow model.
WINDOW_TIMEOUT_SECS: int = 180

# First word(s) of the human-turn template per language — used to detect and
# strip prompt echoes from LLM outputs.
_PROMPT_ECHO_PREFIXES: dict[str, str] = {
    "ru": "ОЧИСТИ ЭТУ ЧАСТЬ",
    "en": "CLEAN THIS PART",
}

PROMPTS: dict[str, tuple[str, str]] = {
    "ru": (
        (
            "Ты исправляешь текст, извлечённый из PDF (методической литературы по химии).\n"
            "Смысл и содержание НЕ менять. НЕ добавлять новые факты.\n"
            "Исправь типичные артефакты PDF-парсинга:\n"
            "- пропущенные пробелы между словами\n"
            "- перенос слов с дефисом на конце строки (склей обратно)\n"
            "- жёсткие переносы строк внутри предложений\n"
            "- повторяющиеся колонтитулы и номера страниц (удали, если очевидны)\n"
            "- лишние пробелы и пустые строки\n"
            "Верни только исправленный текст в формате Markdown, без комментариев."
        ),
        "ОЧИСТИ ЭТУ ЧАСТЬ (фрагмент {part_idx}/{part_total}):\n\n{text}",
    ),
    "en": (
        (
            "You are cleaning text extracted from a PDF (chemistry methodology literature).\n"
            "Do NOT change the meaning or content. Do NOT add new facts.\n"
            "Fix typical PDF-extraction artefacts:\n"
            "- missing spaces between words\n"
            "- words broken with a hyphen at line breaks (rejoin them)\n"
            "- hard line breaks inside sentences\n"
            "- repeated headers, footers, and page numbers (remove if obvious)\n"
            "- duplicate whitespace and blank lines\n"
            "Return only the cleaned text in Markdown format, no commentary."
        ),
        "CLEAN THIS PART (chunk {part_idx}/{part_total}):\n\n{text}",
    ),
}


# ---------------------------------------------------------------------------
# Windowing
# ---------------------------------------------------------------------------

@dataclass
class Window:
    """A single character-level slice of a larger text.

    Attributes:
        i: Zero-based index of this window within the full sequence of
           windows produced for a document.  Used both for ordering and for
           constructing deterministic cache file names
           (``chunk_<i:03d>.md``).
        text: The raw text content of this window, including any overlap
              characters borrowed from the adjacent windows.
    """

    i: int
    text: str


def make_windows(
    text: str,
    window_size: int = WINDOW_SIZE,
    overlap: int = OVERLAP,
) -> List[Window]:
    """Split *text* into a sequence of overlapping character-level windows.

    Each consecutive pair of windows shares ``overlap`` characters at their
    boundary.  This prevents hard truncation of sentences that happen to fall
    exactly at a window edge.

    The very last window always ends exactly at the end of *text* — it may
    therefore be shorter than ``window_size``.

    Args:
        text: The input string to be windowed.  ``None`` is treated as an
              empty string.
        window_size: Maximum number of characters in each window.  Must be
                     strictly positive.
        overlap: Number of characters that adjacent windows share.  Must
                 satisfy ``0 <= overlap < window_size``.

    Returns:
        An ordered list of :class:`Window` objects.  The list is empty when
        *text* (after normalisation) has zero length.

    Raises:
        ValueError: If *window_size* is not positive, or if *overlap* is
                    negative or greater-than-or-equal-to *window_size*.

    Example::

        >>> windows = make_windows("abcdefghij", window_size=6, overlap=2)
        >>> [(w.i, w.text) for w in windows]
        [(0, 'abcdef'), (1, 'efghij')]
    """
    # Normalise None to empty string so callers do not have to guard against it.
    text = text or ""

    if window_size <= 0:
        raise ValueError("window_size must be > 0")
    if not (0 <= overlap < window_size):
        raise ValueError("overlap must be >= 0 and < window_size")

    windows: List[Window] = []
    start = 0
    i = 0
    n = len(text)

    while start < n:
        end = min(start + window_size, n)
        windows.append(Window(i=i, text=text[start:end]))
        i += 1

        # When the current window reaches the end of the text we are done.
        # Without this guard the loop would advance ``start`` past ``n``
        # and append an empty (or duplicate overlap) window.
        if end == n:
            break

        # Advance by (window_size - overlap) so the next window begins
        # ``overlap`` characters before the current window ends.
        start = end - overlap

    return windows


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def strip_prompt_echo(text: str, lang: str = DEFAULT_LANG) -> str:
    """Remove the human-turn instruction line if the LLM echoed it back.

    Some models reproduce the instruction prefix (e.g. "ОЧИСТИ ЭТУ ЧАСТЬ
    (фрагмент 1/5):") at the start of their response.  This function strips
    that first line plus the blank line that follows it when the known prefix
    for *lang* (or any language) is detected.

    Args:
        text: Raw LLM output or cached chunk text.
        lang: ISO 639-1 code; used to choose which prefix to check first.

    Returns:
        Text with the prompt echo removed, stripped of leading whitespace.
    """
    stripped = text.strip()
    prefixes = list(_PROMPT_ECHO_PREFIXES.values())
    # Check the language-specific prefix first, then all others as fallback.
    lang_prefix = _PROMPT_ECHO_PREFIXES.get(lang)
    if lang_prefix:
        prefixes = [lang_prefix] + [p for p in prefixes if p != lang_prefix]
    for prefix in prefixes:
        if stripped.startswith(prefix):
            # Drop everything up to and including the first blank line.
            after = re.sub(r"^[^\n]*\n+", "", stripped, count=1)
            return after.strip()
    return stripped


def detect_language(text: str, sample_chars: int = 2000) -> str:
    """Detect the dominant language of *text*, returning an ISO 639-1 code.

    Samples from the middle third of the text to skip Docling front-matter
    (table-of-contents, figure captions) that may not be representative.

    Sets ``DetectorFactory.seed = 0`` for deterministic results, consistent
    with the pipeline's ``temperature=0`` design principle.

    Args:
        text: Raw markdown text to analyse.
        sample_chars: Maximum number of characters to sample. Defaults to
                      2000 — below ``WINDOW_SIZE`` to avoid full-window cost,
                      above the ~200-char threshold for reliable detection.

    Returns:
        ISO 639-1 language code (e.g. ``"ru"``, ``"en"``), or
        ``DEFAULT_LANG`` if detection fails.
    """
    DetectorFactory.seed = 0
    if not text or not text.strip():
        log.warning("detect_language: empty text, defaulting to %s", DEFAULT_LANG)
        return DEFAULT_LANG
    n = len(text)
    mid_start = n // 3
    sample = text[mid_start: mid_start + sample_chars]
    try:
        return detect(sample)
    except LangDetectException as exc:
        log.warning("detect_language: detection failed (%s), defaulting to %s", exc, DEFAULT_LANG)
        return DEFAULT_LANG
    except Exception as exc:
        log.warning("detect_language: unexpected error (%s), defaulting to %s", exc, DEFAULT_LANG)
        return DEFAULT_LANG


# ---------------------------------------------------------------------------
# BM25 preprocessing
# ---------------------------------------------------------------------------

_NLP_CACHE: dict[str, Any] = {}

_SPACY_MODELS: dict[str, str] = {
    "en": "en_core_web_sm",
    "ru": "ru_core_news_sm",
}

_SPACY_FALLBACK: str = "en_core_web_sm"


def duplicate_headers(text: str) -> str:
    """Repeat the heading text inline so BM25 weights heading terms more.

    Transforms every ATX Markdown heading (``# … ######``) by appending the
    heading text a second time after a space.  For example::

        ## Synthesis  →  ## Synthesis Synthesis

    The ``#`` markers and the space that follows them are preserved so that
    downstream steps (e.g. :func:`lemmatize_strip`) can still detect and
    strip them.

    Args:
        text: Markdown text that may contain headings.

    Returns:
        Text with all headings duplicated.
    """
    return re.sub(r"^(#{1,6} )(.+)$", r"\1\2 \2", text, flags=re.MULTILINE)


def load_nlp(lang: str = DEFAULT_LANG):
    """Return a cached spaCy ``Language`` object for *lang*.

    Models are loaded lazily on first access and kept in :data:`_NLP_CACHE`
    keyed by model name.  Unknown language codes fall back to
    :data:`_SPACY_FALLBACK`.

    Args:
        lang: ISO 639-1 language code.

    Returns:
        A loaded spaCy ``Language`` pipeline.
    """
    import spacy

    model_name = _SPACY_MODELS.get(lang, _SPACY_FALLBACK)
    if model_name not in _NLP_CACHE:
        _NLP_CACHE[model_name] = spacy.load(model_name)
    return _NLP_CACHE[model_name]


def lemmatize_strip(text: str, lang: str = DEFAULT_LANG) -> str:
    """Strip Markdown syntax and lemmatize *text* for BM25 indexing.

    Processing order:

    1. Strip Markdown: ATX headings (``#``), bold/italic markers (``*``),
       and leading bullet characters (``-``, ``*``, ``+``).
    2. Run the spaCy pipeline for *lang* (loaded via :func:`load_nlp`).
    3. For each token apply the priority rule:

       * ``token.is_punct`` → ``token.text`` (surface form, natural spacing)
       * ``token.is_oov``   → ``token.text`` (preserves chemical names, etc.)
       * otherwise          → ``token.lemma_``

       Spacing is taken from ``token.whitespace_`` so punctuation does not
       acquire a spurious leading space.

    Args:
        text: Raw or header-duplicated Markdown text.
        lang: ISO 639-1 code used to select the spaCy model.

    Returns:
        Lemmatized plain text with Markdown syntax removed, stripped of
        leading/trailing whitespace.
    """
    # --- strip Markdown ---
    stripped = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    stripped = re.sub(r"\*{1,3}", "", stripped)
    stripped = re.sub(r"^\s*[-*+]\s+", "", stripped, flags=re.MULTILINE)

    # --- spaCy lemmatization ---
    nlp = load_nlp(lang)
    doc = nlp(stripped)
    result = ""
    for token in doc:
        if token.is_punct:
            # Preserve surface form so punctuation doesn't get a leading space.
            result += token.text + token.whitespace_
        elif _is_special_token(token.text):
            # Chemical names, abbreviations, formulae — preserve as written.
            result += token.text + token.whitespace_
        else:
            result += token.lemma_ + token.whitespace_
    return result.strip()


def _is_special_token(text: str) -> bool:
    """Return True for tokens that should not be lemmatized.

    Covers chemical formulae (H2SO4, CO2), mixed-case names (NaCl, pH),
    and all-caps abbreviations (KOH, DNA).  The heuristic is:

    * contains any digit, OR
    * has at least one uppercase letter after the first character
      (i.e. internal capitalisation that is not just sentence-start case).
    """
    if any(c.isdigit() for c in text):
        return True
    if len(text) > 1 and any(c.isupper() for c in text[1:]):
        return True
    return False


def make_bm25_chunk(text: str, lang: str = DEFAULT_LANG) -> str:
    """Apply the full BM25 preprocessing pipeline to *text*.

    Steps (in order):

    1. :func:`duplicate_headers` — boost heading-term weight.
    2. :func:`lemmatize_strip` — strip Markdown and lemmatize.

    Args:
        text: Cleaned Markdown text (one LLM-cleaned window).
        lang: ISO 639-1 code passed through to :func:`lemmatize_strip`.

    Returns:
        Plain-text, lemmatized string ready for BM25 indexing.
    """
    return lemmatize_strip(duplicate_headers(text), lang)


# ---------------------------------------------------------------------------
# LLM chain (built lazily so missing env vars only fail at runtime)
# ---------------------------------------------------------------------------

def build_chain(llm, lang: str = DEFAULT_LANG):
    """Construct the LangChain LCEL chain used to clean a single text window.

    Looks up the system message and human turn template for *lang* from
    :data:`PROMPTS`.  Falls back to ``PROMPTS[DEFAULT_LANG]`` for unknown
    language codes so the pipeline never fails due to an unsupported language.

    The chain is composed of three stages:

    1. ``ChatPromptTemplate`` — renders the localised system instruction and
       the human turn containing the raw window text and its position.
    2. ``llm`` — the pre-configured chat model instance injected by the caller.
    3. ``StrOutputParser`` — returns a plain Python string ready for disk.

    Args:
        llm: Any LangChain-compatible chat model instance (must support the
             ``invoke`` interface and accept a ``config`` keyword argument
             for passing callbacks).
        lang: ISO 639-1 language code.  Defaults to :data:`DEFAULT_LANG`.

    Returns:
        A LangChain ``Runnable`` that accepts a dict with keys
        ``part_idx`` (int), ``part_total`` (int), and ``text`` (str), and
        returns a cleaned Markdown string.
    """
    # These imports are deferred so that the module can be imported without
    # langchain installed — the dependency is only required when the chain
    # is actually built at runtime.
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    system_msg, human_turn = PROMPTS.get(lang, PROMPTS[DEFAULT_LANG])

    clean_prompt = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("human", human_turn),
    ])

    # LCEL pipe: prompt → model → plain-string parser
    return clean_prompt | llm | StrOutputParser()


# ---------------------------------------------------------------------------
# Async processing function with MinIO output
# ---------------------------------------------------------------------------

async def _clean_window(
    chain, window, total: int, job_id: str, langfuse_handler, semaphore: asyncio.Semaphore
) -> tuple[str, bool]:
    """Return (text, timed_out). On timeout, raw text is returned so other windows are not cancelled."""
    async with semaphore:
        config = {"run_name": f"{job_id}_chunk_{window.i:03d}"}
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]
        try:
            result = await asyncio.wait_for(
                chain.ainvoke(
                    {"part_idx": window.i + 1, "part_total": total, "text": window.text},
                    config=config,
                ),
                timeout=WINDOW_TIMEOUT_SECS,
            )
            return result.strip(), False
        except asyncio.TimeoutError:
            log.error(
                "parser: job %s window %d timed out after %ds",
                job_id, window.i, WINDOW_TIMEOUT_SECS,
            )
            return window.text.strip(), True


async def process_pdf_to_minio(
    pdf_bytes: bytes,
    job_id: str,
    conversation_id: str,
    doc_key: str,
    minio: "MinioStore",
    llm,
    langfuse_handler=None,
) -> dict[str, str]:
    """Run Docling + LLM cleaning pipeline and store chunk files in MinIO.

    Chunk files are written under:
      parsed-chunks/{conversation_id}/{doc_key}/_chunks/chunk_NNN.md
      parsed-chunks/{conversation_id}/{doc_key}/_bm25_chunks/chunk_NNN.txt

    Returns a dict mapping artifact names to MinIO object keys.
    """
    artifacts: dict[str, str] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        pdf_path = tmp / f"{job_id}.pdf"
        pdf_path.write_bytes(pdf_bytes)

        # Stage 1: Docling (CPU-bound — run in thread to avoid blocking event loop)
        def _docling_convert() -> str:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = False
            converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
            )
            return converter.convert(pdf_path).document.export_to_markdown()

        raw_md = await asyncio.to_thread(_docling_convert)
        log.info("parser: job %s docling completed (%d chars)", job_id, len(raw_md))

        # Stage 2: LLM cleaning — all windows fired concurrently
        lang = detect_language(raw_md)
        windows = make_windows(raw_md)
        total = len(windows)
        if total == 0:
            log.warning("parser: job %s produced no windows (empty or unreadable document)", job_id)
            return artifacts
        chain = build_chain(llm, lang)
        semaphore = asyncio.Semaphore(LLM_CONCURRENCY)

        results: list[tuple[str, bool]] = await asyncio.gather(*[
            _clean_window(chain, w, total, job_id, langfuse_handler, semaphore)
            for w in windows
        ])
        timed_out_windows = [w.i for w, (_, timed_out) in zip(windows, results) if timed_out]

        if timed_out_windows:
            raise RuntimeError(
                f"LLM timed out on {len(timed_out_windows)}/{total} window(s): {timed_out_windows}. "
                f"PDF is not fully parsed — job marked as failed."
            )

        cleaned_parts = [strip_prompt_echo(text, lang) for text, _ in results]
        bm25_parts = [make_bm25_chunk(c, lang) for c in cleaned_parts]

        # Upload chunk files with conversation-scoped keys
        for i, (cleaned, bm25) in enumerate(zip(cleaned_parts, bm25_parts)):
            filename = f"chunk_{i:03d}"
            key = minio.upload_chunk(conversation_id, doc_key, "_chunks", f"{filename}.md", cleaned)
            artifacts[filename] = key

            bm25_key = minio.upload_chunk(conversation_id, doc_key, "_bm25_chunks", f"{filename}.txt", bm25)
            artifacts[f"bm25_{i:03d}"] = bm25_key

        log.info("parser: job %s completed, %d chunk artifacts", job_id, len(artifacts))
        return artifacts
