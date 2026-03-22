from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain_core.messages import HumanMessage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load repo-root .env before importing app.config so that OPENAI_API_KEY,
# OPENAI_BASE_URL, ANTHROPIC_API_KEY etc. are available to pydantic-settings.
# config.py declares env_file="../.env" which resolves relative to CWD, so it
# only works when running from exactly the right directory. Loading explicitly
# here makes the script location-independent.
_REPO_ENV = PROJECT_ROOT.parents[1] / ".env"  # ai-agent -> services -> repo root
if _REPO_ENV.exists():
    with _REPO_ENV.open("r", encoding="utf-8") as _efp:
        for _raw in _efp:
            _raw = _raw.strip()
            if not _raw or _raw.startswith("#") or "=" not in _raw:
                continue
            _ekey, _, _eval = _raw.partition("=")
            _ekey = _ekey.strip()
            _eval = _eval.strip()
            # Strip surrounding quotes if present
            if len(_eval) >= 2 and _eval[0] in ('"', "'") and _eval[-1] == _eval[0]:
                _eval = _eval[1:-1]
            # Shell-level env vars take precedence over .env file
            if _ekey and _ekey not in os.environ:
                os.environ[_ekey] = _eval

from app.config import settings  # noqa: E402
from app.llm_providers import get_llm  # noqa: E402


@dataclass
class EvalSample:
    question_id: str
    user_question: str
    reference_answer: str


@dataclass
class PipelineRunRow:
    question_id: str
    user_question: str
    pipeline_type: str
    answer: str
    reference_answer: str
    retrieved_contexts: list[str]
    latency_ms: int
    error: str | None
    run_timestamp: str


def _load_eval_set(path: Path, max_questions: int) -> list[EvalSample]:
    if not path.exists():
        raise FileNotFoundError(f"Eval set file not found: {path}")

    items: list[dict[str, Any]]
    if path.suffix.lower() == ".jsonl":
        items = []
        with path.open("r", encoding="utf-8") as fp:
            for raw_line in fp:
                line = raw_line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Eval set JSON must be an array of objects")
        items = payload

    samples: list[EvalSample] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Eval item #{idx} must be an object")

        question = str(item.get("question", "")).strip()
        reference = str(item.get("reference_answer", "")).strip()
        question_id = str(item.get("question_id") or f"q-{idx:04d}")

        if not question:
            raise ValueError(f"Eval item #{idx} has empty 'question'")
        if not reference:
            raise ValueError(f"Eval item #{idx} has empty 'reference_answer'")

        samples.append(
            EvalSample(
                question_id=question_id,
                user_question=question,
                reference_answer=reference,
            )
        )

    if max_questions > 0:
        samples = samples[:max_questions]
    return samples


async def _run_multi_agent_answer(
    client: httpx.AsyncClient,
    chat_url: str,
    question: str,
    provider: str | None,
) -> tuple[str, int, str | None]:
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": question}],
    }
    if provider:
        payload["provider"] = provider

    start = time.perf_counter()
    try:
        response = await client.post(chat_url, json=payload)
        response.raise_for_status()
        body = response.json()
        answer = str(body.get("content", ""))
        latency_ms = int((time.perf_counter() - start) * 1000)
        return answer, latency_ms, None
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return "", latency_ms, str(exc)


async def _run_direct_llm_answer(question: str, llm: Any) -> tuple[str, int, str | None]:
    start = time.perf_counter()
    try:
        response = await llm.ainvoke([HumanMessage(content=question)])
        answer = str(getattr(response, "content", "") or "")
        latency_ms = int((time.perf_counter() - start) * 1000)
        return answer, latency_ms, None
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return "", latency_ms, str(exc)


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result):
        return None
    return result


def _safe_metric_means_from_records(records: list[dict[str, Any]]) -> dict[str, float]:
    means: dict[str, float] = {}
    excluded = {"user_input", "response", "reference", "retrieved_contexts", "question_id"}
    if not records:
        return means

    keys = set().union(*(row.keys() for row in records))
    for key in sorted(keys):
        if key in excluded:
            continue
        values: list[float] = []
        for row in records:
            parsed = _safe_float(row.get(key))
            if parsed is not None:
                values.append(parsed)
        if values:
            means[key] = sum(values) / len(values)
    return means


def _latency_p95(latencies: list[int]) -> float | None:
    if not latencies:
        return None
    sorted_values = sorted(latencies)
    rank = math.ceil(0.95 * len(sorted_values))
    rank_index = min(max(rank - 1, 0), len(sorted_values) - 1)
    return float(sorted_values[rank_index])


def _extract_bind(agent_url: str) -> tuple[str, int, str] | None:
    parsed = urlparse(agent_url)
    host = parsed.hostname
    port = parsed.port
    scheme = parsed.scheme or "http"
    if not host or not port:
        return None
    return host, port, scheme


