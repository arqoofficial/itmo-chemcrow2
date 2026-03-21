"""Hybrid RAG tool for chemistry corpus retrieval.

This module provides a single LangChain tool entrypoint (`rag_search`) and keeps
retrieval internals local to support migration from experimental notebooks.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import shutil
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from langchain.tools import tool

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_RETRIEVER_REGISTRY: dict[str, BM25DenseRankFusionRetriever] = {}
_REGISTRY_LOCK = Lock()


@dataclass(slots=True)
class Document:
    """A corpus document used by retrievers."""

    doc_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalResult:
    """A single retrieval hit."""

    doc_id: str
    score: float
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


DocumentResolver = Callable[[str], tuple[str, dict[str, Any]] | None]


class BM25SparseEmbedder:
    """BM25 sparse embedding model over tokenized text."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._doc_count = 0
        self._avg_doc_len = 0.0
        self._doc_term_freqs: list[Counter[str]] = []
        self._doc_lengths: list[int] = []
        self._idf: dict[str, float] = {}

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [tok.lower() for tok in _TOKEN_RE.findall(text)]

    def fit(self, documents: list[Document]) -> None:
        if not documents:
            raise ValueError("Cannot fit BM25 on an empty document list")

        self._doc_count = len(documents)
        self._doc_term_freqs = []
        self._doc_lengths = []
        doc_freq: Counter[str] = Counter()

        for doc in documents:
            tokens = self._tokenize(doc.text)
            tf = Counter(tokens)
            self._doc_term_freqs.append(tf)
            self._doc_lengths.append(len(tokens))
            doc_freq.update(tf.keys())

        self._avg_doc_len = sum(self._doc_lengths) / max(self._doc_count, 1)
        self._idf = {
            term: math.log(1.0 + (self._doc_count - df + 0.5) / (df + 0.5))
            for term, df in doc_freq.items()
        }

    def encode_document(self, text: str) -> dict[str, float]:
        tokens = self._tokenize(text)
        tf = Counter(tokens)
        if not tokens:
            return {}

        doc_len = len(tokens)
        norm = 1.0 - self.b + self.b * (doc_len / max(self._avg_doc_len, 1e-9))

        sparse: dict[str, float] = {}
        for term, freq in tf.items():
            idf = self._idf.get(term, 0.0)
            if idf == 0.0:
                continue
            numerator = freq * (self.k1 + 1.0)
            denominator = freq + self.k1 * norm
            sparse[term] = idf * (numerator / denominator)
        return sparse

    def score_query_against_corpus(self, query: str) -> list[float]:
        if self._doc_count == 0:
            raise ValueError("BM25 model is not fitted")

        query_terms = self._tokenize(query)
        if not query_terms:
            return [0.0] * self._doc_count

        scores = [0.0] * self._doc_count
        for i, tf in enumerate(self._doc_term_freqs):
            doc_len = self._doc_lengths[i]
            norm = 1.0 - self.b + self.b * (doc_len / max(self._avg_doc_len, 1e-9))
            score = 0.0
            for term in query_terms:
                freq = tf.get(term, 0)
                if freq == 0:
                    continue
                idf = self._idf.get(term, 0.0)
                numerator = freq * (self.k1 + 1.0)
                denominator = freq + self.k1 * norm
                score += idf * (numerator / denominator)
            scores[i] = score
        return scores

    def to_state(self) -> dict[str, Any]:
        if self._doc_count == 0:
            raise ValueError("Cannot serialize an unfitted BM25 model")
        return {
            "k1": self.k1,
            "b": self.b,
            "doc_count": self._doc_count,
            "avg_doc_len": self._avg_doc_len,
            "doc_lengths": self._doc_lengths,
            "idf": self._idf,
            "doc_term_freqs": [dict(tf) for tf in self._doc_term_freqs],
        }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> BM25SparseEmbedder:
        embedder = cls(k1=float(state["k1"]), b=float(state["b"]))
        embedder._doc_count = int(state["doc_count"])
        embedder._avg_doc_len = float(state["avg_doc_len"])
        embedder._doc_lengths = [int(v) for v in state["doc_lengths"]]
        embedder._idf = {str(k): float(v) for k, v in state["idf"].items()}
        embedder._doc_term_freqs = [
            Counter({str(k): int(v) for k, v in tf.items()})
            for tf in state["doc_term_freqs"]
        ]
        return embedder


