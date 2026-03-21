from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


config_module = _load_module("ai_agent_config", PROJECT_ROOT / "app" / "config.py")
rag_module = _load_module("ai_agent_rag", PROJECT_ROOT / "app" / "tools" / "rag.py")

settings = config_module.settings
BM25DenseRankFusionRetriever = rag_module.BM25DenseRankFusionRetriever
BM25Retriever = rag_module.BM25Retriever
NomicDenseRetriever = rag_module.NomicDenseRetriever
_build_raw_document_resolver = rag_module._build_raw_document_resolver
_load_dual_corpus_documents = rag_module._load_dual_corpus_documents
_prepare_processed_corpus = rag_module._prepare_processed_corpus

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _build_retriever() -> tuple[BM25DenseRankFusionRetriever, dict[str, str]]:
    raw_corpus_dir = Path(settings.RAG_CORPUS_RAW_DIR)
    processed_corpus_dir = Path(settings.RAG_CORPUS_PROCESSED_DIR)
    bm25_index_path = Path(settings.RAG_BM25_INDEX_PATH)
    dense_index_dir = Path(settings.RAG_DENSE_INDEX_DIR)

    if not raw_corpus_dir.exists():
        raise FileNotFoundError(f"RAG raw corpus directory not found: {raw_corpus_dir}")

    if not processed_corpus_dir.exists() or not any(processed_corpus_dir.glob("*.md")):
        _prepare_processed_corpus(raw_corpus_dir, processed_corpus_dir)

    processed_docs, raw_docs_by_id = _load_dual_corpus_documents(raw_corpus_dir, processed_corpus_dir)
    resolver = _build_raw_document_resolver(raw_docs_by_id)

    bm25 = BM25Retriever(index_path=bm25_index_path, document_resolver=resolver)
    bm25.build_or_load(processed_docs, force_rebuild=settings.RAG_FORCE_REBUILD_INDEXES)

    dense = NomicDenseRetriever(
        matryoshka_dim=settings.RAG_DENSE_MATRYOSHKA_DIM,
        batch_size=settings.RAG_DENSE_BATCH_SIZE,
        index_dir=dense_index_dir,
        document_resolver=resolver,
        show_progress_bar=False,
    )
    dense.build_or_load(processed_docs, force_rebuild=settings.RAG_FORCE_REBUILD_INDEXES)

    retriever = BM25DenseRankFusionRetriever(
        bm25_retriever=bm25,
        dense_retriever=dense,
        rrf_k=settings.RAG_RRF_K,
        bm25_weight=settings.RAG_BM25_WEIGHT,
        dense_weight=settings.RAG_DENSE_WEIGHT,
        candidate_k=settings.RAG_CANDIDATE_K,
        document_resolver=resolver,
    )

    sources = {
        doc_id: raw_doc.metadata.get("source", f"{settings.RAG_CORPUS_RAW_DIR}/{doc_id}.md")
        for doc_id, raw_doc in raw_docs_by_id.items()
    }
    return retriever, sources


def _extract_title(text: str, fallback_doc_id: str) -> str:
    match = _HEADING_RE.search(text)
    if match:
        return match.group(1).strip()
    return fallback_doc_id


def _print_results(query: str, retriever: BM25DenseRankFusionRetriever, sources: dict[str, str], top_k: int) -> None:
    results = retriever.retrieve(query=query, top_k=top_k)
    if not results:
        print("No relevant documents found.")
        return

    print(f"Top {top_k} fused RAG sources for query: {query}")
    for idx, hit in enumerate(results, start=1):
        source_path = sources.get(hit.doc_id, f"{settings.RAG_CORPUS_RAW_DIR}/{hit.doc_id}.md")
        title = _extract_title(hit.text, hit.doc_id)
        excerpt = " ".join(hit.text.strip().split())
        if len(excerpt) > 260:
            excerpt = excerpt[:260].rstrip() + "..."

        print(f"{idx}. title={title}")
        print(f"   doc_id={hit.doc_id}")
        print(f"   score={hit.score:.4f}")
        print(f"   source={source_path}")
        print(f"   excerpt={excerpt}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run fused RAG (BM25 + dense RRF) and print top relevant sources.",
    )
    parser.add_argument("query", nargs="?", help="Query to search in local RAG corpus")
    parser.add_argument("--top-k", type=int, default=3, help="How many sources to print (default: 3)")
    args = parser.parse_args()

    top_k = min(max(args.top_k, 1), 10)
    if not settings.RAG_ENABLED:
        raise RuntimeError("RAG is disabled by configuration (RAG_ENABLED=false)")

    retriever, sources = _build_retriever()

    if args.query:
        _print_results(args.query.strip(), retriever, sources, top_k)
        return

    query = input("Enter your query: ").strip()
    if not query:
        print("Query must be a non-empty string.")
        return
    _print_results(query, retriever, sources, top_k)


if __name__ == "__main__":
    main()
