from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

import numpy as np

from .base import BaseRetriever, Document, RetrievalResult


DocumentResolver = Callable[[str], str | None]


class NomicDenseRetriever(BaseRetriever):
	"""Bi-encoder retriever using nomic-embed-text-v1.5."""

	INDEX_VERSION = 1

	def __init__(
		self,
		*,
		model_name: str = "nomic-ai/nomic-embed-text-v1.5",
		matryoshka_dim: int = 512,
		batch_size: int = 16,
		show_progress_bar: bool = True,
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
		self._embeddings: np.ndarray | None = None
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

	def retrieve(self, query: str, top_k: int = 5) -> list[RetrievalResult]:
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
		q_vec = self._truncate_and_normalize(np.asarray(q, dtype=np.float32))[0]

		scores = self._embeddings @ q_vec
		ranked_idx = np.argsort(scores)[::-1][:top_k]

		results: list[RetrievalResult] = []
		for idx in ranked_idx:
			doc = self._documents[int(idx)]
			text = doc.text
			if self._document_resolver is not None:
				resolved = self._document_resolver(doc.doc_id)
				if resolved is not None:
					text = resolved
			results.append(
				RetrievalResult(
					doc_id=doc.doc_id,
					score=float(scores[int(idx)]),
					text=text,
					metadata=doc.metadata,
				)
			)
		return results

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
		q_vec = self._truncate_and_normalize(np.asarray(q, dtype=np.float32))[0]

		scores = self._embeddings @ q_vec
		ranked_idx = np.argsort(scores)[::-1][:top_k]
		return [
			(self._documents[int(idx)].doc_id, float(scores[int(idx)]))
			for idx in ranked_idx
		]

	def save_index(self, index_dir: str | Path, documents: list[Document]) -> None:
		if self._embeddings is None:
			raise ValueError("Cannot persist dense index before build")

		path = Path(index_dir)
		path.mkdir(parents=True, exist_ok=True)

		meta = {
			"version": self.INDEX_VERSION,
			"model_name": self.model_name,
			"matryoshka_dim": self.matryoshka_dim,
			"fingerprint": self._fingerprint_documents(documents),
			"documents": [
				{
					"doc_id": doc.doc_id,
					"text": doc.text,
					"metadata": doc.metadata,
				}
				for doc in documents
			],
		}

		(path / "nomic_dense_meta.json").write_text(
			json.dumps(meta, ensure_ascii=False),
			encoding="utf-8",
		)
		np.savez_compressed(path / "nomic_dense_vectors.npz", embeddings=self._embeddings)

	def load_index(self, index_dir: str | Path, documents: list[Document]) -> bool:
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

	def set_document_resolver(self, resolver: DocumentResolver | None) -> None:
		self._document_resolver = resolver

	def _get_model(self):
		if self._model is not None:
			return self._model

		try:
			from sentence_transformers import SentenceTransformer
		except ImportError as exc:
			raise ImportError(
				"sentence-transformers is required for NomicDenseRetriever"
			) from exc

		self._model = SentenceTransformer(self.model_name, trust_remote_code=True)
		return self._model

	def _truncate_and_normalize(self, vectors: np.ndarray) -> np.ndarray:
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
