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

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _build_retriever() -> tuple[BM25DenseRankFusionRetriever, dict[str, str]]:
    retriever = rag_module._build_hybrid_retriever(settings.RAG_DEFAULT_SOURCE)
    sources: dict[str, str] = {}
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
        source_path = hit.metadata.get("source") or sources.get(hit.doc_id, f"(unknown source for {hit.doc_id})")
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
