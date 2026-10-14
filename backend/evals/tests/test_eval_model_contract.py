"""G6a 评测模型合同角色拆分回归（离线，零真实模型调用）。

教师、judge/复核（reviewer、adjudicator）与 scene-gold 参考答案固定 Sol/xhigh；
被测业务生成经 Project facade 走产品侧 Luna/max；旧 Spark/Luna/terra/DeepSeek
常量仅作冻结元数据。暂停守卫在 G6b 解除前继续拒绝新的独立调用。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from evals.ask_world import (
    ASK_WORLD_TEACHER_MODEL,
    ASK_WORLD_TEACHER_REASONING_EFFORT,
)
from evals.codex_executor import CodexExecutionError, CodexStructuredExecutor
from evals.readiness import assess_baseline_readiness
from evals.schemas import (
    ALLOWED_DATASET_PROVENANCE_MODELS,
    ALLOWED_EVAL_TEACHER_MODELS,
    ALLOWED_HIGH_QUALITY_LLM_MODELS,
    EVAL_ADJUDICATOR_MODEL,
    EVAL_REVIEWER_A_MODEL,
    EVAL_REVIEWER_B_MODEL,
    EVAL_TEACHER_MODEL,
    EVAL_TEACHER_REASONING_EFFORT,
    FROZEN_LEGACY_EVAL_MODELS,
    HIGH_QUALITY_LLM_FALLBACK_MODEL,
    HIGH_QUALITY_LLM_MODEL,
    DatasetCase,
    DatasetSplit,
    EvalSuite,
    GenerationMeta,
    QCDecision,
)


def test_eval_teacher_contract_constants() -> None:
    assert EVAL_TEACHER_MODEL == "gpt-6.1-sol"
    assert EVAL_TEACHER_REASONING_EFFORT == "xhigh"
    assert ALLOWED_EVAL_TEACHER_MODELS == frozenset({EVAL_TEACHER_MODEL})


def test_legacy_constants_stay_frozen_metadata() -> None:
    """旧常量保留历史标识值，历史数据集与账本仍可被识别和校验。"""

    assert HIGH_QUALITY_LLM_MODEL == "gpt-5.3-codex-spark"
    assert HIGH_QUALITY_LLM_FALLBACK_MODEL == "gpt-5.6-luna"
    assert EVAL_REVIEWER_A_MODEL == "deepseek-v4-flash"
    assert EVAL_REVIEWER_B_MODEL == "gpt-5.6-luna"
    assert EVAL_ADJUDICATOR_MODEL == "gpt-5.6-terra"
    assert FROZEN_LEGACY_EVAL_MODELS == frozenset(
        {
            HIGH_QUALITY_LLM_MODEL,
            HIGH_QUALITY_LLM_FALLBACK_MODEL,
            EVAL_REVIEWER_A_MODEL,
            EVAL_REVIEWER_B_MODEL,
            EVAL_ADJUDICATOR_MODEL,
        }
    )
    # dataset generator/judge 溯源接受旧 generator 合同与新教师合同，
    # 但不接受从未担任 generator/judge 的 terra/DeepSeek。
    assert ALLOWED_DATASET_PROVENANCE_MODELS == (
        ALLOWED_HIGH_QUALITY_LLM_MODELS | ALLOWED_EVAL_TEACHER_MODELS
    )


def test_codex_executor_defaults_to_sol_xhigh() -> None:
    executor = CodexStructuredExecutor()

    assert executor.model == EVAL_TEACHER_MODEL
    assert executor.reasoning_effort == EVAL_TEACHER_REASONING_EFFORT
    assert executor.meta.model == EVAL_TEACHER_MODEL
    assert executor.meta.reasoning_effort == EVAL_TEACHER_REASONING_EFFORT
    assert len(executor.meta.executor_hash) == 64


def test_ask_world_teacher_contract_shares_schemas_constants() -> None:
    assert ASK_WORLD_TEACHER_MODEL is EVAL_TEACHER_MODEL
    assert ASK_WORLD_TEACHER_REASONING_EFFORT == "xhigh"


def test_legacy_models_require_explicit_frozen_allowlist() -> None:
    with pytest.raises(ValueError, match="eval model must be one of: gpt-6.1-sol"):
        CodexStructuredExecutor(model=HIGH_QUALITY_LLM_MODEL)

    legacy = CodexStructuredExecutor(
        model=HIGH_QUALITY_LLM_MODEL,
        allowed_models=FROZEN_LEGACY_EVAL_MODELS,
    )
    assert legacy.model == HIGH_QUALITY_LLM_MODEL
    assert len(legacy.meta.executor_hash) == 64


@pytest.mark.asyncio
async def test_pause_guard_still_rejects_new_contract_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G6a 验收：迁移后暂停守卫仍拦截新 Sol/xhigh 教师路径的真实调用。"""

    from evals.generation import GeneratedCaseBatch

    async def unexpected_spawn(*args, **kwargs):
        raise AssertionError("paused evaluator must not start a CLI")

    monkeypatch.setattr(
        "evals.codex_executor.asyncio.create_subprocess_exec", unexpected_spawn
    )
    executor = CodexStructuredExecutor()
    with pytest.raises(CodexExecutionError, match="evaluation is paused"):
        await executor.generate_structured(
            "synthetic", GeneratedCaseBatch, step_name="contract-gate"
        )


