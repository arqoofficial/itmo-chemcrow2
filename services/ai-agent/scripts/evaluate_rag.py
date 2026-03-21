from __future__ import annotations

import argparse
import importlib.util
import json
import math
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Protocol

from app.config import settings


def _load_rag_module():
    script_root = Path(__file__).resolve().parents[1]
    rag_path = script_root / "app" / "tools" / "rag.py"
    spec = importlib.util.spec_from_file_location("rag_module", rag_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load rag module from {rag_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rag_module = _load_rag_module()
BM25DenseRankFusionRetriever = rag_module.BM25DenseRankFusionRetriever
BM25Retriever = rag_module.BM25Retriever
NomicDenseRetriever = rag_module.NomicDenseRetriever
_build_canonical_document_resolver = rag_module._build_canonical_document_resolver
_load_chunked_processed_corpus = rag_module._load_chunked_processed_corpus


class SupportsRetrieveIds(Protocol):
    def retrieve_ids(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        ...


def flatten_queries(queries: dict[str, list[str]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for doc_id, items in queries.items():
        for query in items:
            pairs.append((doc_id, query))
    return pairs


def evaluate_model(name: str, retriever: SupportsRetrieveIds, pairs: list[tuple[str, str]], top_k: int) -> dict:
    top1_hits = 0
    topk_hits = 0
    mrr_sum = 0.0
    ndcg_sum = 0.0

    for expected_doc_id, query in pairs:
        ranked = retriever.retrieve_ids(query, top_k=top_k)
        ranked_ids = [doc_id for doc_id, _ in ranked]

        rank = None
        for i, doc_id in enumerate(ranked_ids, start=1):
            if doc_id == expected_doc_id:
                rank = i
                break

        if ranked_ids and ranked_ids[0] == expected_doc_id:
            top1_hits += 1
        if rank is not None:
            topk_hits += 1
            mrr_sum += 1.0 / rank
            ndcg_sum += 1.0 / math.log2(rank + 1)

    n = len(pairs)
    if n == 0:
        raise ValueError("No benchmark queries found")

    return {
        "name": name,
        "queries": n,
        "top1": top1_hits / n,
        f"hit@{top_k}": topk_hits / n,
        "mrr": mrr_sum / n,
        f"ndcg@{top_k}": ndcg_sum / n,
    }


def run_dense_rebuild_check(processed_docs: list, matryoshka_dim: int, batch_size: int) -> dict:
    # Rebuild check is intentionally run on a small subset to keep diagnostics fast.
    small_docs = processed_docs[: min(len(processed_docs), 4)]

    with tempfile.TemporaryDirectory(prefix="rag_dense_rebuild_") as tmpdir:
        tmp_index_dir = Path(tmpdir) / "nomic_dense"

        dense = NomicDenseRetriever(
            model_name=settings.RAG_EMBEDDING_MODEL,
            matryoshka_dim=matryoshka_dim,
            batch_size=batch_size,
            index_dir=tmp_index_dir,
            show_progress_bar=False,
        )

        t0 = time.perf_counter()
        first_status = dense.build_or_load(small_docs, force_rebuild=False)
        t1 = time.perf_counter()

        meta_exists_after_build = (tmp_index_dir / "nomic_dense_meta.json").exists()
        vectors_exists_after_build = (tmp_index_dir / "nomic_dense_vectors.npz").exists()

        # Simulate accidental index deletion and ensure rebuild still works.
        shutil.rmtree(tmp_index_dir)

        t2 = time.perf_counter()
        second_status = dense.build_or_load(small_docs, force_rebuild=False)
        t3 = time.perf_counter()

        meta_exists_after_rebuild = (tmp_index_dir / "nomic_dense_meta.json").exists()
        vectors_exists_after_rebuild = (tmp_index_dir / "nomic_dense_vectors.npz").exists()

        sample = dense.retrieve_ids("ретросинтетический анализ", top_k=3)

    return {
        "first_status": first_status,
        "first_build_seconds": round(t1 - t0, 3),
        "second_status_after_delete": second_status,
        "second_build_seconds": round(t3 - t2, 3),
        "meta_exists_after_build": meta_exists_after_build,
        "vectors_exists_after_build": vectors_exists_after_build,
        "meta_exists_after_rebuild": meta_exists_after_rebuild,
        "vectors_exists_after_rebuild": vectors_exists_after_rebuild,
        "sample_retrieval_count": len(sample),
        "sample_top_doc": sample[0][0] if sample else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate BM25 vs Dense vs Fusion on data-rag benchmark")
    parser.add_argument("--top-k", type=int, default=5, help="Top-k for hit-rate and ranking metrics")
    parser.add_argument(
        "--max-queries",
        type=int,
        default=12,
        help="Optional cap on number of benchmark queries to evaluate (default 12 for faster local runs)",
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path(settings.RAG_DATA_DIR) / "benchmarks" / "chapter_eval_queries.json",
        help="Path to benchmark queries JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(settings.RAG_DATA_DIR) / "benchmarks" / "latest_eval_results.json",
        help="Path to save JSON report",
    )
    args = parser.parse_args()

    source_dir = Path(settings.RAG_SOURCES_DIR) / settings.RAG_DEFAULT_SOURCE
    processed_corpus_dir = source_dir / "corpus_processed"
    bm25_index_path = source_dir / "indexes" / "bm25_index.json"
    dense_index_dir = source_dir / "indexes" / "nomic_dense"

    queries_by_doc = json.loads(args.queries.read_text(encoding="utf-8"))
    pairs = flatten_queries(queries_by_doc)
    if args.max_queries > 0:
        pairs = pairs[: args.max_queries]

    bundle = _load_chunked_processed_corpus(processed_corpus_dir)
    resolver = _build_canonical_document_resolver(bundle.canonical_documents_by_id)

    bm25 = BM25Retriever(index_path=bm25_index_path, document_resolver=resolver)
    bm25.build_or_load(bundle.bm25_documents, force_rebuild=False)

    dense = NomicDenseRetriever(
        model_name=settings.RAG_EMBEDDING_MODEL,
        matryoshka_dim=settings.RAG_DENSE_MATRYOSHKA_DIM,
        batch_size=settings.RAG_DENSE_BATCH_SIZE,
        index_dir=dense_index_dir,
        document_resolver=resolver,
        show_progress_bar=False,
    )
    dense.build_or_load(bundle.dense_documents, force_rebuild=False)

    fusion = BM25DenseRankFusionRetriever(
        bm25_retriever=bm25,
        dense_retriever=dense,
        rrf_k=settings.RAG_RRF_K,
        bm25_weight=settings.RAG_BM25_WEIGHT,
        dense_weight=settings.RAG_DENSE_WEIGHT,
        candidate_k=settings.RAG_CANDIDATE_K,
        bm25_to_canonical_doc_id=bundle.bm25_to_canonical_doc_id,
        document_resolver=resolver,
    )

    model_results = [
        evaluate_model("bm25", bm25, pairs, args.top_k),
        evaluate_model("dense_nomic", dense, pairs, args.top_k),
        evaluate_model("fusion_rrf", fusion, pairs, args.top_k),
    ]

    best_by_top1 = max(model_results, key=lambda row: row["top1"])
    best_by_mrr = max(model_results, key=lambda row: row["mrr"])

    try:
        rebuild_check = run_dense_rebuild_check(
            bundle.dense_documents,
            matryoshka_dim=settings.RAG_DENSE_MATRYOSHKA_DIM,
            batch_size=settings.RAG_DENSE_BATCH_SIZE,
        )
    except KeyboardInterrupt:
        rebuild_check = {
            "status": "interrupted",
            "message": "Dense rebuild diagnostic was interrupted",
        }

    report = {
        "benchmark": {
            "queries_path": str(args.queries),
            "processed_corpus_dir": str(processed_corpus_dir),
            "source_dir": str(source_dir),
            "query_count": len(pairs),
            "top_k": args.top_k,
        },
        "models": model_results,
        "best_model": {
            "by_top1": best_by_top1["name"],
            "by_mrr": best_by_mrr["name"],
        },
        "dense_rebuild_check": rebuild_check,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("RAG benchmark complete")
    print(f"Queries: {len(pairs)}")
    print(f"Top-k: {args.top_k}")
    for row in model_results:
        print(
            f"- {row['name']}: "
            f"top1={row['top1']:.2%}, "
            f"hit@{args.top_k}={row[f'hit@{args.top_k}']:.2%}, "
            f"mrr={row['mrr']:.4f}, "
            f"ndcg@{args.top_k}={row[f'ndcg@{args.top_k}']:.4f}"
        )
    print(f"Best by top1: {best_by_top1['name']}")
    print(f"Best by mrr: {best_by_mrr['name']}")
    print(
        "Dense rebuild check: "
        f"first={rebuild_check['first_status']}, "
        f"after_delete={rebuild_check['second_status_after_delete']}, "
        f"sample_hits={rebuild_check['sample_retrieval_count']}"
    )
    print(f"Report saved to: {args.output}")


if __name__ == "__main__":
    main()
