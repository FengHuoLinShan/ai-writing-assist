"""Explicit RP opening through real stream, hold, audit, release and persistence."""

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from test_ai_quality_live import measured_provider, require_offpeak_flash  # noqa: F401
from infrastructure.llm.providers import OpenAIProvider
from modules.interaction.models import InteractionMessageNode
from modules.interaction.tests.test_real_llm import (
    test_deepseek_account_connection_generates_persisted_rp_opening as rp_opening,
)

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(
        os.getenv("RUN_AI_QUALITY_LIVE") != "1", reason="explicit paid acceptance only"
    ),
]


async def test_rp_opening_real(db_session, monkeypatch, measured_provider):
    root = Path(os.environ["AI_QUALITY_ARTIFACTS"])
    original = OpenAIProvider.generate_stream

    async def generate_stream(self, request):
        require_offpeak_flash(request.model)
        rows = (
            [json.loads(s) for s in (root / "requests.jsonl").read_text().splitlines()]
            if (root / "requests.jsonl").exists()
            else []
        )
        assert not any(row.get("unknown_charge") for row in rows), (
            "Reconcile unknown charges first"
        )
        ceiling = (
            len(request.model_dump_json().encode())
            + 2000
            + 4 * (request.max_tokens or 131072)
        ) / 1e6
        assert sum(r.get("estimated_yuan", 0) for r in rows) + ceiling <= float(
            os.environ["AI_QUALITY_CAP_YUAN"]
        )
        try:
            stream = await original(self, request)
        except BaseException as exc:
            with (root / "requests.jsonl").open("a") as f:
                f.write(
                    json.dumps(
                        {
                            "kind": "stream",
                            "error": type(exc).__name__,
                            "unknown_charge": True,
                        }
                    )
                    + "\n"
                )
            raise

        async def iterate():
            usage = None
            parts = []
            try:
                async for chunk in stream:
                    if chunk.usage is not None:
                        usage = chunk.usage.model_dump()
                    parts.append(chunk.content)
                    yield chunk
            finally:
                row = {
                    "kind": "stream",
                    "model": request.model,
                    "output": "".join(parts),
                    "usage": usage or {},
                    "unknown_charge": usage is None,
                }
                if usage:
                    row["estimated_yuan"] = (
                        usage["prompt_tokens"] + 4 * usage["completion_tokens"]
                    ) / 1e6
                with (root / "requests.jsonl").open("a") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")

        return iterate()

    monkeypatch.setattr(OpenAIProvider, "generate_stream", generate_stream)
    await rp_opening(db_session)
    nodes = (
        await db_session.scalars(
            select(InteractionMessageNode).where(
                InteractionMessageNode.role == "assistant",
                InteractionMessageNode.message_kind == "story",
            )
        )
    ).all()
    (root / "rp-opening.json").write_text(
        json.dumps(
            {"status": "passed", "outputs": [n.content for n in nodes]},
            ensure_ascii=False,
            indent=2,
        )
    )