@pytest.mark.asyncio
async def test_model_review_evaluator_pins_sol_without_cache_fallback(
    tmp_path,
) -> None:
    from evals.cli import _open_model_review_evaluator

    async with _open_model_review_evaluator(
        model=EVAL_TEACHER_MODEL,
        cache_dir=tmp_path,
    ) as evaluator:
        assert evaluator.executor.model == EVAL_TEACHER_MODEL
        assert evaluator.executor.reasoning_effort == EVAL_TEACHER_REASONING_EFFORT
        # 复核角色固定模型，不回放旧合同模型的缓存。
        assert evaluator.allow_primary_cache_fallback is False


@pytest.mark.asyncio
async def test_scene_gold_repair_pins_sol_and_drops_legacy_fallback(tmp_path) -> None:
    from evals.cli import _scene_gold_repair

    with (
        patch("evals.cli.repair_scene_gold_cases", autospec=True) as repair,
        patch("evals.cli._load_cases", autospec=True) as load_cases,
        patch("evals.cli.source_path_for_variant", autospec=True) as source_path,
    ):
        repair.return_value = ([], {})
        load_cases.return_value = []
        await _scene_gold_repair(
            dataset=tmp_path / "dataset.jsonl",
            variant="pilot",
            model=EVAL_TEACHER_MODEL,
            output=tmp_path / "out.jsonl",
            meta_output=tmp_path / "meta.json",
            cache_dir=tmp_path / "cache",
            cache_only=True,
        )

    repair.assert_awaited_once()
    kwargs = repair.await_args.kwargs
    assert kwargs["primary_executor"].model == EVAL_TEACHER_MODEL
    assert kwargs["primary_executor"].reasoning_effort == EVAL_TEACHER_REASONING_EFFORT
    assert kwargs["fallback_executor"] is None
    assert kwargs["cache_only"] is True
    assert source_path.call_args == (("pilot",),)


def _provenance_case(model: str) -> DatasetCase:
    return DatasetCase(
        case_id="scene-000001",
        suite=EvalSuite.scene,
        scenario="location_shift",
        source_group_id="group-a",
        input={"text": "文本"},
        reference={"boundary_offsets": [0, 2]},
        split=DatasetSplit.test,
        generation_meta=GenerationMeta(
            model=model,
            profile_hash="a" * 64,
            prompt_hash="b" * 64,
            source_hash="c" * 64,
        ),
        qc=QCDecision(
            status="accepted",
            judge_decisions=[{"model": model, "prompt_hash": "d" * 64}],
        ),
    )


@pytest.mark.parametrize(
    "model",
    [EVAL_TEACHER_MODEL, HIGH_QUALITY_LLM_MODEL, HIGH_QUALITY_LLM_FALLBACK_MODEL],
)
def test_dataset_provenance_accepts_sol_and_frozen_generator_contract(model: str) -> None:
    report = assess_baseline_readiness(
        [_provenance_case(model)],
        tier="pilot",
        suites=(EvalSuite.scene,),
    )

    assert "generation_provenance_invalid:count=1" not in report["issues"]
    assert "judge_provenance_invalid:count=1" not in report["issues"]


def test_dataset_provenance_rejects_models_never_used_as_generator() -> None:
    for model in (EVAL_ADJUDICATOR_MODEL, EVAL_REVIEWER_A_MODEL):
        report = assess_baseline_readiness(
            [_provenance_case(model)],
            tier="pilot",
            suites=(EvalSuite.scene,),
        )

        assert "generation_provenance_invalid:count=1" in report["issues"]
