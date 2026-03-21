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
    monkeypatch.setattr(rag, "_get_hybrid_retriever", lambda: fake)

    result = rag.rag_search.invoke({"query": "amide coupling", "top_k": 999})

    assert "RAG retrieval results:" in result
    assert "doc_id=chapter_01" in result
    assert "doc_id=chunk_003" in result
    assert fake.last_query == "amide coupling"
    assert fake.last_top_k == 10


def test_rag_search_missing_data(monkeypatch):
    monkeypatch.setattr(settings, "RAG_ENABLED", True)

    def _raise_missing():
        raise FileNotFoundError("app/data-rag/corpus_raw")

    monkeypatch.setattr(rag, "_get_hybrid_retriever", _raise_missing)

    result = rag.rag_search.invoke({"query": "aldol condensation"})

    assert "RAG data is not initialized correctly." in result
