from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CANONICAL_CHUNKS_SUFFIX = "_chunks"
_BM25_CHUNKS_SUFFIX = "_bm25_chunks"
_SUPPORTED_CHUNK_EXTENSIONS = {".md", ".txt"}
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


config_module = _load_module("ai_agent_config", _PROJECT_ROOT / "app" / "config.py")
settings = config_module.settings


@dataclass(slots=True)
class CorpusStats:
    doc_key: str
    canonical_count: int
    bm25_count: int
    missing_in_bm25: list[str]
    missing_in_canonical: list[str]


def _chunk_files(directory: Path) -> list[Path]:
    return sorted(
        p
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in _SUPPORTED_CHUNK_EXTENSIONS
    )


def _chunk_key(path: Path, parent: Path) -> str:
    return path.relative_to(parent).with_suffix("").as_posix()


def _collect_stats(processed_dir: Path) -> tuple[list[CorpusStats], list[str], list[str]]:
    dense_dirs = sorted(
        p
        for p in processed_dir.iterdir()
        if p.is_dir() and p.name.endswith(_CANONICAL_CHUNKS_SUFFIX) and not p.name.endswith(_BM25_CHUNKS_SUFFIX)
    )

    errors: list[str] = []
    warnings: list[str] = []
    stats: list[CorpusStats] = []

    if not dense_dirs:
        errors.append(
            "No canonical directories found. "
            f"Expected folders like '*{_CANONICAL_CHUNKS_SUFFIX}' in {processed_dir}"
        )
        return stats, errors, warnings

    for dense_dir in dense_dirs:
        doc_key = dense_dir.name[: -len(_CANONICAL_CHUNKS_SUFFIX)]
        bm25_dir = processed_dir / f"{doc_key}{_BM25_CHUNKS_SUFFIX}"

        dense_files = _chunk_files(dense_dir)
        dense_keys = {_chunk_key(p, dense_dir) for p in dense_files}

        if not dense_files:
            errors.append(f"Canonical chunk folder is empty: {dense_dir}")

        if not bm25_dir.exists() or not bm25_dir.is_dir():
            errors.append(f"Missing BM25 folder for doc '{doc_key}': {bm25_dir}")
            stats.append(
                CorpusStats(
                    doc_key=doc_key,
                    canonical_count=len(dense_keys),
                    bm25_count=0,
                    missing_in_bm25=sorted(dense_keys),
                    missing_in_canonical=[],
                )
            )
            continue

        bm25_files = _chunk_files(bm25_dir)
        bm25_keys = {_chunk_key(p, bm25_dir) for p in bm25_files}
        if not bm25_files:
            errors.append(f"BM25 chunk folder is empty: {bm25_dir}")

        missing_in_bm25 = sorted(dense_keys - bm25_keys)
        missing_in_canonical = sorted(bm25_keys - dense_keys)

        if missing_in_bm25:
            errors.append(
                f"Doc '{doc_key}' has canonical chunks without BM25 counterparts: "
                + ", ".join(missing_in_bm25[:5])
                + (" ..." if len(missing_in_bm25) > 5 else "")
            )
        if missing_in_canonical:
            errors.append(
                f"Doc '{doc_key}' has BM25 chunks without canonical counterparts: "
                + ", ".join(missing_in_canonical[:5])
                + (" ..." if len(missing_in_canonical) > 5 else "")
            )

        stats.append(
            CorpusStats(
                doc_key=doc_key,
                canonical_count=len(dense_keys),
                bm25_count=len(bm25_keys),
                missing_in_bm25=missing_in_bm25,
                missing_in_canonical=missing_in_canonical,
            )
        )

    extra_bm25_dirs = sorted(
        p
        for p in processed_dir.iterdir()
        if p.is_dir() and p.name.endswith(_BM25_CHUNKS_SUFFIX)
    )
    canonical_doc_keys = {entry.doc_key for entry in stats}
    for bm25_dir in extra_bm25_dirs:
        doc_key = bm25_dir.name[: -len(_BM25_CHUNKS_SUFFIX)]
        if doc_key in canonical_doc_keys:
            continue
        warnings.append(f"Orphan BM25 directory without canonical pair: {bm25_dir}")

    return stats, errors, warnings


def _print_index_status(source_dir: Path) -> None:
    bm25_index = source_dir / "indexes" / "bm25_index.json"
    dense_meta = source_dir / "indexes" / "nomic_dense" / "nomic_dense_meta.json"
    dense_vec = source_dir / "indexes" / "nomic_dense" / "nomic_dense_vectors.npz"

    print("\nIndex files:")
    for path in [bm25_index, dense_meta, dense_vec]:
        if path.exists():
            print(f"  OK   {path} ({path.stat().st_size} bytes)")
        else:
            print(f"  MISS {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight validation for chunked RAG corpus layout")
    parser.add_argument("--scope", default=settings.RAG_DEFAULT_SOURCE, help="RAG source scope (default from settings)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (non-zero exit code)",
    )
    args = parser.parse_args()

    source_dir = Path(settings.RAG_SOURCES_DIR) / args.scope
    processed_dir = source_dir / "corpus_processed"

    if not source_dir.exists():
        raise SystemExit(f"RAG source directory not found: {source_dir}")
    if not processed_dir.exists():
        raise SystemExit(f"Processed corpus directory not found: {processed_dir}")

    stats, errors, warnings = _collect_stats(processed_dir)

    total_canonical = sum(item.canonical_count for item in stats)
    total_bm25 = sum(item.bm25_count for item in stats)

    print(f"Source scope: {args.scope}")
    print(f"Processed corpus: {processed_dir}")
    print(f"Documents: {len(stats)}")
    print(f"Canonical chunks: {total_canonical}")
    print(f"BM25 chunks: {total_bm25}")

    print("\nPer-document chunk stats:")
    for item in stats:
        print(
            f"  - {item.doc_key}: canonical={item.canonical_count}, bm25={item.bm25_count}, "
            f"missing_in_bm25={len(item.missing_in_bm25)}, missing_in_canonical={len(item.missing_in_canonical)}"
        )

    if warnings:
        print("\nWarnings:")
        for msg in warnings:
            print(f"  - {msg}")

    if errors:
        print("\nErrors:")
        for msg in errors:
            print(f"  - {msg}")

    _print_index_status(source_dir)

    if errors or (warnings and args.strict):
        raise SystemExit(2)

    print("\nPreflight check passed.")


if __name__ == "__main__":
    main()
