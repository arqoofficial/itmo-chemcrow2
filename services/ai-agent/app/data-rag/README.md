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
- Local retrieval tool: `rag_search` (hybrid BM25+dense search over local corpus).
- External fallback: `literature_search` (Semantic Scholar API).

Routing policy in agent prompt:
1. If user asks for literature references/citations on a topic, call `rag_search` first.
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
uv run python scripts/evaluate_rag.py --top-k 5 --max-queries 12
```

The script compares BM25, dense (Nomic), and fusion (RRF), and writes a JSON report to
`app/data-rag/benchmarks/latest_eval_results.json`.

## Pipeline evaluation (multi-agent vs direct LLM)
Evaluate and compare the multi-agent system (with chemistry tools) against a direct LLM baseline using RAGAS metrics.

**Overview:**
- `evaluate_pipeline_ragas.py` runs identical questions through both pipelines
- Multi-agent: ReAct-based system with tool calling (RDKit, PubChem, ADMET profiling, safety checks, etc.)
- Direct LLM: raw LLM without tools, for latency and capability comparison
- Results include RAGAS metrics: ResponseRelevancy, AnswerCorrectness, SemanticSimilarity, and latency deltas

**Core parameters:**
- `--eval-set <JSON_FILE>`: Path to evaluation questions (JSON format with `questions` array)
- `--agent-url <URL>`: Agent endpoint (default: `http://127.0.0.1:8100/api/v1/chat`)
- `--provider <openai|anthropic>`: LLM provider for generation (default: openai)
- `--judge-provider <openai|anthropic>`: LLM provider for RAGAS scoring (default: openai)
- `--max-questions <N>`: Evaluate only first N questions (useful for quick iteration)
- `--timeout-seconds <SEC>`: Request timeout (default: 300)
- `--judge-max-tokens <N>`: Max tokens for judge model (default: 1024)
- `--judge-temperature <FLOAT>`: Temperature for judge scoring (default: 0.0)
- `--judge-only`: Score existing raw results without regenerating answers

**Quick examples:**

*Full evaluation on default agent:*
```bash
cd services/ai-agent
uv run python scripts/evaluate_pipeline_ragas.py \
  --eval-set app/data-rag/benchmarks/ragas_eval_set.example.json
```

*Quick check with just 3 questions:*
```bash
cd services/ai-agent
uv run python scripts/evaluate_pipeline_ragas.py \
  --eval-set app/data-rag/benchmarks/ragas_eval_set.example.json \
  --max-questions 3
```

*Custom agent URL and longer timeout:*
```bash
cd services/ai-agent
uv run python scripts/evaluate_pipeline_ragas.py \
  --eval-set app/data-rag/benchmarks/chapter_eval_queries.json \
  --agent-url http://127.0.0.1:8101/api/v1/chat \
  --timeout-seconds 600
```

*Re-score existing raw results without re-running generation (fast):*
```bash
cd services/ai-agent
uv run python scripts/evaluate_pipeline_ragas.py \
  --eval-set app/data-rag/benchmarks/ragas_eval_set.example.json \
  --judge-only \
  --judge-temperature 0.5
```


**Output artifacts:**
- `app/data-rag/benchmarks/pipeline_eval_raw.json`: Raw answers for both pipelines (each row includes error, latency_ms, answer text)
- `app/data-rag/benchmarks/pipeline_eval_summary.json`: Aggregated metrics (per-pipeline averages, deltas, error counts)

**Environment setup:**
Ensure `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY` are set. Auto-start will launch ai-agent if `--agent-url` points to localhost and no server is listening.

## Query fused retrieval manually
Use `query_fused_rag.py` to run one-off hybrid retrieval and inspect top sources.

Run from repository root:

```bash
uv run python scripts/query_fused_rag.py "best solvent for SN2" --top-k 3
```

Direct run from `services/ai-agent` is still supported:

```bash
uv run python scripts/query_fused_rag.py "best solvent for SN2" --top-k 3
```

If you omit the query argument, the script will prompt interactively.

## Preflight corpus validation
Use `preflight_rag_corpus.py` before starting the service to validate chunk pairs and index presence.

Run from `services/ai-agent`:

```bash
uv run python scripts/preflight_rag_corpus.py --scope default
```

Strict mode treats warnings (for example, orphan BM25 folders) as errors:

```bash
uv run python scripts/preflight_rag_corpus.py --scope default --strict
```