class BM25Retriever:
    """Retriever built on top of BM25 sparse embeddings."""

    INDEX_VERSION = 1

    def __init__(
        self,
        *,
        index_path: str | Path | None = None,
        document_resolver: DocumentResolver | None = None,
    ) -> None:
        self.embedder = BM25SparseEmbedder()
        self._documents: list[Document] = []
        self._doc_vectors: list[dict[str, float]] = []
        self._index_path = Path(index_path) if index_path is not None else None
        self._document_resolver = document_resolver

    def build(self, documents: list[Document]) -> None:
        if not documents:
            raise ValueError("Cannot build retriever with an empty corpus")

        self._documents = documents
        self.embedder.fit(documents)
        self._doc_vectors = [self.embedder.encode_document(doc.text) for doc in documents]

        if self._index_path is not None:
            self.save_index(self._index_path, documents)

    def build_or_load(self, documents: list[Document], force_rebuild: bool = False) -> str:
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
                {"doc_id": doc.doc_id, "text": doc.text, "metadata": doc.metadata}
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
        if payload.get("fingerprint") != self._fingerprint_documents(documents):
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
            {str(k): float(v) for k, v in vec.items()} for vec in payload["doc_vectors"]
        ]
        return True

    def retrieve_ids(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        if not self._documents:
            raise ValueError("Retriever is not built")
        if top_k <= 0:
            return []

        scores = self.embedder.score_query_against_corpus(query)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [(self._documents[idx].doc_id, float(score)) for idx, score in ranked[:top_k]]

    @staticmethod
    def _fingerprint_documents(documents: list[Document]) -> str:
        hasher = hashlib.sha256()
        for doc in documents:
            hasher.update(doc.doc_id.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(doc.text.encode("utf-8"))
            hasher.update(b"\x00")
        return hasher.hexdigest()


class NomicDenseRetriever:
    """Bi-encoder retriever using nomic-embed-text-v1.5."""

    INDEX_VERSION = 1

    def __init__(
        self,
        *,
        model_name: str = "nomic-ai/nomic-embed-text-v1.5",
        matryoshka_dim: int = 512,
        batch_size: int = 16,
        show_progress_bar: bool = False,
        index_dir: str | Path | None = None,
        document_resolver: DocumentResolver | None = None,
    ) -> None:
        self.model_name = model_name
        self.matryoshka_dim = matryoshka_dim
        self.batch_size = batch_size
        self.show_progress_bar = show_progress_bar
        self.index_dir = Path(index_dir) if index_dir is not None else None
        self._document_resolver = document_resolver
        self._documents: list[Document] = []
        self._embeddings = None
        self._model = None

    def build(self, documents: list[Document]) -> None:
        if not documents:
            raise ValueError("Cannot build retriever with an empty corpus")

        model = self._get_model()
        self._documents = documents
        prefixed_docs = [f"search_document: {doc.text}" for doc in documents]
        embeddings = model.encode(
            prefixed_docs,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=self.show_progress_bar,
        )

        import numpy as np

        embeddings = np.asarray(embeddings, dtype=np.float32)
        embeddings = self._truncate_and_normalize(embeddings)
        self._embeddings = embeddings

        if self.index_dir is not None:
            self.save_index(self.index_dir, documents)

    def build_or_load(self, documents: list[Document], force_rebuild: bool = False) -> str:
        if self.index_dir is None:
            self.build(documents)
            return "built"

        if not force_rebuild and self.load_index(self.index_dir, documents):
            return "loaded"

        self.build(documents)
        return "built"

    def retrieve_ids(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        if not self._documents or self._embeddings is None:
            raise ValueError("Retriever is not built")
        if top_k <= 0:
            return []

        model = self._get_model()
        q = model.encode(
            [f"search_query: {query}"],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

        import numpy as np

        q_vec = self._truncate_and_normalize(np.asarray(q, dtype=np.float32))[0]
        scores = self._embeddings @ q_vec
        ranked_idx = np.argsort(scores)[::-1][:top_k]
        return [(self._documents[int(idx)].doc_id, float(scores[int(idx)])) for idx in ranked_idx]

    def save_index(self, index_dir: str | Path, documents: list[Document]) -> None:
        if self._embeddings is None:
            raise ValueError("Cannot persist dense index before build")

        import numpy as np

        path = Path(index_dir)
        path.mkdir(parents=True, exist_ok=True)
        meta = {
            "version": self.INDEX_VERSION,
            "model_name": self.model_name,
            "matryoshka_dim": self.matryoshka_dim,
            "fingerprint": self._fingerprint_documents(documents),
            "documents": [
                {"doc_id": doc.doc_id, "text": doc.text, "metadata": doc.metadata}
                for doc in documents
            ],
        }
        (path / "nomic_dense_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False),
            encoding="utf-8",
        )
        np.savez_compressed(path / "nomic_dense_vectors.npz", embeddings=self._embeddings)

    def load_index(self, index_dir: str | Path, documents: list[Document]) -> bool:
        import numpy as np

        path = Path(index_dir)
        meta_path = path / "nomic_dense_meta.json"
        vec_path = path / "nomic_dense_vectors.npz"
        if not meta_path.exists() or not vec_path.exists():
            return False

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("version") != self.INDEX_VERSION:
            return False
        if meta.get("model_name") != self.model_name:
            return False
        if int(meta.get("matryoshka_dim", 0)) != self.matryoshka_dim:
            return False
        if meta.get("fingerprint") != self._fingerprint_documents(documents):
            return False

        loaded = np.load(vec_path)
        embeddings = np.asarray(loaded["embeddings"], dtype=np.float32)
        self._embeddings = self._truncate_and_normalize(embeddings)
        self._documents = [
            Document(
                doc_id=item["doc_id"],
                text=item.get("text", ""),
                metadata=item.get("metadata", {}),
            )
            for item in meta["documents"]
        ]
        return True

    def _get_model(self):
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for dense retrieval"
            ) from exc

        self._model = SentenceTransformer(self.model_name, trust_remote_code=True)
        return self._model

    def _truncate_and_normalize(self, vectors):
        import numpy as np

        if vectors.ndim != 2:
            raise ValueError("Expected a 2D array of embeddings")

        dim = min(self.matryoshka_dim, vectors.shape[1])
        out = vectors[:, :dim]
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms = np.where(norms == 0.0, 1.0, norms)
        return out / norms

    @staticmethod
    def _fingerprint_documents(documents: list[Document]) -> str:
        hasher = hashlib.sha256()
        for doc in documents:
            hasher.update(doc.doc_id.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(doc.text.encode("utf-8"))
            hasher.update(b"\x00")
        return hasher.hexdigest()


class BM25DenseRankFusionRetriever:
    """Hybrid retriever using reciprocal rank fusion over BM25 and dense scores."""

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

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        ranked_ids = self.retrieve_ids(query, top_k=top_k)
        results: list[RetrievalResult] = []
        for doc_id, score in ranked_ids:
            text = ""
            doc_meta: dict[str, Any] = {}
            if self._document_resolver is not None:
                resolved = self._document_resolver(doc_id)
                if resolved is not None:
                    text, doc_meta = resolved
            results.append(
                RetrievalResult(
                    doc_id=doc_id,
                    score=float(score),
                    text=text,
                    metadata={
                        **doc_meta,
                        "retriever": "bm25_dense_rrf",
                        "rrf_k": self.rrf_k,
                        "bm25_weight": self.bm25_weight,
                        "dense_weight": self.dense_weight,
                    },
                )
            )
        return results

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


def _load_markdown_documents(corpus_dir: Path) -> list[Document]:
    if not corpus_dir.exists():
        raise FileNotFoundError(f"Corpus directory does not exist: {corpus_dir}")

    documents: list[Document] = []
    for md_file in sorted(corpus_dir.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        documents.append(
            Document(
                doc_id=md_file.stem,
                text=text,
                metadata={"source": str(md_file)},
            )
        )
    return documents


def _prepare_processed_corpus(raw_corpus_dir: Path, processed_corpus_dir: Path) -> None:
    """Initial baseline preprocessing: mirror raw markdown into processed folder."""
    if not raw_corpus_dir.exists():
        raise FileNotFoundError(f"Raw corpus directory does not exist: {raw_corpus_dir}")

    processed_corpus_dir.mkdir(parents=True, exist_ok=True)
    for raw_file in sorted(raw_corpus_dir.glob("*.md")):
        shutil.copy2(raw_file, processed_corpus_dir / raw_file.name)


def _load_dual_corpus_documents(
    raw_corpus_dir: Path,
    processed_corpus_dir: Path,
) -> tuple[list[Document], dict[str, Document]]:
    raw_docs = _load_markdown_documents(raw_corpus_dir)
    processed_docs = _load_markdown_documents(processed_corpus_dir)

    raw_by_id = {doc.doc_id: doc for doc in raw_docs}
    missing = [doc.doc_id for doc in processed_docs if doc.doc_id not in raw_by_id]
    if missing:
        raise ValueError(
            "Processed corpus contains doc_ids not found in raw corpus: "
            + ", ".join(sorted(missing))
        )

    with_raw_mapping: list[Document] = []
    for doc in processed_docs:
        raw_doc = raw_by_id[doc.doc_id]
        metadata = dict(doc.metadata)
        metadata["raw_source"] = raw_doc.metadata.get("source")
        metadata["processed_source"] = doc.metadata.get("source")
        with_raw_mapping.append(Document(doc_id=doc.doc_id, text=doc.text, metadata=metadata))

    return with_raw_mapping, raw_by_id


def _build_raw_document_resolver(raw_docs_by_id: dict[str, Document]) -> DocumentResolver:
    def _resolve(doc_id: str) -> tuple[str, dict[str, Any]] | None:
        doc = raw_docs_by_id.get(doc_id)
        if doc is None:
            return None
        return (doc.text, {"raw_source": doc.metadata["source"]})

    return _resolve


def _build_hybrid_retriever(scope: str = "default") -> BM25DenseRankFusionRetriever:
    from app.config import settings

    source_dir = Path(settings.RAG_SOURCES_DIR) / scope
    if not source_dir.exists():
        raise FileNotFoundError(f"RAG source directory not found: {source_dir}")

    raw_corpus_dir = source_dir / "corpus_raw"
    processed_corpus_dir = source_dir / "corpus_processed"
    bm25_index_path = source_dir / "indexes" / "bm25_index.json"
    dense_index_dir = source_dir / "indexes" / "nomic_dense"

    if not raw_corpus_dir.exists():
        raise FileNotFoundError(f"RAG raw corpus directory not found: {raw_corpus_dir}")

    if not processed_corpus_dir.exists() or not any(processed_corpus_dir.glob("*.md")):
        logger.info("Preparing processed corpus in %s", processed_corpus_dir)
        _prepare_processed_corpus(raw_corpus_dir, processed_corpus_dir)

    processed_docs, raw_docs_by_id = _load_dual_corpus_documents(
        raw_corpus_dir=raw_corpus_dir,
        processed_corpus_dir=processed_corpus_dir,
    )
    resolver = _build_raw_document_resolver(raw_docs_by_id)

    bm25 = BM25Retriever(index_path=bm25_index_path, document_resolver=resolver)
    bm25.build_or_load(processed_docs, force_rebuild=settings.RAG_FORCE_REBUILD_INDEXES)

    dense = NomicDenseRetriever(
        matryoshka_dim=settings.RAG_DENSE_MATRYOSHKA_DIM,
        batch_size=settings.RAG_DENSE_BATCH_SIZE,
        index_dir=dense_index_dir,
        document_resolver=resolver,
    )
    dense.build_or_load(processed_docs, force_rebuild=settings.RAG_FORCE_REBUILD_INDEXES)

    return BM25DenseRankFusionRetriever(
        bm25_retriever=bm25,
        dense_retriever=dense,
        rrf_k=settings.RAG_RRF_K,
        bm25_weight=settings.RAG_BM25_WEIGHT,
        dense_weight=settings.RAG_DENSE_WEIGHT,
        candidate_k=settings.RAG_CANDIDATE_K,
        document_resolver=resolver,
    )


def _get_retriever_for_scope(scope: str = "default") -> BM25DenseRankFusionRetriever:
    with _REGISTRY_LOCK:
        if scope not in _RETRIEVER_REGISTRY:
            _RETRIEVER_REGISTRY[scope] = _build_hybrid_retriever(scope)
    return _RETRIEVER_REGISTRY[scope]


def _format_retrieval_results(results: list[RetrievalResult]) -> str:
    if not results:
        return "No relevant documents found in RAG corpus."

    lines = ["RAG retrieval results:"]
    for idx, hit in enumerate(results, start=1):
        snippet = " ".join(hit.text.strip().split())
        if len(snippet) > 420:
            snippet = snippet[:420].rstrip() + "..."
        lines.append(
            f"{idx}. doc_id={hit.doc_id}; score={hit.score:.4f}; excerpt={snippet}"
        )
    return "\n".join(lines)


def _extract_title_from_text(text: str, fallback_doc_id: str) -> str:
    match = _HEADING_RE.search(text)
    if match:
        return match.group(1).strip()
    return fallback_doc_id


def _format_citation_results(results: list[RetrievalResult]) -> str:
    if not results:
        return "No citation candidates found in local literature corpus."

    lines = ["Citation candidates from local literature corpus:"]
    for idx, hit in enumerate(results, start=1):
        snippet = " ".join(hit.text.strip().split())
        if len(snippet) > 320:
            snippet = snippet[:320].rstrip() + "..."
        title = _extract_title_from_text(hit.text, hit.doc_id)
        source = hit.metadata.get("raw_source") or f"(unknown source for {hit.doc_id})"
        lines.append(
            f"{idx}. doc_id={hit.doc_id}; title={title}; source={source}; "
            f"score={hit.score:.4f}; excerpt={snippet}"
        )
    return "\n".join(lines)


def _run_rag_query(query: str, top_k: int, *, citation_mode: bool) -> str:
    from app.config import settings

    if not settings.RAG_ENABLED:
        return "RAG tool is disabled by configuration."
    if not query or not query.strip():
        return "Query must be a non-empty string."

    safe_top_k = min(max(int(top_k), 1), 10)
    try:
        retriever = _get_retriever_for_scope(settings.RAG_DEFAULT_SOURCE)
        results = retriever.retrieve(query.strip(), top_k=safe_top_k)
        if citation_mode:
            return _format_citation_results(results)
        return _format_retrieval_results(results)
    except FileNotFoundError as exc:
        logger.exception("RAG data is missing")
        return (
            "RAG data is not initialized correctly. "
            f"Missing path: {exc}."
        )
    except ImportError as exc:
        logger.exception("Dense retriever dependency missing")
        return (
            "RAG dense retriever dependencies are missing. "
            "Install sentence-transformers and numpy in ai-agent environment. "
            f"Details: {exc}"
        )
    except Exception as exc:
        logger.exception("RAG search failed")
        return f"RAG search failed: {exc}"


@tool
def rag_search(query: str, top_k: int = 4) -> str:
    """Search internal chemistry corpus with a hybrid BM25+dense retriever.

    Args:
        query: Natural-language chemistry question or retrieval query.
        top_k: Number of documents to return (default 4, max 10).
    """
    return _run_rag_query(query=query, top_k=top_k, citation_mode=False)


@tool
def literature_citation_search(topic: str, top_k: int = 5) -> str:
    """Find citation candidates from the local curated chemistry literature corpus.

    Use this tool when the user asks for references/citations from literature on a
    specific chemistry topic.

    Args:
        topic: Topic or question to search in local literature corpus.
        top_k: Number of citation candidates to return (default 5, max 10).
    """
    return _run_rag_query(query=topic, top_k=top_k, citation_mode=True)
