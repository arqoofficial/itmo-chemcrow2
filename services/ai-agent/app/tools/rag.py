"""Hybrid RAG tool for chemistry corpus retrieval.

This module provides two LangChain tool entry points — ``rag_search`` and
``literature_citation_search`` — that let the ChemCrow2 AI agent query a
locally-hosted chemistry corpus without any external API calls.

Retrieval strategy — BM25 + Nomic dense + RRF
----------------------------------------------
Retrieval is performed by ``BM25DenseRankFusionRetriever``, which runs two
independent rankers over the same corpus and merges their ranked lists using
**Reciprocal Rank Fusion (RRF)**:

1. **BM25 sparse retrieval** (``BM25Retriever`` / ``BM25SparseEmbedder``):
   A pure-Python implementation of the Okapi BM25 scoring function.  No
   external ML dependencies are required.  The fitted model and per-document
   term-frequency vectors are persisted to a single JSON file so that startup
   cost is paid only once.

2. **Nomic dense retrieval** (``NomicDenseRetriever``):
   Uses ``nomic-ai/nomic-embed-text-v1.5`` via ``sentence-transformers`` to
   produce 768-dimensional embeddings that are Matryoshka-truncated to
   ``matryoshka_dim`` (default 512) dimensions before cosine similarity is
   computed.  The model is baked into the Docker image at build time, so
   inference never requires a network call.  Embeddings are persisted as a
   compressed NumPy archive alongside a JSON metadata file.

3. **RRF fusion**:
   For each query, both retrievers independently return ``candidate_k``
   results.  The union of those candidate sets is re-ranked with the formula
   ``score(d) += weight / (k + rank(d))``, where ``k`` defaults to 60.  The
   constant ``k`` suppresses high-variance rank fluctuations at the top of
   each list while letting near-misses contribute meaningfully.

Data flow
---------
::

    compose bind mount (./services/ai-agent/app/data-rag)
        └── sources/
            └── <scope>/          ← e.g. "default"
                ├── corpus_raw/   ← authoritative .md files
                ├── corpus_processed/   ← pre-processed copies (or mirrors)
                └── indexes/
                    ├── bm25_index.json
                    └── nomic_dense/
                        ├── nomic_dense_meta.json
                        └── nomic_dense_vectors.npz

On first request for a scope the module:
  1. Creates ``corpus_processed`` by copying ``corpus_raw`` (if absent).
  2. Builds / loads BM25 and dense indexes, consulting document fingerprints
     to decide whether a cached index is still valid.
  3. Stores the live ``BM25DenseRankFusionRetriever`` in the module-level
     ``_RETRIEVER_REGISTRY`` keyed by scope name.  Subsequent requests return
     the cached retriever without re-loading from disk.

The ``DocumentResolver`` always returns **raw** document text so that the
agent receives the original, unmodified content even when retrieval ran over
pre-processed text.
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

# Module-level registry that keeps one retriever instance per scope alive for
# the lifetime of the process.  Avoids re-loading multi-hundred-MB numpy
# arrays on every query.
_RETRIEVER_REGISTRY: dict[str, BM25DenseRankFusionRetriever] = {}

# Protects _RETRIEVER_REGISTRY during first-build, which is not thread-safe
# because both BM25 fitting and dense encoding mutate instance state in place.
_REGISTRY_LOCK = Lock()


@dataclass(slots=True)
class Document:
    """A corpus document used by retrievers.

    Attributes:
        doc_id: Unique identifier (typically the markdown file stem).
        text: Full plain text content used for indexing.
        metadata: Arbitrary key/value pairs stored alongside the document
            (e.g. ``source`` file path, ``raw_source`` path).
    """

    doc_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalResult:
    """A single retrieval hit returned by a retriever.

    Attributes:
        doc_id: Identifier of the matched document.
        score: Retriever-specific relevance score (BM25 raw score, cosine
            similarity, or RRF fusion score depending on the retriever).
        text: Document text, populated by the ``DocumentResolver`` when one
            is attached to the retriever.
        metadata: Document metadata merged with retriever-level provenance
            keys (``retriever``, ``rrf_k``, etc.).
    """

    doc_id: str
    score: float
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# A callable that resolves a doc_id to its display content.
#
# Contract: given a ``doc_id`` string, return a ``(text, metadata)`` tuple
# where:
#   - ``text`` is the content to surface to the agent (typically the raw,
#     unprocessed version of the document).
#   - ``metadata`` is a dict of additional provenance fields.  The key
#     ``"raw_source"`` should hold the filesystem path of the authoritative
#     source file so that citation results can include a traceable reference.
#
# Return ``None`` if the doc_id is not found (the caller will leave text
# and metadata empty rather than raising).
DocumentResolver = Callable[[str], tuple[str, dict[str, Any]] | None]


class BM25SparseEmbedder:
    """BM25 sparse embedding model over tokenized text.

    Implements the Okapi BM25 ranking function without any external
    dependencies.  Supports both corpus-level fitting and per-query scoring.

    The tokenizer (``_tokenize``) is intentionally simple — it extracts
    alphanumeric runs from Latin and Cyrillic scripts — so that the same
    code works for both English and Russian chemistry literature.

    Attributes:
        k1: Term-frequency saturation parameter (default 1.5).  Higher values
            give more weight to term repetition.
        b: Length normalisation parameter (default 0.75).  1.0 = full
            normalisation by document length, 0.0 = no normalisation.
    """

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
    """Retriever built on top of BM25 sparse embeddings.

    Handles index persistence — saving the fitted model and all pre-computed
    document vectors to a single JSON file — so that the expensive fitting
    step only runs when the corpus changes.

    Attributes:
        INDEX_VERSION: Integer version tag embedded in the index file.
            Increment this when the serialisation format changes so that
            stale on-disk indexes are rejected and rebuilt automatically.
        embedder: The underlying ``BM25SparseEmbedder`` instance.
    """

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
        """Build the index from scratch or load a valid cached index from disk.

        Decides whether the on-disk index is still valid by comparing a
        SHA-256 fingerprint of the current document list against the
        fingerprint stored in the index file.  A mismatch (corpus changed)
        or a version mismatch triggers a full rebuild.

        Args:
            documents: The full list of ``Document`` objects that will back
                this retriever.
            force_rebuild: When ``True``, skip the cache check and always
                rebuild, even if a valid index exists on disk.

        Returns:
            ``"loaded"`` if the index was restored from disk, ``"built"`` if
            it was freshly computed and written to disk.
        """
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
        # Reject the cached index if the corpus has changed since it was built.
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
        """Return the top-k document IDs and their BM25 scores for a query.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            A list of ``(doc_id, score)`` tuples sorted by descending score,
            with at most ``top_k`` entries.

        Raises:
            ValueError: If the retriever has not been built or loaded yet.
        """
        if not self._documents:
            raise ValueError("Retriever is not built")
        if top_k <= 0:
            return []

        scores = self.embedder.score_query_against_corpus(query)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [(self._documents[idx].doc_id, float(score)) for idx, score in ranked[:top_k]]

    @staticmethod
    def _fingerprint_documents(documents: list[Document]) -> str:
        """Compute a SHA-256 fingerprint over doc_ids and texts.

        The fingerprint is used to detect whether the corpus has changed
        since an index was last built, avoiding stale cached indexes.
        Only ``doc_id`` and ``text`` are hashed; metadata changes alone do
        not trigger a rebuild.

        Args:
            documents: Ordered list of documents to fingerprint.

        Returns:
            Hex-encoded SHA-256 digest string.
        """
        hasher = hashlib.sha256()
        for doc in documents:
            hasher.update(doc.doc_id.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(doc.text.encode("utf-8"))
            hasher.update(b"\x00")
        return hasher.hexdigest()


class NomicDenseRetriever:
    """Bi-encoder dense retriever using nomic-embed-text-v1.5.

    Encodes documents and queries with the Nomic embedding model and ranks
    by cosine similarity.  Supports **Matryoshka Representation Learning**
    (MRL): the full 768-dimensional embeddings are truncated to
    ``matryoshka_dim`` dimensions and re-normalised before storage and
    similarity computation.  This trades a small amount of retrieval quality
    for significantly reduced memory and compute cost.

    The model is loaded lazily on first use (``_get_model``).  Because the
    Docker image pre-downloads the model weights at build time, inference
    never performs a network request.

    Index persistence uses two files:
      - ``nomic_dense_meta.json`` — document list, model parameters, and a
        corpus fingerprint for cache validation.
      - ``nomic_dense_vectors.npz`` — compressed float32 embedding matrix.

    Attributes:
        INDEX_VERSION: Integer version tag.  Increment when the index file
            format changes to force a rebuild on next startup.
        model_name: HuggingFace model identifier.
        matryoshka_dim: Target embedding dimensionality after MRL truncation.
        batch_size: Number of documents encoded per forward pass.
    """

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
        # Nomic requires a task-type prefix on both document and query strings.
        # "search_document:" is used at index time; "search_query:" at query time.
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
        """Build the dense index or load it from disk if still valid.

        Validation checks model name, ``matryoshka_dim``, index version, and
        the corpus fingerprint.  Any mismatch triggers a full rebuild.

        Args:
            documents: Corpus documents to index.
            force_rebuild: Skip validation and always re-encode the corpus.

        Returns:
            ``"loaded"`` if restored from disk, ``"built"`` if freshly encoded.
        """
        if self.index_dir is None:
            self.build(documents)
            return "built"

        if not force_rebuild and self.load_index(self.index_dir, documents):
            return "loaded"

        self.build(documents)
        return "built"

    def retrieve_ids(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Return the top-k document IDs and cosine similarity scores for a query.

        The query is prefixed with ``"search_query: "`` as required by the
        Nomic instruction-tuned embedding model before encoding.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            A list of ``(doc_id, cosine_similarity)`` tuples sorted by
            descending similarity, with at most ``top_k`` entries.

        Raises:
            ValueError: If the retriever has not been built or loaded yet.
        """
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
        # Matrix–vector dot product is equivalent to cosine similarity because
        # both the corpus embeddings and the query vector are L2-normalised.
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
        # Reject cache if corpus content has changed since the index was built.
        if meta.get("fingerprint") != self._fingerprint_documents(documents):
            return False

        loaded = np.load(vec_path)
        embeddings = np.asarray(loaded["embeddings"], dtype=np.float32)
        # Re-apply truncation+normalisation on load in case matryoshka_dim
        # was changed between builds (the guard above would have caught it,
        # but this is an extra safety measure).
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

        # MRL truncation: keep only the first `matryoshka_dim` dimensions.
        # The Nomic model is trained so that prefix sub-vectors are already
        # semantically meaningful, making this lossless in practice.
        dim = min(self.matryoshka_dim, vectors.shape[1])
        out = vectors[:, :dim]
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        # Guard against zero-norm vectors (e.g. empty documents) to avoid NaN.
        norms = np.where(norms == 0.0, 1.0, norms)
        return out / norms

    @staticmethod
    def _fingerprint_documents(documents: list[Document]) -> str:
        """Compute a SHA-256 fingerprint over doc_ids and texts.

        Args:
            documents: Ordered list of documents to fingerprint.

        Returns:
            Hex-encoded SHA-256 digest string.
        """
        hasher = hashlib.sha256()
        for doc in documents:
            hasher.update(doc.doc_id.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(doc.text.encode("utf-8"))
            hasher.update(b"\x00")
        return hasher.hexdigest()


class BM25DenseRankFusionRetriever:
    """Hybrid retriever using Reciprocal Rank Fusion (RRF) over BM25 and dense scores.

    Combines the lexical precision of BM25 with the semantic recall of dense
    embeddings.  Neither ranker's raw scores are compared directly — instead,
    only the **rank positions** from each ranker contribute to the final score,
    making the fusion robust to score-scale differences between the two methods.

    RRF formula applied to each candidate document ``d``:

    .. code-block:: text

        fusion_score(d) = bm25_weight / (rrf_k + rank_bm25(d))
                        + dense_weight / (rrf_k + rank_dense(d))

    The constant ``rrf_k`` (default 60, from the original RRF paper by
    Cormack et al.) ensures that a document ranked #1 by one method but
    absent from the other still receives a reasonable score, preventing
    winner-takes-all behaviour.

    Attributes:
        bm25_retriever: The BM25 ranker.
        dense_retriever: The Nomic dense ranker.
        rrf_k: RRF smoothing constant.  Larger values flatten the rank
            contribution curve, reducing the dominance of top-ranked results.
        bm25_weight: Multiplicative weight applied to BM25 rank contributions.
        dense_weight: Multiplicative weight applied to dense rank contributions.
        candidate_k: Number of candidates each sub-retriever fetches before
            fusion.  Must be >= ``top_k`` at query time; the effective union
            is ``max(top_k, candidate_k)``.
    """

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
        """Retrieve the top-k documents for a query using RRF-fused ranking.

        After fusion ranks are computed by ``retrieve_ids``, the
        ``DocumentResolver`` is called for each result to populate ``text``
        and ``metadata``.  Retriever-level provenance keys (``retriever``,
        ``rrf_k``, ``bm25_weight``, ``dense_weight``) are merged into the
        metadata dict, overriding any identically-named document-level keys.

        Args:
            query: The search query string.
            top_k: Number of documents to return.

        Returns:
            A list of ``RetrievalResult`` objects sorted by descending fusion
            score, with at most ``top_k`` entries.
        """
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
                        **doc_meta,  # doc_meta keys are overridden by retriever-level metadata below
                        "retriever": "bm25_dense_rrf",
                        "rrf_k": self.rrf_k,
                        "bm25_weight": self.bm25_weight,
                        "dense_weight": self.dense_weight,
                    },
                )
            )
        return results

    def retrieve_ids(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        """Compute RRF-fused rankings and return the top-k (doc_id, score) pairs.

        Both sub-retrievers are asked for ``max(top_k, candidate_k)``
        candidates.  The union of those two lists is scored with the RRF
        formula, then sorted descending and truncated to ``top_k``.

        Documents that appear in only one ranker's list still receive a
        partial RRF score via that ranker's ``weight / (rrf_k + rank)``
        contribution.

        Args:
            query: The search query string.
            top_k: Number of fused results to return.

        Returns:
            A list of ``(doc_id, rrf_score)`` tuples sorted by descending
            fusion score, with at most ``top_k`` entries.
        """
        if top_k <= 0:
            return []

        retrieve_k = max(top_k, self.candidate_k)
        bm25_ids = self.bm25_retriever.retrieve_ids(query, top_k=retrieve_k)
        dense_ids = self.dense_retriever.retrieve_ids(query, top_k=retrieve_k)

        # RRF: accumulate rank-based scores from each retriever.
        # Rank is 1-based so that the best document contributes
        # weight / (rrf_k + 1) rather than weight / rrf_k.
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
    """Create a ``DocumentResolver`` that returns raw (unprocessed) document text.

    Using raw text as the resolver output means the agent always receives the
    original, unmodified source content in its context window, even when
    retrieval was performed over a pre-processed version of the corpus.  This
    preserves formatting, formulas, and citations that pre-processing might
    strip.

    The returned metadata dict contains a single key ``"raw_source"`` whose
    value is the filesystem path to the source ``.md`` file, satisfying the
    ``DocumentResolver`` contract for citation traceability.

    Args:
        raw_docs_by_id: Mapping from ``doc_id`` to the corresponding raw
            ``Document`` object.

    Returns:
        A ``DocumentResolver`` closure over ``raw_docs_by_id``.
    """
    def _resolve(doc_id: str) -> tuple[str, dict[str, Any]] | None:
        doc = raw_docs_by_id.get(doc_id)
        if doc is None:
            return None
        return (doc.text, {"raw_source": doc.metadata["source"]})

    return _resolve


def _build_hybrid_retriever(scope: str = "default") -> BM25DenseRankFusionRetriever:
    """Construct a fully initialised ``BM25DenseRankFusionRetriever`` for a scope.

    A **scope** maps to a subdirectory under ``RAG_SOURCES_DIR``.  The
    directory layout expected under ``<RAG_SOURCES_DIR>/<scope>/`` is:

    .. code-block:: text

        corpus_raw/          ← mandatory; one .md file per document
        corpus_processed/    ← auto-created as a mirror of corpus_raw if absent
        indexes/
            bm25_index.json
            nomic_dense/
                nomic_dense_meta.json
                nomic_dense_vectors.npz

    Both retrievers consult the corpus fingerprint stored in their respective
    index files.  If the fingerprint matches the current corpus, the cached
    index is loaded instead of rebuilt.  ``RAG_FORCE_REBUILD_INDEXES=true``
    bypasses this check.

    The ``DocumentResolver`` passed to all components always serves raw
    document text, so the agent sees original content regardless of
    pre-processing applied in ``corpus_processed``.

    Args:
        scope: Name of the source subdirectory (default ``"default"``).

    Returns:
        A ready-to-query ``BM25DenseRankFusionRetriever``.

    Raises:
        FileNotFoundError: If the scope directory or ``corpus_raw`` is absent.
    """
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
    """Return the cached retriever for *scope*, building it on first access.

    The module-level ``_RETRIEVER_REGISTRY`` dict maps scope names to live
    retriever instances.  Because building a retriever involves CPU-intensive
    BM25 fitting and potentially GPU-accelerated dense encoding, we want to
    do this exactly once per process lifetime.

    The ``_REGISTRY_LOCK`` ensures that two concurrent requests for the same
    scope do not race to build it simultaneously.  The lock is held for the
    entire build so that no partially-initialised retriever is ever returned.

    Args:
        scope: Source scope name (default ``"default"``).

    Returns:
        A ready-to-query ``BM25DenseRankFusionRetriever``.
    """
    # Hold the lock for the entire build — not just the registry check — to
    # prevent a second thread from starting a duplicate build while the first
    # is still running.  Builds are infrequent (once per scope per process)
    # so the coarse lock is acceptable.
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
    """Format retrieval results as structured citation candidates for the agent.

    Produces a numbered list where each entry includes the document title
    (extracted from the first Markdown heading, or the ``doc_id`` as
    fallback), the filesystem path via ``raw_source`` for traceability, an
    RRF score, and a 320-character excerpt.

    This output is designed for ``literature_citation_search``: the agent can
    use the ``source`` path and ``title`` to construct a proper citation
    rather than just quoting a snippet.

    Args:
        results: Ordered list of ``RetrievalResult`` objects from the hybrid
            retriever.

    Returns:
        A human-readable string suitable for inclusion in the agent's context.
    """
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
    """Execute a RAG query and return a formatted string result for the agent.

    This is the single implementation shared by both ``rag_search`` and
    ``literature_citation_search``.  The ``citation_mode`` flag selects
    whether the output is formatted as generic retrieval results or as
    structured citation candidates.

    The function clamps ``top_k`` to ``[1, 10]`` before querying, so callers
    cannot request an arbitrarily large retrieval set.

    Args:
        query: The search query or topic string.
        top_k: Requested number of results (clamped to 1–10).
        citation_mode: When ``True``, output includes document titles and
            source paths in addition to the text excerpt.

    Returns:
        A formatted multi-line string describing the retrieval results, or a
        plain error message if RAG is disabled or an exception was raised.
        Never raises — all exceptions are caught and returned as messages so
        that the agent can reason about the failure.
    """
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
