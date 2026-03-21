from __future__ import annotations

from .base import BaseRetriever, Document, RetrievalResult
from .bm25_embedder import BM25SparseEmbedder


class BM25Retriever(BaseRetriever):
    """Retriever built on top of BM25 sparse embeddings."""

    def __init__(self, embedder: BM25SparseEmbedder | None = None) -> None:
        self.embedder = embedder or BM25SparseEmbedder()
        self._documents: list[Document] = []
        self._doc_vectors: list[dict[str, float]] = []

    def build(self, documents: list[Document]) -> None:
        if not documents:
            raise ValueError("Cannot build retriever with an empty corpus")

        self._documents = documents
        self.embedder.fit(documents)

        # Precompute sparse vectors as a simple in-memory vector database.
        self._doc_vectors = [
            self.embedder.encode_document(doc.text)
            for doc in documents
        ]

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        if not self._documents:
            raise ValueError("Retriever is not built")
        if top_k <= 0:
            return []

        scores = self.embedder.score_query_against_corpus(query)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

        results: list[RetrievalResult] = []
        for idx, score in ranked[:top_k]:
            doc = self._documents[idx]
            results.append(
                RetrievalResult(
                    doc_id=doc.doc_id,
                    score=float(score),
                    text=doc.text,
                    metadata=doc.metadata,
                )
            )
        return results

    @property
    def vector_db(self) -> list[dict[str, float]]:
        """Expose sparse vectors for downstream reranking/debugging."""
        return self._doc_vectors
