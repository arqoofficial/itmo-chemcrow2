# data-rag

Production RAG assets for `services/ai-agent`.

## Layout
- `corpus_raw/`: source documents.
  - Top-level `*.md`: authored raw markdown corpus.
  - `pdfs/*.pdf`: source PDFs for automatic ingestion.
- `corpus_processed/`: retrieval-ready corpus produced at runtime.
  - `<doc_id>.md`: clean corpus documents used for dense retrieval.
  - `<doc_id>__bm25.md`: BM25-optimized text variants used for sparse retrieval.
- `indexes/`: persisted retrieval indexes.
  - `bm25_index.json`
  - `nomic_dense/`

## Current flow
1. Raw files are authored or synced into `corpus_raw/`.
2. During retriever initialization, `app/tools/rag.py` automatically prepares `corpus_processed/`:
  - mirrors top-level raw markdown into clean processed markdown,
  - creates BM25 variants (`__bm25` suffix) for those docs,
  - ingests PDFs from `corpus_raw/pdfs/` into processed markdown docs,
  - creates BM25 variants for PDF-derived docs.
3. Hybrid retriever builds/loads indexes from `indexes/`:
  - BM25 index uses BM25 variants,
  - dense index uses clean processed markdown.

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
Set `RAG_FORCE_REBUILD_INDEXES=true` to force index regeneration at runtime.

## PDF ingestion settings
Configured in `app/config.py`:

- `RAG_PDF_RAW_SUBDIR` (default `pdfs`)
- `RAG_BM25_SUFFIX` (default `__bm25`)
- `RAG_PDF_ENABLE_LLM_CLEANING` (default `false`)
- `RAG_PDF_CLEAN_MODEL` (default `openai/gpt-4o-mini`)
- `RAG_PDF_CLEAN_WINDOW_SIZE` (default `6000`)
- `RAG_PDF_CLEAN_OVERLAP` (default `800`)

When LLM cleaning is disabled or unavailable, deterministic cleaning is applied.

## Benchmarking
- Query benchmark file: `benchmarks/chapter_eval_queries.json`
- Evaluation script: `services/ai-agent/scripts/evaluate_rag.py`

Run from `services/ai-agent`:

```bash
python ../.venv/Scripts/python.exe scripts/evaluate_rag.py --top-k 5 --max-queries 12
```

The script compares BM25, dense (Nomic), and fusion (RRF), and writes a JSON report to
`app/data-rag/benchmarks/latest_eval_results.json`.
