"""The local CLI adapter fits the existing structured evaluation port."""

import pytest
from pydantic import BaseModel

from evals.cli_executor import CLIStructuredExecutor
from evals.generation import HighQualityEvalLLM
from infrastructure.llm.cli_agent import CLIResult


@pytest.mark.asyncio
async def test_local_cli_records_distinct_eval_profile(monkeypatch):
    class Answer(BaseModel):
        answer: str

    async def fake_run(spec):
        assert spec.kind == "pi" and spec.model == "test/model"
        return CLIResult('{"answer":"ok"}', 0, None)

    monkeypatch.setattr("evals.cli_executor.run_cli_agent", fake_run)
    executor = CLIStructuredExecutor("pi", model="test/model")
    result = await executor.generate_structured(
        "synthetic prompt", Answer, step_name="synthetic"
    )
    meta = HighQualityEvalLLM(executor).run_meta("synthetic prompt")
    assert result.answer == "ok"
    assert meta.model == "test/model"
    assert meta.profile_hash == executor.meta.executor_hash
    assert meta.cost_status == "unavailable_local_cli"
