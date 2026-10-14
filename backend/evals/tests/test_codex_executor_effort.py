"""codex executor reasoning effort 允许集回归。"""

import pytest

from evals.codex_executor import CodexStructuredExecutor
from evals.schemas import FROZEN_LEGACY_EVAL_MODELS


@pytest.mark.parametrize("effort", [None, "low", "medium", "high", "xhigh", "max"])
def test_codex_executor_accepts_official_efforts(effort):
    # 冻结历史模型仅允许显式 frozen 元数据重建（G6a）。
    executor = CodexStructuredExecutor(
        model="gpt-5.6-luna",
        reasoning_effort=effort,
        allowed_models=FROZEN_LEGACY_EVAL_MODELS,
        command="codex",
    )
    # Luna 未显式指定 effort 时回退其专属默认 medium。
    assert executor.reasoning_effort == (effort or "medium")


def test_codex_executor_rejects_unknown_effort():
    with pytest.raises(ValueError, match="unsupported eval reasoning effort"):
        CodexStructuredExecutor(
            model="gpt-5.6-luna",
            reasoning_effort="ultra",
            allowed_models=FROZEN_LEGACY_EVAL_MODELS,
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
    executor = CodexStructuredExecutor()
    original_meta = executor.meta
    with pytest.raises(CodexExecutionError, match="evaluation is paused"):
        await executor.generate_structured(
            "synthetic", GeneratedCaseBatch, step_name="gate"
        )
    assert executor.meta == original_meta


def test_frozen_deepseek_reviewer_is_rejected_before_any_runtime_access():
    from evals.cli import _validate_review_model_assignment

    # DeepSeek reviewer A 是冻结历史：在任何项目运行时访问前即被合同拒绝。
    with pytest.raises(ValueError, match="requires model gpt-6.1-sol"):
        _validate_review_model_assignment("reviewer-a", "deepseek-v4-flash")


@pytest.mark.asyncio
async def test_sol_reviewer_executor_still_paused_before_spawn(tmp_path, monkeypatch):
    from evals.cli import _open_model_review_evaluator
    from evals.codex_executor import CodexExecutionError

    async def unexpected_spawn(*args, **kwargs):
        raise AssertionError("paused reviewer must not start a CLI")

    monkeypatch.setattr(
        "evals.codex_executor.asyncio.create_subprocess_exec", unexpected_spawn
    )
    with pytest.raises(CodexExecutionError, match="evaluation is paused"):
        async with _open_model_review_evaluator(
            model="gpt-6.1-sol", cache_dir=tmp_path
        ) as evaluator:
            from evals.generation import GeneratedCaseBatch

            await evaluator.executor.generate_structured(
                "synthetic", GeneratedCaseBatch, step_name="gate"
            )