def _is_local_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "0.0.0.0"}


def _health_url_from_agent_url(agent_url: str) -> str:
    bind = _extract_bind(agent_url)
    if not bind:
        return ""
    host, port, scheme = bind
    return f"{scheme}://{host}:{port}/health"


async def _wait_for_health(health_url: str, timeout_seconds: float) -> bool:
    if not health_url:
        return False

    deadline = time.perf_counter() + max(timeout_seconds, 0.1)
    timeout = httpx.Timeout(2.0, connect=2.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        while time.perf_counter() < deadline:
            try:
                response = await client.get(health_url)
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)

    return False


def _start_local_agent_process(host: str, port: int) -> subprocess.Popen[Any] | None:
    cmd = [
        "uv",
        "run",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]

    popen_kwargs: dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }

    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        return subprocess.Popen(cmd, **popen_kwargs)
    except Exception:
        return None


def _terminate_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


async def _ensure_local_agent_available(agent_url: str, startup_wait_seconds: float) -> subprocess.Popen[Any] | None:
    bind = _extract_bind(agent_url)
    if not bind:
        return None

    host, port, _scheme = bind
    if not _is_local_host(host):
        return None

    health_url = _health_url_from_agent_url(agent_url)
    if await _wait_for_health(health_url, timeout_seconds=1.0):
        return None

    proc = _start_local_agent_process(host=host, port=port)
    if proc is None:
        raise RuntimeError(
            "Failed to auto-start ai-agent process. Start it manually with: "
            f"{sys.executable} -m uvicorn app.main:app --host {host} --port {port}"
        )

    if await _wait_for_health(health_url, timeout_seconds=startup_wait_seconds):
        print(f"Auto-started local ai-agent at {health_url}")
        return proc

    _terminate_process(proc)
    raise RuntimeError(
        "Auto-started ai-agent did not become healthy in time. "
        f"Tried health URL: {health_url}"
    )


def _instantiate_ragas_metrics(metric_names: list[str], judge_llm: Any) -> list[Any]:
    metrics_module = importlib.import_module("ragas.metrics")
    result: list[Any] = []
    for metric_name in metric_names:
        if not hasattr(metrics_module, metric_name):
            continue
        metric_cls = getattr(metrics_module, metric_name)
        try:
            result.append(metric_cls())
            continue
        except TypeError:
            pass

        try:
            result.append(metric_cls(llm=judge_llm))
            continue
        except TypeError:
            pass

        try:
            result.append(metric_cls(llm=judge_llm, embeddings=None))
        except TypeError:
            continue

    return result


def _build_judge_llm(judge_provider: str | None, judge_max_tokens: int | None, judge_temperature: float) -> Any:
    judge_llm = get_llm(judge_provider)

    # Bind inference-time kwargs for judge calls. This allows rerunning RAGAS
    # without changing runtime agent configs.
    bind_kwargs: dict[str, Any] = {}
    if judge_max_tokens and judge_max_tokens > 0:
        bind_kwargs["max_tokens"] = judge_max_tokens
    bind_kwargs["temperature"] = judge_temperature

    if bind_kwargs:
        judge_llm = judge_llm.bind(**bind_kwargs)
    return judge_llm


