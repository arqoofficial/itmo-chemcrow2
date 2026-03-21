from __future__ import annotations

from app.config import settings
from app.tools import rag
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
    monkeypatch.setattr(rag, "_get_retriever_for_scope", lambda scope="default": fake)

    result = rag.rag_search.invoke({"query": "amide coupling", "top_k": 999})

    assert "RAG retrieval results:" in result
    assert "doc_id=chapter_01" in result
    assert "doc_id=chunk_003" in result
    assert fake.last_query == "amide coupling"
    assert fake.last_top_k == 10


def test_literature_citation_search_formats_structured_citations(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)
    fake = _FakeRetriever()
    monkeypatch.setattr(rag, "_get_retriever_for_scope", lambda scope="default": fake)

    result = rag.literature_citation_search.invoke({"topic": "solvent selection"})

    assert "Citation candidates from local literature corpus:" in result
    assert "title=chapter_01" in result
    assert "source=(unknown source for chapter_01)" in result
    assert fake.last_query == "solvent selection"
    assert fake.last_top_k == 5


def test_literature_citation_search_empty_topic(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)

    result = rag.literature_citation_search.invoke({"topic": "   "})

    assert result == "Query must be a non-empty string."


def test_rag_search_missing_data(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)

    def _raise_missing(scope="default"):
        raise FileNotFoundError("app/data-rag/sources/default")

    monkeypatch.setattr(rag, "_get_retriever_for_scope", _raise_missing)

    result = rag.rag_search.invoke({"query": "aldol condensation"})

    assert "RAG data is not initialized correctly." in result


def test_bm25_dense_rrf_retrieve_forwards_doc_metadata():
    """retrieve() must forward raw_source from document resolver into RetrievalResult.metadata."""
    from app.tools.rag import (
        BM25DenseRankFusionRetriever,
        BM25Retriever,
        NomicDenseRetriever,
        Document,
    )

    class _StubBM25:
        def retrieve_ids(self, query, top_k=5):
            return [("doc_01", 0.9)]

        def build_or_load(self, docs, force_rebuild=False):
            pass

    class _StubDense:
        def retrieve_ids(self, query, top_k=5):
            return [("doc_01", 0.8)]

        def build_or_load(self, docs, force_rebuild=False):
            pass

    def resolver(doc_id):
        return ("some text about chemistry", {"raw_source": "app/data-rag/sources/default/corpus_raw/doc_01.md"})

    retriever = BM25DenseRankFusionRetriever(
        bm25_retriever=_StubBM25(),
        dense_retriever=_StubDense(),
        document_resolver=resolver,
    )
    results = retriever.retrieve("test query", top_k=1)

    assert len(results) == 1
    assert results[0].text == "some text about chemistry"
    assert results[0].metadata["raw_source"] == "app/data-rag/sources/default/corpus_raw/doc_01.md"
    assert results[0].metadata["retriever"] == "bm25_dense_rrf"
