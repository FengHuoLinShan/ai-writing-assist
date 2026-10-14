"""codex executor reasoning effort 允许集回归。"""

import pytest

from evals.codex_executor import CodexStructuredExecutor


@pytest.mark.parametrize("effort", [None, "low", "medium", "high", "xhigh", "max"])
def test_codex_executor_accepts_official_efforts(effort):
    executor = CodexStructuredExecutor(
        model="gpt-5.6-luna",
        reasoning_effort=effort,
        command="codex",
    )
    # Luna 未显式指定 effort 时回退其专属默认 medium。
    assert executor.reasoning_effort == (effort or "medium")


def test_codex_executor_rejects_unknown_effort():
    with pytest.raises(ValueError, match="unsupported eval reasoning effort"):
        CodexStructuredExecutor(
            model="gpt-5.6-luna",
            reasoning_effort="ultra",
            command="codex",
        )


@pytest.mark.asyncio
async def test_legacy_eval_calls_fail_before_spawn_and_keep_metadata(monkeypatch):
    from evals.codex_executor import CodexExecutionError
    from evals.generation import GeneratedCaseBatch

    async def unexpected_spawn(*args, **kwargs):
        raise AssertionError("paused evaluator must not start a CLI")

    monkeypatch.setattr(
        "evals.codex_executor.asyncio.create_subprocess_exec", unexpected_spawn
    )
    executor = CodexStructuredExecutor(model="gpt-5.6-luna")
    original_meta = executor.meta
    with pytest.raises(CodexExecutionError, match="evaluation is paused"):
        await executor.generate_structured(
            "synthetic", GeneratedCaseBatch, step_name="gate"
        )
    assert executor.meta == original_meta


@pytest.mark.asyncio
async def test_legacy_project_reviewer_cannot_bypass_pause(tmp_path, monkeypatch):
    from evals.cli import _open_model_review_evaluator
    from evals.codex_executor import CodexExecutionError

    def unexpected_init(self):
        raise AssertionError("paused reviewer must fail before project access")

    monkeypatch.setattr("core.database.DatabaseManager.init", unexpected_init)
    with pytest.raises(CodexExecutionError, match="evaluation is paused"):
        async with _open_model_review_evaluator(
            model="deepseek-v4-flash", novel_id="synthetic-project", cache_dir=tmp_path
        ):
            pytest.fail("legacy reviewer must not be made available")
