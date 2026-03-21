from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.tools import rag
from app.tools import rag_pdf_ingestion
from app.tools.rag import RetrievalResult


class _FakeRetriever:
    def __init__(self) -> None:
        self.last_query: str | None = None
        self.last_top_k: int | None = None

    def retrieve(self, query: str, top_k: int = 5):
        self.last_query = query
        self.last_top_k = top_k
        return [
            RetrievalResult(
                doc_id="chapter_01",
                score=0.9231,
                text="Organic synthesis route planning with catalysts and solvents.",
                metadata={},
            ),
            RetrievalResult(
                doc_id="chunk_003",
                score=0.8112,
                text="Yield optimization requires balancing temperature and concentration.",
                metadata={},
            ),
        ]


def test_rag_search_disabled(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", False)

    result = rag.rag_search.invoke({"query": "acetylation"})

    assert result == "RAG tool is disabled by configuration."


def test_rag_search_empty_query(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)

    result = rag.rag_search.invoke({"query": "   "})

    assert result == "Query must be a non-empty string."


def test_rag_search_happy_path_and_top_k_clamp(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    fake = _FakeRetriever()
    monkeypatch.setattr(rag, "_get_hybrid_retriever", lambda: fake)

    result = rag.rag_search.invoke({"query": "amide coupling", "top_k": 999})

    assert "RAG retrieval results:" in result
    assert "doc_id=chapter_01" in result
    assert "doc_id=chunk_003" in result
    assert fake.last_query == "amide coupling"
    assert fake.last_top_k == 10


def test_literature_citation_search_formats_structured_citations(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    fake = _FakeRetriever()
    monkeypatch.setattr(rag, "_get_hybrid_retriever", lambda: fake)

    result = rag.literature_citation_search.invoke({"topic": "solvent selection"})

    assert "Citation candidates from local literature corpus:" in result
    assert "title=chapter_01" in result
    assert "source=app/data-rag/corpus_raw/chapter_01.md" in result
    assert fake.last_query == "solvent selection"
    assert fake.last_top_k == 5


def test_literature_citation_search_empty_topic(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)

    result = rag.literature_citation_search.invoke({"topic": "   "})

    assert result == "Query must be a non-empty string."


def test_rag_search_missing_data(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)

    def _raise_missing():
        raise FileNotFoundError("app/data-rag/corpus_raw")

    monkeypatch.setattr(rag, "_get_hybrid_retriever", _raise_missing)

    result = rag.rag_search.invoke({"query": "aldol condensation"})

    assert "RAG data is not initialized correctly." in result


def test_prepare_processed_corpus_builds_pdf_and_bm25_variants(monkeypatch, tmp_path: Path):
    raw_dir = tmp_path / "corpus_raw"
    processed_dir = tmp_path / "corpus_processed"
    pdf_dir = raw_dir / "pdfs"
    raw_dir.mkdir(parents=True)
    pdf_dir.mkdir(parents=True)

    (raw_dir / "chapter_01.md").write_text("# Chapter 1\n\nOrganic chemistry.", encoding="utf-8")
    (pdf_dir / "guide.pdf").write_bytes(b"%PDF-1.4\n%%EOF")

    monkeypatch.setattr(settings, "RAG_PDF_RAW_SUBDIR", "pdfs")
    monkeypatch.setattr(settings, "RAG_BM25_SUFFIX", "__bm25")
    monkeypatch.setattr(settings, "RAG_PDF_ENABLE_LLM_CLEANING", False)
    monkeypatch.setattr(settings, "RAG_PDF_CLEAN_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setattr(settings, "RAG_PDF_CLEAN_WINDOW_SIZE", 1000)
    monkeypatch.setattr(settings, "RAG_PDF_CLEAN_OVERLAP", 100)

    monkeypatch.setattr(
        rag_pdf_ingestion,
        "extract_markdown_from_pdf",
        lambda _: "# PDF Guide\n\nSynthetic route notes.",
    )

    rag._prepare_processed_corpus(raw_dir, processed_dir)

    assert (processed_dir / "chapter_01.md").exists()
    assert (processed_dir / "chapter_01__bm25.md").exists()
    assert (processed_dir / "pdf_guide.md").exists()
    assert (processed_dir / "pdf_guide__bm25.md").exists()


def test_build_bm25_documents_prefers_bm25_variants(tmp_path: Path):
    processed_dir = tmp_path / "corpus_processed"
    processed_dir.mkdir(parents=True)

    (processed_dir / "doc_a.md").write_text("CLEAN A", encoding="utf-8")
    (processed_dir / "doc_a__bm25.md").write_text("bm25 a", encoding="utf-8")
    (processed_dir / "doc_b.md").write_text("CLEAN B", encoding="utf-8")

    clean_docs = rag._load_markdown_documents(processed_dir, bm25_only=False, bm25_suffix="__bm25")
    bm25_docs = rag._build_bm25_documents(
        processed_dir,
        clean_docs,
        bm25_suffix="__bm25",
    )
    by_id = {doc.doc_id: doc for doc in bm25_docs}

    assert by_id["doc_a"].text == "bm25 a"
    assert by_id["doc_b"].text == "CLEAN B"
