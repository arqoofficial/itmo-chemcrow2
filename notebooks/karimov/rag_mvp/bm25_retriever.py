from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from .base import BaseRetriever, Document, RetrievalResult
from .bm25_embedder import BM25SparseEmbedder


DocumentResolver = Callable[[str], str | None]


class BM25Retriever(BaseRetriever):
    """Retriever built on top of BM25 sparse embeddings."""

    INDEX_VERSION = 1

    def __init__(
        self,
        embedder: BM25SparseEmbedder | None = None,
        *,
        index_path: str | Path | None = None,
        document_resolver: DocumentResolver | None = None,
    ) -> None:
        self.embedder = embedder or BM25SparseEmbedder()
        self._documents: list[Document] = []
        self._doc_vectors: list[dict[str, float]] = []
        self._index_path = Path(index_path) if index_path is not None else None
        self._document_resolver = document_resolver

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

        if self._index_path is not None:
            self.save_index(self._index_path, documents)

    def build_or_load(self, documents: list[Document], force_rebuild: bool = False) -> str:
        """Load fresh on-disk index or build and persist a new one."""
        if self._index_path is None:
            self.build(documents)
            return "built"

        if not force_rebuild and self.load_index(self._index_path, documents):
            return "loaded"

        self.build(documents)
        return "built"

    def save_index(self, path: str | Path, documents: list[Document]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "version": self.INDEX_VERSION,
            "fingerprint": self._fingerprint_documents(documents),
            "documents": [
                {
                    "doc_id": doc.doc_id,
                    "text": doc.text,
                    "metadata": doc.metadata,
                }
                for doc in documents
            ],
            "doc_vectors": self._doc_vectors,
            "embedder_state": self.embedder.to_state(),
        }

        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def load_index(self, path: str | Path, documents: list[Document]) -> bool:
        target = Path(path)
        if not target.exists():
            return False

        payload = json.loads(target.read_text(encoding="utf-8"))
        if payload.get("version") != self.INDEX_VERSION:
            return False

        expected = self._fingerprint_documents(documents)
        if payload.get("fingerprint") != expected:
            return False

        self.embedder = BM25SparseEmbedder.from_state(payload["embedder_state"])
        self._documents = [
            Document(
                doc_id=item["doc_id"],
                text=item.get("text", ""),
                metadata=item.get("metadata", {}),
            )
            for item in payload["documents"]
        ]
        self._doc_vectors = [
            {str(k): float(v) for k, v in vec.items()}
            for vec in payload["doc_vectors"]
        ]
        return True

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
            text = doc.text
            if self._document_resolver is not None:
                resolved = self._document_resolver(doc.doc_id)
                if resolved is not None:
                    text = resolved
            results.append(
                RetrievalResult(
                    doc_id=doc.doc_id,
                    score=float(score),
                    text=text,
                    metadata=doc.metadata,
                )
            )
        return results

    def retrieve_ids(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Retrieve only doc_ids and scores; useful for deferred raw document loading."""
        if not self._documents:
            raise ValueError("Retriever is not built")
        if top_k <= 0:
            return []

        scores = self.embedder.score_query_against_corpus(query)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [
            (self._documents[idx].doc_id, float(score))
            for idx, score in ranked[:top_k]
        ]

    def set_document_resolver(self, resolver: DocumentResolver | None) -> None:
        self._document_resolver = resolver

    @staticmethod
    def _fingerprint_documents(documents: list[Document]) -> str:
        hasher = hashlib.sha256()
        for doc in documents:
            hasher.update(doc.doc_id.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(doc.text.encode("utf-8"))
            hasher.update(b"\x00")
        return hasher.hexdigest()

    @property
    def vector_db(self) -> list[dict[str, float]]:
        """Expose sparse vectors for downstream reranking/debugging."""
        return self._doc_vectors
