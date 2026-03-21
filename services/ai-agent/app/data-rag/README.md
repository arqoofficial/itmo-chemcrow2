# data-rag

Production RAG assets for `services/ai-agent`.

## Layout
- `corpus_raw/`: source markdown documents used for final answer excerpts.
- `corpus_processed/`: retrieval-ready corpus (currently a mirrored copy of raw).
- `indexes/`: persisted retrieval indexes.
  - `bm25_index.json`
  - `nomic_dense/`
- `pipelines/parsing/`: reserved for future parsing scripts.
- `pipelines/preprocessing/`: reserved for future preprocessing scripts.

## Current flow
1. Raw files are authored or synced into `corpus_raw/`.
2. Current baseline preprocessing mirrors files into `corpus_processed/`.
3. Hybrid retriever in `app/tools/rag.py` loads prebuilt indexes from `indexes/`.

## Rebuild behavior
Set `RAG_FORCE_REBUILD_INDEXES=true` to force index regeneration at runtime.

## Benchmarking
- Query benchmark file: `benchmarks/chapter_eval_queries.json`
- Evaluation script: `services/ai-agent/scripts/evaluate_rag.py`

Run from `services/ai-agent`:

```bash
python ../.venv/Scripts/python.exe scripts/evaluate_rag.py --top-k 5 --max-queries 12
```

The script compares BM25, dense (Nomic), and fusion (RRF), and writes a JSON report to
`app/data-rag/benchmarks/latest_eval_results.json`.
