from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SparseEmbedder(ABC):
    """Base class for sparse embedding models."""

    @abstractmethod
    def fit(self, documents: list[Document]) -> None:
        """Fit the sparse model on documents."""

    @abstractmethod
    def encode_document(self, text: str) -> dict[str, float]:
        """Encode a document into a sparse vector representation."""

    @abstractmethod
    def encode_query(self, query: str) -> dict[str, float]:
        """Encode a user query into a sparse vector representation."""


class BaseRetriever(ABC):
    """Base class for retrievers."""

    @abstractmethod
    def build(self, documents: list[Document]) -> None:
        """Build retrieval index from documents."""

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
        """Retrieve most relevant documents for a query."""
