#!/usr/bin/env python3
"""Download RAG dense embedding weights into ai-agent's app/data/SentenceTransformer.

See scripts/README.md for run instructions.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ai_agent_root() -> Path:
    """Repo checkout: .../repo/scripts/this.py → .../repo/services/ai-agent. Docker: /app."""
    here = Path(__file__).resolve()
    above_scripts = here.parent.parent
    nested = above_scripts / "services" / "ai-agent"
    if nested.is_dir():
        return nested
    return above_scripts


_AI_AGENT_ROOT = _ai_agent_root()
if str(_AI_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_AGENT_ROOT))


def _target_dir(override: Path | None) -> Path:
    if override is not None:
        return override.resolve()
    from app.config import settings

    raw = (settings.RAG_EMBEDDING_MODEL_DIR or "").strip()
    if not raw:
        raise SystemExit("RAG_EMBEDDING_MODEL_DIR is empty in configuration")
    p = Path(raw)
    if not p.is_absolute():
        p = _AI_AGENT_ROOT / p
    return p.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save SentenceTransformer embedding model to RAG_EMBEDDING_MODEL_DIR (or --output).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Override output directory (default: RAG_EMBEDDING_MODEL_DIR under services/ai-agent)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Hugging Face model id (default: settings.RAG_EMBEDDING_MODEL)",
    )
    args = parser.parse_args()

    from app.config import settings

    model_id = args.model or settings.RAG_EMBEDDING_MODEL
    out = _target_dir(args.output)
    out.mkdir(parents=True, exist_ok=True)

    from sentence_transformers import SentenceTransformer

    print(f"Downloading {model_id!r} …")
    model = SentenceTransformer(model_id, trust_remote_code=True)
    model.save(str(out))
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
