from __future__ import annotations

import math
import re
from collections import Counter

from .base import Document, SparseEmbedder

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]+")


class BM25SparseEmbedder(SparseEmbedder):
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

        # Standard BM25 idf with +1 inside log for numerical stability.
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

    def encode_query(self, query: str) -> dict[str, float]:
        tokens = self._tokenize(query)
        tf = Counter(tokens)
        return {
            term: self._idf.get(term, 0.0) * freq
            for term, freq in tf.items()
            if term in self._idf
        }

    def score_query_against_corpus(self, query: str) -> list[float]:
        """Efficient BM25 scoring of query against all indexed documents."""
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
