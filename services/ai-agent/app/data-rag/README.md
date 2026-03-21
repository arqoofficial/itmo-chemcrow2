# data-rag

Production RAG assets for `services/ai-agent`.

## Layout
- `corpus_processed/`: retrieval-ready chunk corpus.
  - `<doc_key>_chunks/`: canonical chunks returned by the tool.
  - `<doc_key>_bm25_chunks/`: BM25-optimized chunks used only for sparse retrieval.
- `indexes/`: persisted retrieval indexes.
  - `bm25_index.json`
  - `nomic_dense/`
- `pipelines/parsing/`: reserved for future parsing scripts.
- `pipelines/preprocessing/`: reserved for future preprocessing scripts.

## Current flow
1. Chunk folders are synced into `sources/<scope>/corpus_processed/`.
2. Hybrid retriever loads canonical chunks from `*_chunks/` and BM25 chunks from `*_bm25_chunks/`.
3. Search is fused with RRF in canonical id space, so results always return canonical chunk text.
4. Indexes are loaded from `indexes/` when fingerprints match, otherwise rebuilt and saved.

## Chunk mapping rules
- Each BM25 chunk must have a matching canonical chunk with the same relative chunk key.
- Supported chunk extensions: `.md`, `.txt`.
- Example pair:
  - `paper_01_chunks/chunk_000.md`
  - `paper_01_bm25_chunks/chunk_000.txt`

## Agent literature workflow
- Primary citation tool: `literature_citation_search` (local RAG corpus).
- General retrieval tool: `rag_search` (same local hybrid retriever).
- External fallback: `literature_search` (Semantic Scholar API).

Routing policy in agent prompt:
1. If user asks for literature references/citations on a topic, call
  `literature_citation_search` first.
2. If local corpus has no/weak coverage, fallback to `literature_search`.
3. Final answer should clearly cite source origin (local corpus vs external papers).

## Rebuild behavior
- Default mode: persisted indexes are reused.
- Rebuild happens only when an index is missing, schema version changes, or corpus fingerprint changes.
- Set `RAG_FORCE_REBUILD_INDEXES=true` to force index regeneration.

## Benchmarking
- Query benchmark file: `benchmarks/chapter_eval_queries.json`
- Evaluation script: `services/ai-agent/scripts/evaluate_rag.py`

Run from `services/ai-agent`:

```bash
python ../.venv/Scripts/python.exe scripts/evaluate_rag.py --top-k 5 --max-queries 12
```

The script compares BM25, dense (Nomic), and fusion (RRF), and writes a JSON report to
`app/data-rag/benchmarks/latest_eval_results.json`.