def _evaluate_with_ragas(
    rows: list[PipelineRunRow],
    judge_provider: str | None,
    judge_max_tokens: int | None,
    judge_temperature: float,
) -> dict[str, Any]:
    try:
        ragas_module = importlib.import_module("ragas")
        evaluate_fn = ragas_module.evaluate
        schema_module = importlib.import_module("ragas.dataset_schema")
        single_turn_sample_cls = schema_module.SingleTurnSample
        evaluation_dataset_cls = schema_module.EvaluationDataset
    except Exception as exc:
        return {
            "status": "skipped",
            "reason": f"RAGAS import failed: {exc}",
            "hint": "Install ragas in ai-agent environment: uv add ragas",
        }

    judge_llm = _build_judge_llm(judge_provider, judge_max_tokens, judge_temperature)
    metric_candidates = [
        "ResponseRelevancy",
        "AnswerCorrectness",
        "SemanticSimilarity",
    ]
    metrics = _instantiate_ragas_metrics(metric_candidates, judge_llm)
    if not metrics:
        return {
            "status": "skipped",
            "reason": "No compatible RAGAS metrics found for the installed version.",
            "hint": "Check ragas version and metric names.",
        }

    results: dict[str, Any] = {
        "status": "ok",
        "judge_provider": judge_provider or settings.DEFAULT_LLM_PROVIDER,
        "metrics_selected": [m.__class__.__name__ for m in metrics],
        "pipelines": {},
        "delta_multi_agent_minus_direct_llm": {},
    }

    pipeline_order = ["multi_agent", "direct_llm"]
    means_by_pipeline: dict[str, dict[str, float]] = {}

    for pipeline_type in pipeline_order:
        valid_rows = [row for row in rows if row.pipeline_type == pipeline_type and not row.error]
        if not valid_rows:
            results["pipelines"][pipeline_type] = {
                "row_count": 0,
                "reason": "No successful rows to evaluate.",
            }
            continue

        samples = [
            single_turn_sample_cls(
                user_input=row.user_question,
                response=row.answer,
                reference=row.reference_answer,
                retrieved_contexts=row.retrieved_contexts,
            )
            for row in valid_rows
        ]

        dataset = evaluation_dataset_cls(samples=samples)
        eval_result = evaluate_fn(dataset=dataset, metrics=metrics, llm=judge_llm)

        if hasattr(eval_result, "to_pandas"):
            frame = eval_result.to_pandas()
            records = frame.to_dict(orient="records")
            means = _safe_metric_means_from_records(records)
        elif hasattr(eval_result, "to_dict"):
            raw = eval_result.to_dict()
            if isinstance(raw, list):
                records = [row for row in raw if isinstance(row, dict)]
            elif isinstance(raw, dict):
                records = [raw]
            else:
                records = []
            means = _safe_metric_means_from_records(records)
        else:
            try:
                raw = dict(eval_result)
            except TypeError:
                raw = {}
            records = [raw] if isinstance(raw, dict) else []
            means = _safe_metric_means_from_records(records)

        means_by_pipeline[pipeline_type] = means
        results["pipelines"][pipeline_type] = {
            "row_count": len(valid_rows),
            "metric_means": means,
            "scores": records,
        }

    left = means_by_pipeline.get("multi_agent", {})
    right = means_by_pipeline.get("direct_llm", {})
    for key in sorted(set(left).intersection(right)):
        results["delta_multi_agent_minus_direct_llm"][key] = left[key] - right[key]

    return results


def _rows_from_raw_payload(raw_payload: dict[str, Any]) -> list[PipelineRunRow]:
    rows_data = raw_payload.get("rows")
    if not isinstance(rows_data, list):
        raise ValueError("raw payload must include 'rows' list")

    rows: list[PipelineRunRow] = []
    for idx, item in enumerate(rows_data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"raw row #{idx} must be an object")
        rows.append(
            PipelineRunRow(
                question_id=str(item.get("question_id", "")),
                user_question=str(item.get("user_question", "")),
                pipeline_type=str(item.get("pipeline_type", "")),
                answer=str(item.get("answer", "")),
                reference_answer=str(item.get("reference_answer", "")),
                retrieved_contexts=list(item.get("retrieved_contexts") or []),
                latency_ms=int(item.get("latency_ms") or 0),
                error=item.get("error"),
                run_timestamp=str(item.get("run_timestamp", "")),
            )
        )
    return rows


