from __future__ import annotations

from collections import defaultdict
from typing import Callable

from .base import BaseRetriever, Document, RetrievalResult
from .bm25_retriever import BM25Retriever
from .nomic_dense_retriever import NomicDenseRetriever

DocumentResolver = Callable[[str], str | None]


class BM25DenseRankFusionRetriever(BaseRetriever):
    """Hybrid retriever using reciprocal rank fusion (RRF) over BM25 and dense results."""

    def __init__(
        self,
        *,
        bm25_retriever: BM25Retriever,
        dense_retriever: NomicDenseRetriever,
        rrf_k: int = 60,
        bm25_weight: float = 1.0,
        dense_weight: float = 1.0,
        candidate_k: int = 20,
        document_resolver: DocumentResolver | None = None,
    ) -> None:
        self.bm25_retriever = bm25_retriever
        self.dense_retriever = dense_retriever
        self.rrf_k = rrf_k
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight
        self.candidate_k = candidate_k
        self._document_resolver = document_resolver

    def build(self, documents: list[Document]) -> None:
        """Build both child retrievers from the same document list."""
        self.bm25_retriever.build(documents)
        self.dense_retriever.build(documents)

    def retrieve_ids(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        if top_k <= 0:
            return []

        retrieve_k = max(top_k, self.candidate_k)
        bm25_ids = self.bm25_retriever.retrieve_ids(query, top_k=retrieve_k)
        dense_ids = self.dense_retriever.retrieve_ids(query, top_k=retrieve_k)

        scores: dict[str, float] = defaultdict(float)

        for rank, (doc_id, _) in enumerate(bm25_ids, start=1):
            scores[doc_id] += self.bm25_weight / (self.rrf_k + rank)

        for rank, (doc_id, _) in enumerate(dense_ids, start=1):
            scores[doc_id] += self.dense_weight / (self.rrf_k + rank)

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        ranked_ids = self.retrieve_ids(query, top_k=top_k)

        results: list[RetrievalResult] = []
        for doc_id, score in ranked_ids:
            text = ""
            if self._document_resolver is not None:
                resolved = self._document_resolver(doc_id)
                if resolved is not None:
                    text = resolved

            results.append(
                RetrievalResult(
                    doc_id=doc_id,
                    score=float(score),
                    text=text,
                    metadata={
                        "retriever": "bm25_dense_rrf",
                        "rrf_k": self.rrf_k,
                        "bm25_weight": self.bm25_weight,
                        "dense_weight": self.dense_weight,
                    },
                )
            )

        return results

    def set_document_resolver(self, resolver: DocumentResolver | None) -> None:
        self._document_resolver = resolver
