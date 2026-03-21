# RAGAS Pipeline Comparison (Zero-touch Runtime)

This benchmark compares two answer paths on the same eval set without modifying runtime API logic:

1. `multi_agent` via existing `POST /api/v1/chat`
2. `direct_llm` via direct provider call in the script

The script saves two artifacts:

- raw paired outputs for debugging
- summary with latency stats and RAGAS metrics (if installed)

## Eval set format

Use JSON or JSONL with rows:

- `question_id` (optional, auto-generated if missing)
- `question` (required)
- `reference_answer` (required)

Example file:

- [app/data-rag/benchmarks/ragas_eval_set.example.json](app/data-rag/benchmarks/ragas_eval_set.example.json)

## Run

From [services/ai-agent](services/ai-agent):

```bash
uv run python scripts/evaluate_pipeline_ragas.py \
  --eval-set app/data-rag/benchmarks/ragas_eval_set.example.json \
  --agent-url http://localhost:8100/api/v1/chat \
  --provider openai \
  --judge-provider openai
```

Smoke run:

```bash
uv run python scripts/evaluate_pipeline_ragas.py \
  --eval-set app/data-rag/benchmarks/ragas_eval_set.example.json \
  --max-questions 2
```

## Outputs

Default outputs:

- `app/data-rag/benchmarks/pipeline_eval_raw.json`
- `app/data-rag/benchmarks/pipeline_eval_summary.json`

## Notes

- If `ragas` is not installed, script still writes raw outputs and summary marks RAGAS section as skipped.
- For fair comparison, both branches use the same provider (`--provider`) unless overridden.
- This flow is intentionally isolated from runtime to avoid changes in [app/main.py](app/main.py).
