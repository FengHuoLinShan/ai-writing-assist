"""Opt-in synthetic probes using the owner runtime and one uncapped spend ledger."""

import fcntl
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# These overrides are process-local. Never rewrite the shared .env or restart
# another chat's service to bypass its proxy.
os.environ["LLM_PROXY_URL"] = ""
os.environ["ECHO_SQL"] = "false"
from core.config import load_env_file  # noqa: E402

load_env_file(Path("/Users/tywww/Desktop/项目/ai-writing-assist/backend/.env"))

from sqlalchemy.engine import make_url  # noqa: E402

if make_url(os.environ["DATABASE_URL"]).database != "ai_novel_acceptance_guimi":
    raise RuntimeError("Expected the existing protected acceptance database")

from evals.ask_world import main  # noqa: E402
from evals.v4_live import Meter, save  # noqa: E402
from infrastructure.llm.providers import OpenAIProvider  # noqa: E402

PRIVATE = Path(
    "/Users/tywww/Documents/ai-writing-assist-private/ask-world-quality-20261004"
)
PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
SPEND = PRIVATE / "cumulative-cost.json"
ARTIFACT = Path("../.agent/tasks/2026/T-20261004-ask-world-quality/artifacts")
if not SPEND.exists():
    original = ARTIFACT / "deepseek-debug-ledger.jsonl"
    save(
        SPEND,
        {
            "cap_usd": None,
            "provider": "deepseek",
            "model": "deepseek-flash",
            "pricing_source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "pricing_verified_at": "2026-10-04",
            "calls": [],
            "authorization_history": [
                {
                    "at": datetime.now(UTC).isoformat(),
                    "cap_usd": None,
                    "scope": (
                        "Ask World v3 debug, one holdout and real browser acceptance"
                    ),
                    "user_instruction": "不设预算上限，继续做完",
                }
            ],
            "previous_unmetered_generation": {
                "observed_case_count": 28,
                "output_ledger_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
                "usage_available": False,
                "cost_available": False,
                "reason": "Historical case ledger did not retain transport usage or cost",
            },
            "teacher_cost_status": "unavailable_codex_cli_subscription",
        },
    )

with SPEND.with_suffix(".lock").open("a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    meter = Meter(SPEND)
    if meter.ledger["cap_usd"] is not None:
        raise RuntimeError(
            "This continuation requires the recorded uncapped authorization"
        )
    original_generate = OpenAIProvider.generate
    OpenAIProvider.generate = meter.wrap(original_generate)
    sys.argv = ["evals.ask_world", *sys.argv[1:]]
    try:
        main()
    finally:
        OpenAIProvider.generate = original_generate
        calls = meter.ledger["calls"]
        print(
            json.dumps(
                {
                    "metered_calls": len(calls),
                    "settled_calls": sum(call["status"] == "settled" for call in calls),
                    "estimated_cost_usd": sum(
                        call.get("estimated_cost_usd", 0) for call in calls
                    ),
                    "prior_cost_available": False,
                }
            )
        )
