from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

BM25_SUFFIX = "__bm25"
PDF_DOC_PREFIX = "pdf_"

_PROMPT_ECHO_PREFIXES = (
    "CLEAN THIS PART",
    "ОЧИСТИ ЭТУ ЧАСТЬ",
)


@dataclass(slots=True)
class ProcessedCorpusSummary:
    copied_raw_markdown: int = 0
    generated_pdf_docs: int = 0
    generated_bm25_docs: int = 0


def bm25_variant_name(stem: str, *, suffix: str = BM25_SUFFIX) -> str:
    return f"{stem}{suffix}.md"


def is_bm25_variant_stem(stem: str, *, suffix: str = BM25_SUFFIX) -> bool:
    return stem.endswith(suffix)


def canonical_doc_id(stem: str, *, suffix: str = BM25_SUFFIX) -> str:
    if stem.endswith(suffix):
        return stem[: -len(suffix)]
    return stem


def extract_markdown_from_pdf(pdf_path: Path) -> str:
    """Extract markdown-ish text from a PDF using pypdf as the baseline parser."""
    try:
        PdfReader = import_module("pypdf").PdfReader
    except ImportError as exc:
        raise ImportError(
            "PDF ingestion requires pypdf. Install it in ai-agent environment."
        ) from exc

    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    joined = "\n\n".join(p.strip() for p in pages if p and p.strip())
    return joined.strip()


def _clean_prompt_echo(text: str) -> str:
    stripped = text.strip()
    for prefix in _PROMPT_ECHO_PREFIXES:
        if stripped.startswith(prefix):
            after = re.sub(r"^[^\n]*\n+", "", stripped, count=1)
            return after.strip()
    return stripped


def make_windows(text: str, window_size: int, overlap: int) -> list[str]:
    text = text or ""
    if window_size <= 0:
        raise ValueError("window_size must be > 0")
    if not (0 <= overlap < window_size):
        raise ValueError("overlap must be >= 0 and < window_size")

    windows: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + window_size, n)
        windows.append(text[start:end])
        if end == n:
            break
        start = end - overlap
    return windows


def deterministic_clean_markdown(text: str) -> str:
    """Cheap deterministic cleanup for PDF extraction artefacts."""
    if not text:
        return ""

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")

    cleaned = re.sub(r"(\w)-\n(\w)", r"\1\2", cleaned)
    cleaned = re.sub(r"([^\n])\n([^\n#*\-\d])", r"\1 \2", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def _build_llm_cleaner(model: str):
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    llm = cast(Any, ChatOpenAI)(
        model=model,
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE"),
        temperature=0,
    )

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are cleaning text extracted from chemistry PDFs. "
            "Do not add facts and do not change meaning. "
            "Fix spacing, broken hyphenation, and hard line breaks. "
            "Return only cleaned Markdown text.",
        ),
        (
            "human",
            "CLEAN THIS PART (chunk {part_idx}/{part_total}):\n\n{text}",
        ),
    ])
    return prompt | llm | StrOutputParser()


def clean_with_optional_llm(
    text: str,
    *,
    use_llm: bool,
    model: str,
    window_size: int,
    overlap: int,
) -> str:
    base = deterministic_clean_markdown(text)
    if not use_llm:
        return base

    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("LLM cleaning enabled but OPENAI_API_KEY is missing; using deterministic fallback")
        return base

    try:
        chain = _build_llm_cleaner(model)
    except Exception as exc:
        logger.warning("Failed to initialize LLM cleaner (%s); using deterministic fallback", exc)
        return base

    windows = make_windows(base, window_size=window_size, overlap=overlap)
    if not windows:
        return ""

    cleaned_parts: list[str] = []
    total = len(windows)
    for idx, win in enumerate(windows, start=1):
        try:
            out = chain.invoke({"part_idx": idx, "part_total": total, "text": win})
            cleaned_parts.append(_clean_prompt_echo((out or "").strip()))
        except Exception as exc:
            logger.warning("LLM cleaning failed at chunk %d/%d (%s); fallback for this chunk", idx, total, exc)
            cleaned_parts.append(win)

    return "\n\n".join(p for p in cleaned_parts if p).strip()


def make_bm25_text(text: str) -> str:
    """Create BM25-oriented text variant from markdown.

    Strategy is intentionally lightweight and dependency-free:
    duplicate headings, remove markdown syntax, lowercase, and normalize whitespace.
    """
    if not text:
        return ""

    with_header_boost = re.sub(r"^(#{1,6} )(.+)$", r"\1\2 \2", text, flags=re.MULTILINE)
    stripped = re.sub(r"^#{1,6}\s+", "", with_header_boost, flags=re.MULTILINE)
    stripped = re.sub(r"\*{1,3}", "", stripped)
    stripped = re.sub(r"^\s*[-*+]\s+", "", stripped, flags=re.MULTILINE)
    stripped = re.sub(r"`", "", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip().lower()
    return stripped


def process_raw_and_pdf_corpus(
    *,
    raw_corpus_dir: Path,
    processed_corpus_dir: Path,
    pdf_raw_subdir: str,
    bm25_suffix: str = BM25_SUFFIX,
    use_llm_cleaning: bool = False,
    llm_model: str = "openai/gpt-4o-mini",
    llm_window_size: int = 6000,
    llm_overlap: int = 800,
) -> ProcessedCorpusSummary:
    if not raw_corpus_dir.exists():
        raise FileNotFoundError(f"Raw corpus directory does not exist: {raw_corpus_dir}")

    processed_corpus_dir.mkdir(parents=True, exist_ok=True)

    summary = ProcessedCorpusSummary()

    # 1) Mirror raw markdown and generate BM25 variants.
    for raw_file in sorted(raw_corpus_dir.glob("*.md")):
        if is_bm25_variant_stem(raw_file.stem, suffix=bm25_suffix):
            continue
        dst = processed_corpus_dir / raw_file.name
        text = raw_file.read_text(encoding="utf-8")
        dst.write_text(text, encoding="utf-8")
        summary.copied_raw_markdown += 1

        bm25_path = processed_corpus_dir / bm25_variant_name(raw_file.stem, suffix=bm25_suffix)
        bm25_path.write_text(make_bm25_text(text), encoding="utf-8")
        summary.generated_bm25_docs += 1

    # 2) Process PDFs from the dedicated raw/pdfs folder.
    pdf_dir = raw_corpus_dir / pdf_raw_subdir
    if not pdf_dir.exists():
        logger.info("PDF source directory does not exist: %s (skipping)", pdf_dir)
        return summary

    for pdf_file in sorted(pdf_dir.glob("*.pdf")):
        pdf_doc_stem = f"{PDF_DOC_PREFIX}{pdf_file.stem}"
        clean_md_path = processed_corpus_dir / f"{pdf_doc_stem}.md"
        bm25_md_path = processed_corpus_dir / bm25_variant_name(pdf_doc_stem, suffix=bm25_suffix)

        if clean_md_path.exists() and bm25_md_path.exists():
            continue

        extracted = extract_markdown_from_pdf(pdf_file)
        cleaned = clean_with_optional_llm(
            extracted,
            use_llm=use_llm_cleaning,
            model=llm_model,
            window_size=llm_window_size,
            overlap=llm_overlap,
        )
        if not cleaned:
            cleaned = f"# {pdf_file.stem}\n\n"

        clean_md_path.write_text(cleaned, encoding="utf-8")
        summary.generated_pdf_docs += 1

        bm25_md_path.write_text(make_bm25_text(cleaned), encoding="utf-8")
        summary.generated_bm25_docs += 1

    return summary
