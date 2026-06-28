"""Run a sanitized LLM connectivity check from the command line."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infrastructure.llm.health import check_llm_health  # noqa: E402


async def main() -> int:
    result = await check_llm_health()
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
