from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from .base import Document
from .bm25_retriever import BM25Retriever
from .fusion_retriever import BM25DenseRankFusionRetriever
from .nomic_dense_retriever import NomicDenseRetriever


def load_markdown_documents(corpus_dir: str | Path) -> list[Document]:
    path = Path(corpus_dir)
    if not path.exists():
        raise FileNotFoundError(f"Corpus directory does not exist: {path}")

    documents: list[Document] = []
    for md_file in sorted(path.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        documents.append(
            Document(
                doc_id=md_file.stem,
                text=text,
                metadata={"source": str(md_file)},
            )
        )
    return documents


def prepare_processed_corpus(
    raw_corpus_dir: str | Path,
    processed_corpus_dir: str | Path,
) -> list[Path]:
    """Mirror raw markdown files into processed directory as an initial baseline."""
    raw = Path(raw_corpus_dir)
    processed = Path(processed_corpus_dir)

    if not raw.exists():
        raise FileNotFoundError(f"Raw corpus directory does not exist: {raw}")

    processed.mkdir(parents=True, exist_ok=True)

    copied_files: list[Path] = []
    for raw_file in sorted(raw.glob("*.md")):
        dst = processed / raw_file.name
        shutil.copy2(raw_file, dst)
        copied_files.append(dst)
    return copied_files


def load_dual_corpus_documents(
    raw_corpus_dir: str | Path,
    processed_corpus_dir: str | Path,
) -> tuple[list[Document], dict[str, Document]]:
    """Load processed docs for retrieval and raw docs for final hydration by doc_id."""
    raw_docs = load_markdown_documents(raw_corpus_dir)
    processed_docs = load_markdown_documents(processed_corpus_dir)

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
        with_raw_mapping.append(
            Document(doc_id=doc.doc_id, text=doc.text, metadata=metadata)
        )

    return with_raw_mapping, raw_by_id


def build_raw_document_resolver(raw_docs_by_id: dict[str, Document]) -> Callable[[str], str | None]:
    """Build resolver that maps retrieved doc_id to raw corpus text."""

    def _resolve(doc_id: str) -> str | None:
        doc = raw_docs_by_id.get(doc_id)
        if doc is None:
            return None
        return doc.text

    return _resolve


def load_chunks_from_eval(eval_chunks: dict) -> list[Document]:
    """Load chunks from eval_queries EVAL_CHUNKS dict."""
    documents: list[Document] = []
    for chunk_id, data in eval_chunks.items():
        documents.append(
            Document(
                doc_id=chunk_id,
                text=data["text"],
                metadata={"type": "eval_chunk"},
            )
        )
    return documents


def build_bm25_retriever(corpus_dir: str | Path) -> BM25Retriever:
    documents = load_markdown_documents(corpus_dir)
    retriever = BM25Retriever()
    retriever.build(documents)
    return retriever


def build_bm25_retriever_from_processed(
    raw_corpus_dir: str | Path,
    processed_corpus_dir: str | Path,
    *,
    index_path: str | Path | None = None,
    force_rebuild: bool = False,
) -> BM25Retriever:
    processed_docs, raw_docs_by_id = load_dual_corpus_documents(
        raw_corpus_dir=raw_corpus_dir,
        processed_corpus_dir=processed_corpus_dir,
    )
    resolver = build_raw_document_resolver(raw_docs_by_id)
    retriever = BM25Retriever(index_path=index_path, document_resolver=resolver)
    retriever.build_or_load(processed_docs, force_rebuild=force_rebuild)
    return retriever


def build_bm25_retriever_from_eval_chunks(eval_chunks: dict) -> BM25Retriever:
    """Build retriever specifically for eval chunks."""
    documents = load_chunks_from_eval(eval_chunks)
    retriever = BM25Retriever()
    retriever.build(documents)
    return retriever


def build_nomic_dense_retriever_from_processed(
    raw_corpus_dir: str | Path,
    processed_corpus_dir: str | Path,
    *,
    index_dir: str | Path | None = None,
    matryoshka_dim: int = 512,
    batch_size: int = 16,
    force_rebuild: bool = False,
) -> NomicDenseRetriever:
    processed_docs, raw_docs_by_id = load_dual_corpus_documents(
        raw_corpus_dir=raw_corpus_dir,
        processed_corpus_dir=processed_corpus_dir,
    )
    resolver = build_raw_document_resolver(raw_docs_by_id)
    retriever = NomicDenseRetriever(
        matryoshka_dim=matryoshka_dim,
        batch_size=batch_size,
        index_dir=index_dir,
        document_resolver=resolver,
    )
    retriever.build_or_load(processed_docs, force_rebuild=force_rebuild)
    return retriever


def build_bm25_dense_fusion_retriever_from_processed(
    raw_corpus_dir: str | Path,
    processed_corpus_dir: str | Path,
    *,
    bm25_index_path: str | Path | None = None,
    dense_index_dir: str | Path | None = None,
    matryoshka_dim: int = 512,
    batch_size: int = 16,
    rrf_k: int = 60,
    bm25_weight: float = 1.0,
    dense_weight: float = 1.0,
    candidate_k: int = 20,
    force_rebuild: bool = False,
) -> BM25DenseRankFusionRetriever:
    processed_docs, raw_docs_by_id = load_dual_corpus_documents(
        raw_corpus_dir=raw_corpus_dir,
        processed_corpus_dir=processed_corpus_dir,
    )
    resolver = build_raw_document_resolver(raw_docs_by_id)

    bm25 = BM25Retriever(index_path=bm25_index_path, document_resolver=resolver)
    bm25.build_or_load(processed_docs, force_rebuild=force_rebuild)

    dense = NomicDenseRetriever(
        matryoshka_dim=matryoshka_dim,
        batch_size=batch_size,
        index_dir=dense_index_dir,
        document_resolver=resolver,
    )
    dense.build_or_load(processed_docs, force_rebuild=force_rebuild)

    return BM25DenseRankFusionRetriever(
        bm25_retriever=bm25,
        dense_retriever=dense,
        rrf_k=rrf_k,
        bm25_weight=bm25_weight,
        dense_weight=dense_weight,
        candidate_k=candidate_k,
        document_resolver=resolver,
    )
