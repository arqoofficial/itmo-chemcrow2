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
    """retrieve() must forward source from document resolver into RetrievalResult.metadata."""
    from app.tools.rag import BM25DenseRankFusionRetriever

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
        return ("some text about chemistry", {"source": "app/data-rag/sources/default/corpus_processed/doc_chunks/chunk_001.md"})

    retriever = BM25DenseRankFusionRetriever(
        bm25_retriever=_StubBM25(),
        dense_retriever=_StubDense(),
        document_resolver=resolver,
    )
    results = retriever.retrieve("test query", top_k=1)

    assert len(results) == 1
    assert results[0].text == "some text about chemistry"
    assert results[0].metadata["source"] == "app/data-rag/sources/default/corpus_processed/doc_chunks/chunk_001.md"
    assert results[0].metadata["retriever"] == "bm25_dense_rrf"


def test_load_chunked_processed_corpus_builds_mapping(tmp_path):
    processed = tmp_path / "corpus_processed"
    dense_dir = processed / "paper_01_chunks"
    bm25_dir = processed / "paper_01_bm25_chunks"
    dense_dir.mkdir(parents=True)
    bm25_dir.mkdir(parents=True)

    (dense_dir / "chunk_000.md").write_text("canonical dense text", encoding="utf-8")
    (bm25_dir / "chunk_000.txt").write_text("bm25-optimized text", encoding="utf-8")

    bundle = rag._load_chunked_processed_corpus(processed)

    assert len(bundle.dense_documents) == 1
    assert len(bundle.bm25_documents) == 1
    bm25_doc = bundle.bm25_documents[0]
    canonical_doc = bundle.dense_documents[0]
    assert bm25_doc.metadata["canonical_doc_id"] == canonical_doc.doc_id
    assert bundle.bm25_to_canonical_doc_id[bm25_doc.doc_id] == canonical_doc.doc_id
    assert bundle.canonical_documents_by_id[canonical_doc.doc_id].text == "canonical dense text"


def test_bm25_dense_rrf_normalizes_bm25_ids_to_canonical():
    class _StubBM25:
        def retrieve_ids(self, query, top_k=5):
            return [("paper_01::bm25::chunk_000", 0.95)]

    class _StubDense:
        def retrieve_ids(self, query, top_k=5):
            return [("paper_01::chunk_000", 0.91)]

    def resolver(doc_id):
        if doc_id == "paper_01::chunk_000":
            return (
                "canonical chunk text",
                {"source": "app/data-rag/sources/default/corpus_processed/paper_01_chunks/chunk_000.md"},
            )
        return None

    retriever = rag.BM25DenseRankFusionRetriever(
        bm25_retriever=_StubBM25(),
        dense_retriever=_StubDense(),
        bm25_to_canonical_doc_id={"paper_01::bm25::chunk_000": "paper_01::chunk_000"},
        document_resolver=resolver,
    )

    ids = retriever.retrieve_ids("solvent", top_k=1)
    assert ids[0][0] == "paper_01::chunk_000"

    results = retriever.retrieve("solvent", top_k=1)
    assert results[0].doc_id == "paper_01::chunk_000"
    assert results[0].text == "canonical chunk text"