def _summarize_raw(rows: list[PipelineRunRow]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for pipeline_type in ["multi_agent", "direct_llm"]:
        grouped = [row for row in rows if row.pipeline_type == pipeline_type]
        errors = [row for row in grouped if row.error]
        latency = [row.latency_ms for row in grouped if row.error is None]
        result[pipeline_type] = {
            "rows": len(grouped),
            "errors": len(errors),
            "avg_latency_ms": float(sum(latency) / len(latency)) if latency else None,
            "p95_latency_ms": _latency_p95(latency),
        }
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare existing multi-agent pipeline with direct LLM baseline and evaluate with RAGAS.",
    )
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=Path(settings.RAG_DATA_DIR) / "benchmarks" / "ragas_eval_set.example.json",
        help="Path to eval set JSON/JSONL. Each row needs: question_id, question, reference_answer.",
    )
    parser.add_argument(
        "--agent-url",
        type=str,
        default="http://localhost:8100/api/v1/chat",
        help="Existing ai-agent synchronous chat endpoint.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="LLM provider override for both branches: openai | anthropic.",
    )
    parser.add_argument(
        "--judge-provider",
        type=str,
        default=None,
        help="LLM provider for RAGAS judge. Defaults to --provider, then DEFAULT_LLM_PROVIDER.",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=0,
        help="Optional cap for local smoke runs. 0 means all rows.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120,
        help="Timeout for multi-agent HTTP calls.",
    )
    parser.add_argument(
        "--no-auto-start-agent",
        action="store_true",
        help="Disable automatic startup of local ai-agent when --agent-url points to localhost.",
    )
    parser.add_argument(
        "--agent-startup-wait-seconds",
        type=float,
        default=25.0,
        help="How long to wait for a local auto-started ai-agent to pass /health.",
    )
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=Path(settings.RAG_DATA_DIR) / "benchmarks" / "pipeline_eval_raw.json",
        help="Path to save raw paired outputs.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path(settings.RAG_DATA_DIR) / "benchmarks" / "pipeline_eval_summary.json",
        help="Path to save summary with RAGAS metrics.",
    )
    parser.add_argument(
        "--judge-only",
        action="store_true",
        help="Skip generation and recompute only RAGAS from --raw-output.",
    )
    parser.add_argument(
        "--judge-max-tokens",
        type=int,
        default=2048,
        help="Max tokens for RAGAS judge model calls.",
    )
    parser.add_argument(
        "--judge-temperature",
        type=float,
        default=0.0,
        help="Temperature for RAGAS judge model calls.",
    )
    args = parser.parse_args()

    judge_provider = args.judge_provider or args.provider
    question_count = 0
    auto_started_agent_proc: subprocess.Popen[Any] | None = None

    try:
        if args.judge_only:
            if not args.raw_output.exists():
                raise FileNotFoundError(f"--judge-only requested but raw output not found: {args.raw_output}")
            raw_payload = json.loads(args.raw_output.read_text(encoding="utf-8"))
            rows = _rows_from_raw_payload(raw_payload)
            question_count = len({row.question_id for row in rows})
        else:
            if not args.no_auto_start_agent:
                auto_started_agent_proc = await _ensure_local_agent_available(
                    agent_url=args.agent_url,
                    startup_wait_seconds=args.agent_startup_wait_seconds,
                )

            samples = _load_eval_set(args.eval_set, max_questions=args.max_questions)
            question_count = len(samples)
            run_timestamp = datetime.now(UTC).isoformat()

            llm = get_llm(args.provider)
            rows = []

            async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
                for idx, sample in enumerate(samples, start=1):
                    ma_answer, ma_latency, ma_error = await _run_multi_agent_answer(
                        client=client,
                        chat_url=args.agent_url,
                        question=sample.user_question,
                        provider=args.provider,
                    )
                    rows.append(
                        PipelineRunRow(
                            question_id=sample.question_id,
                            user_question=sample.user_question,
                            pipeline_type="multi_agent",
                            answer=ma_answer,
                            reference_answer=sample.reference_answer,
                            retrieved_contexts=[],
                            latency_ms=ma_latency,
                            error=ma_error,
                            run_timestamp=run_timestamp,
                        )
                    )

                    direct_answer, direct_latency, direct_error = await _run_direct_llm_answer(
                        question=sample.user_question,
                        llm=llm,
                    )
                    rows.append(
                        PipelineRunRow(
                            question_id=sample.question_id,
                            user_question=sample.user_question,
                            pipeline_type="direct_llm",
                            answer=direct_answer,
                            reference_answer=sample.reference_answer,
                            retrieved_contexts=[],
                            latency_ms=direct_latency,
                            error=direct_error,
                            run_timestamp=run_timestamp,
                        )
                    )

                    print(f"[{idx}/{len(samples)}] completed question_id={sample.question_id}")

            raw_payload = {
                "meta": {
                    "run_timestamp": run_timestamp,
                    "agent_url": args.agent_url,
                    "provider": args.provider or settings.DEFAULT_LLM_PROVIDER,
                    "judge_provider": judge_provider or settings.DEFAULT_LLM_PROVIDER,
                    "eval_set": str(args.eval_set),
                    "question_count": question_count,
                },
                "rows": [asdict(row) for row in rows],
            }

            args.raw_output.parent.mkdir(parents=True, exist_ok=True)
            args.raw_output.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        # Run RAGAS in a thread so it can create its own event loop without
        # conflicting with the asyncio.run() that drives this function.
        try:
            ragas_payload = await asyncio.to_thread(
                _evaluate_with_ragas,
                rows,
                judge_provider,
                args.judge_max_tokens,
                args.judge_temperature,
            )
        except asyncio.CancelledError as exc:
            ragas_payload = {
                "status": "error",
                "reason": f"RAGAS evaluation cancelled: {exc}",
                "hint": "Raw outputs are valid. Re-run with --judge-only to retry judge scoring.",
            }
        summary_payload = {
            "meta": raw_payload["meta"],
            "raw_summary": _summarize_raw(rows),
            "ragas": ragas_payload,
        }

        if isinstance(summary_payload["meta"], dict):
            summary_payload["meta"]["judge_only"] = bool(args.judge_only)
            summary_payload["meta"]["judge_max_tokens"] = args.judge_max_tokens
            summary_payload["meta"]["judge_temperature"] = args.judge_temperature

        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        print("Pipeline comparison complete")
        print(f"Questions: {question_count}")
        print(f"Raw output: {args.raw_output}")
        print(f"Summary output: {args.summary_output}")
    finally:
        if auto_started_agent_proc is not None:
            _terminate_process(auto_started_agent_proc)


if __name__ == "__main__":
    asyncio.run(main())
