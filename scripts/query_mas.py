from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AI_AGENT_ROOT = REPO_ROOT / "services" / "ai-agent"
TARGET_SCRIPT = AI_AGENT_ROOT / "scripts" / "query_mas.py"


def main() -> None:
    if not TARGET_SCRIPT.exists():
        raise SystemExit(f"Target script not found: {TARGET_SCRIPT}")

    result = subprocess.run(
        [sys.executable, str(TARGET_SCRIPT), *sys.argv[1:]],
        cwd=str(AI_AGENT_ROOT),
        check=False,
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
