from __future__ import annotations

from pathlib import Path

from .base import Document
from .bm25_retriever import BM25Retriever


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


def build_bm25_retriever_from_eval_chunks(eval_chunks: dict) -> BM25Retriever:
    """Build retriever specifically for eval chunks."""
    documents = load_chunks_from_eval(eval_chunks)
    retriever = BM25Retriever()
    retriever.build(documents)
    return retriever
