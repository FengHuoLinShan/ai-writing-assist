from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from pydantic import BaseModel

from evals.cache import EvalCache
from evals.cli import (
    PILOT_RAW_STEM,
    PILOT_SUITE_SIZES,
    _freeze_dataset,
    _judge_batches,
    _judge_status,
    _rag_preflight,
    _run_workflow_evaluation,
)
from evals.codex_executor import (
    CodexExecutionMeta,
    CodexStructuredExecutor,
    _strict_json_schema,
)
from evals.corpus import ChapterSnapshot, CorpusSnapshot
from evals.generation import (
    GeneratedCaseBatch,
    GeneratedCaseDraft,
    GenerationRunMeta,
    HighQualityEvalLLM,
    JudgeDecision,
    JudgeDecisionBatch,
    JudgeDecisionItem,
    ReferenceSnapshotBatch,
    ReferenceSnapshotItem,
    _model_review_prompt,
    materialize_generated_cases,
)
from evals.ragas_adapter import build_codex_ragas_llm
from evals.readiness import (
    BASELINE_MINIMUMS,
    BASELINE_SCENARIOS,
    SAFETY_REVIEW_ERROR,
    assess_baseline_readiness,
)
from evals.runners.outline import evaluate_outline_cases, run_outline_preview_cases
from evals.runners.rag import evaluate_rag_cases
from evals.runners.scene import evaluate_scene_cases, run_scene_workflow_cases
from evals.runners.world import evaluate_world_cases, run_world_workflow_cases
from evals.schemas import (
    ALLOWED_CODEX_REVIEW_MODELS,
    HIGH_QUALITY_LLM_MODEL,
    DatasetCase,
    DatasetManifest,
    DatasetSplit,
    EvalResult,
    EvalSuite,
    GenerationMeta,
    HumanReview,
    HumanReviewDecision,
    LogicalSourceRef,
    QCDecision,
    RiskLevel,
)
from modules.rag.contracts import RagChunkContract, RagResultBundle


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _corpus() -> CorpusSnapshot:
    return CorpusSnapshot(
        source_alias="fixture",
        file_hash=_hash("file"),
        byte_size=10,
        chapters=[
            ChapterSnapshot(
                chapter_index=1,
                title="第一章",
                start_offset=0,
                end_offset=10,
                content_hash=_hash("chapter"),
                source_group_id="group-1",
            )
        ],
    )


def _case(suite: EvalSuite, case_id: str, reference: dict) -> DatasetCase:
    return DatasetCase(
        case_id=case_id,
        suite=suite,
        scenario="fixture",
        source_group_id="group-1",
        input={"query": "问题"},
        reference=reference,
        split=DatasetSplit.test,
    )


def _pilot_ready_cases() -> list[DatasetCase]:
    cases: list[DatasetCase] = []
    for suite, minimum in BASELINE_MINIMUMS["pilot"].items():
        scenarios = BASELINE_SCENARIOS[suite]
        for index in range(minimum):
            cases.append(
                _case(
                    suite,
                    f"{suite.value}-ready-{index:04d}",
                    {"answer": "fixture"},
                ).model_copy(
                    update={
                        "scenario": scenarios[index % len(scenarios)],
                        "generation_meta": GenerationMeta(
                            profile_hash=_hash("executor"),
                            prompt_hash=_hash(f"prompt:{suite.value}:{index}"),
                            source_hash=_hash("source"),
                        ),
                        "source_refs": (
                            [
                                LogicalSourceRef(
                                    corpus_id="fixture-corpus",
                                    source_alias="fixture",
                                    source_group_id="group-1",
                                    chapter_index=1,
                                    content_hash=_hash("chapter"),
                                    range_hash=_hash(
                                        f"scene-range:{suite.value}:{index}"
                                    ),
                                    start_offset=index * 10,
                                    end_offset=index * 10 + 5,
                                )
                            ]
                            if suite == EvalSuite.scene
                            else []
                        ),
                        "qc": QCDecision(
                            status="accepted",
                            judge_decisions=[
                                {
                                    "model": HIGH_QUALITY_LLM_MODEL,
                                    "prompt_hash": _hash("judge-1"),
                                    "decision": "accept",
                                    "rubric_score": 5,
                                }
                            ],
                        ),
                    }
                )
            )
    for suite in EvalSuite:
        suite_cases = [case for case in cases if case.suite == suite]
        for index, case in enumerate(suite_cases[:30]):
            decisions = [
                HumanReviewDecision(
                    status="accepted",
                    reviewer_version="reviewer-a",
                )
            ]
            if index < 8:
                decisions.append(
                    HumanReviewDecision(
                        status="accepted",
                        reviewer_version="reviewer-b",
                    )
                )
            case.human_review = HumanReview(
                status="accepted",
                reviewer_version=("consensus" if len(decisions) == 2 else "reviewer-a"),
                score=5,
                independent_reviews=decisions,
            )
    return cases


def test_materialized_generation_is_locked_to_quality_model() -> None:
    snapshot = ReferenceSnapshotBatch(
        references=[
            ReferenceSnapshotItem(
                reference_id="fact-1",
                reference={"answer": "答案", "no_answer": False},
                supporting_chapter_indices=[1],
            )
        ]
    )
    cases = materialize_generated_cases(
        [
            GeneratedCaseDraft(
                scenario="exact_name",
                reference_id="fact-1",
                input={"query": "主角是谁？"},
            )
        ],
        suite="rag",
        corpus=_corpus(),
        run_meta=GenerationRunMeta(
            model=HIGH_QUALITY_LLM_MODEL,
            prompt_hash=_hash("prompt"),
            profile_hash=_hash("profile"),
        ),
        reference_snapshot=snapshot,
    )

    assert cases[0].generation_meta.model == "gpt-5.3-codex-spark"
    assert cases[0].generation_meta.seed == 20260711
    assert cases[0].reference["context_ids"] == ["fixture:chapter:1"]


def test_materialization_enforces_no_answer_and_hard_negative_invariants() -> None:
    snapshot = ReferenceSnapshotBatch(
        references=[
            ReferenceSnapshotItem(
                reference_id="no-answer-1",
                reference={"answer": None, "no_answer": True},
                supporting_chapter_indices=[1],
            )
        ]
    )
    cases = materialize_generated_cases(
        [
            GeneratedCaseDraft(
                scenario="no_answer",
                reference_id="no-answer-1",
                input={"query": "原文未提供的信息？"},
                hard_negative_chapter_indices=[1],
                risk_flags=["ordinary_generation_caveat"],
            )
        ],
        suite="rag",
        corpus=_corpus(),
        run_meta=GenerationRunMeta(
            model=HIGH_QUALITY_LLM_MODEL,
            prompt_hash=_hash("prompt"),
            profile_hash=_hash("profile"),
        ),
        reference_snapshot=snapshot,
    )

    assert cases[0].source_refs == []
    assert [ref.chapter_index for ref in cases[0].hard_negative_refs] == [1]
    assert cases[0].risk_level == RiskLevel.safety_critical


def test_materialization_preserves_visibility_cutoff() -> None:
    snapshot = ReferenceSnapshotBatch(
        references=[
            ReferenceSnapshotItem(
                reference_id="visible-fact",
                reference={"answer": "答案", "no_answer": False},
                supporting_chapter_indices=[1],
            )
        ]
    )

    cases = materialize_generated_cases(
        [
            GeneratedCaseDraft(
                scenario="visibility_cutoff",
                reference_id="visible-fact",
                input={"query": "截至第一章能看到什么？"},
                visible_until_chapter=1,
            )
        ],
        suite="rag",
        corpus=_corpus(),
        run_meta=GenerationRunMeta(
            model=HIGH_QUALITY_LLM_MODEL,
            prompt_hash=_hash("prompt"),
            profile_hash=_hash("profile"),
        ),
        reference_snapshot=snapshot,
    )

    assert cases[0].visibility.visible_until_chapter == 1


def test_prefixed_adjudicator_role_receives_disagreement_instructions() -> None:
    prompt = _model_review_prompt([], reviewer_role="scene-range-adjudicator")

    assert "这是分歧裁决" in prompt
    assert "这是独立审查" not in prompt


def test_ordinary_risk_flag_does_not_become_safety_critical() -> None:
    snapshot = ReferenceSnapshotBatch(
        references=[
            ReferenceSnapshotItem(
                reference_id="fact-1",
                reference={"answer": "答案", "no_answer": False},
                supporting_chapter_indices=[1],
            )
        ]
    )
    cases = materialize_generated_cases(
        [
            GeneratedCaseDraft(
                scenario="multi_hop",
                reference_id="fact-1",
                input={"query": "需要多跳推理的问题"},
                hard_negative_chapter_indices=[1],
                risk_flags=["因果顺序识别"],
            )
        ],
        suite="rag",
        corpus=_corpus(),
        run_meta=GenerationRunMeta(
            model=HIGH_QUALITY_LLM_MODEL,
            prompt_hash=_hash("prompt"),
            profile_hash=_hash("profile"),
        ),
        reference_snapshot=snapshot,
    )

    assert cases[0].hard_negative_refs == []
    assert cases[0].risk_level == RiskLevel.normal
    assert cases[0].rubric["persona"] == "author_retrieval"


@pytest.mark.asyncio
async def test_generation_rejects_uncovered_configured_scenarios() -> None:
    class FakeExecutor:
        meta = CodexExecutionMeta(
            model=HIGH_QUALITY_LLM_MODEL,
            executor_hash=_hash("executor"),
        )

        async def generate_structured(self, *_args, **_kwargs):
            return GeneratedCaseBatch(
                cases=[
                    GeneratedCaseDraft(
                        scenario="exact_name",
                        persona="writing_conflict",
                        reference_id="fact-1",
                        input={"query": "问题"},
                    )
                ]
            )

    snapshot = ReferenceSnapshotBatch(
        references=[
            ReferenceSnapshotItem(
                reference_id="fact-1",
                reference={"answer": "答案"},
                supporting_chapter_indices=[1],
            )
        ]
    )

    with pytest.raises(ValueError, match="miss required scenarios"):
        await HighQualityEvalLLM(FakeExecutor()).generate_cases(  # type: ignore[arg-type]
            suite="rag",
            source_excerpt="fixture",
            chapter_indices=[1],
            scenarios=["exact_name", "multi_hop"],
            count=2,
            reference_snapshot=snapshot,
        )


@pytest.mark.asyncio
async def test_generation_semantic_retry_repairs_unknown_scenario_and_caches_prompt(
    tmp_path: Path,
) -> None:
    class FakeExecutor:
        calls = 0
        meta = CodexExecutionMeta(
            model=HIGH_QUALITY_LLM_MODEL,
            executor_hash=_hash("executor"),
        )

        async def generate_structured(self, *_args, **_kwargs):
            self.calls += 1
            scenario = "early_reveal" if self.calls == 1 else "exact_name"
            return GeneratedCaseBatch(
                cases=[
                    GeneratedCaseDraft(
                        scenario=scenario,
                        reference_id="fact-1",
                        input={"query": "问题"},
                    )
                ]
            )

    executor = FakeExecutor()
    evaluator = HighQualityEvalLLM(  # type: ignore[arg-type]
        executor,
        cache=EvalCache(tmp_path),
    )
    kwargs = {
        "suite": "rag",
        "source_excerpt": "fixture",
        "chapter_indices": [1],
        "scenarios": ["exact_name"],
        "count": 1,
        "reference_snapshot": ReferenceSnapshotBatch(
            references=[
                ReferenceSnapshotItem(
                    reference_id="fact-1",
                    reference={"answer": "答案"},
                    supporting_chapter_indices=[1],
                )
            ]
        ),
    }

    generated, first_meta = await evaluator.generate_cases(**kwargs)
    cached, cached_meta = await evaluator.generate_cases(**kwargs)

    assert executor.calls == 2
    assert generated.cases[0].scenario == "exact_name"
    assert cached.cases[0].scenario == "exact_name"
    assert cached_meta.cached is True
    assert cached_meta.prompt_hash == first_meta.prompt_hash
    cache_payload = json.loads(
        next((tmp_path / "generation").glob("*.json")).read_text(encoding="utf-8")
    )
    assert cache_payload["prompt_hash"] != cache_payload["input_hash"]


def test_eval_cache_does_not_store_raw_prompt(tmp_path: Path) -> None:
    cache = EvalCache(tmp_path)
    key = cache.key({"prompt_hash": _hash("private source")})
    path = cache.put("fixture", key, {"result": {"accepted": True}})

    assert "private source" not in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_generation_cache_prevents_duplicate_codex_calls(tmp_path: Path) -> None:
    class FakeExecutor:
        calls = 0
        meta = CodexExecutionMeta(
            model=HIGH_QUALITY_LLM_MODEL,
            executor_hash=_hash("executor"),
        )

        async def generate_structured(self, *_args, **_kwargs):
            self.calls += 1
            return GeneratedCaseBatch(
                cases=[
                    GeneratedCaseDraft(
                        scenario="exact_name",
                        reference_id="fact-1",
                        input={"query": "问题"},
                    )
                ]
            )

    executor = FakeExecutor()
    evaluator = HighQualityEvalLLM(  # type: ignore[arg-type]
        executor,
        cache=EvalCache(tmp_path),
    )
    kwargs = {
        "suite": "rag",
        "source_excerpt": "fixture",
        "chapter_indices": [1],
        "scenarios": ["exact_name"],
        "count": 1,
        "reference_snapshot": ReferenceSnapshotBatch(
            references=[
                ReferenceSnapshotItem(
                    reference_id="fact-1",
                    reference={"answer": "答案"},
                    supporting_chapter_indices=[1],
                )
            ]
        ),
    }

    await evaluator.generate_cases(**kwargs)
    await evaluator.generate_cases(**kwargs)

    assert executor.calls == 1
    cache_payload = json.loads(
        next((tmp_path / "generation").glob("*.json")).read_text(encoding="utf-8")
    )
    assert cache_payload["input_hash"] == cache_payload["prompt_hash"]
    assert cache_payload["metric_version"] == "v1"
    assert cache_payload["rubric_version"] == "v1"
    assert cache_payload["temperature_profile"] == "codex_cli_fixed"
    assert "duration_ms" in cache_payload
    assert "fixture" not in json.dumps(cache_payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_luna_fallback_replays_primary_cache_with_original_provenance(
    tmp_path: Path,
) -> None:
    class FakeExecutor:
        def __init__(self, model: str) -> None:
            self.model = model
            self.calls = 0
            self.meta = CodexExecutionMeta(
                model=model,
                executor_hash=_hash(model),
            )

        async def generate_structured(self, *_args, **_kwargs):
            self.calls += 1
            return ReferenceSnapshotBatch(
                references=[
                    ReferenceSnapshotItem(
                        reference_id="fact-1",
                        reference={"answer": "答案"},
                        supporting_chapter_indices=[1],
                    )
                ]
            )

    kwargs = {
        "suite": "rag",
        "source_excerpt": "fixture",
        "chapter_indices": [1],
        "scenarios": ["exact_name"],
        "count": 1,
    }
    primary = FakeExecutor(HIGH_QUALITY_LLM_MODEL)
    _, primary_meta = await HighQualityEvalLLM(  # type: ignore[arg-type]
        primary,
        cache=EvalCache(tmp_path),
    ).generate_reference_snapshot(**kwargs)
    fallback = FakeExecutor("gpt-5.6-luna")
    _, replay_meta = await HighQualityEvalLLM(  # type: ignore[arg-type]
        fallback,
        cache=EvalCache(tmp_path),
    ).generate_reference_snapshot(**kwargs)

    assert primary.calls == 1
    assert fallback.calls == 0
    assert primary_meta.model == HIGH_QUALITY_LLM_MODEL
    assert replay_meta.model == HIGH_QUALITY_LLM_MODEL
    assert replay_meta.profile_hash == _hash(HIGH_QUALITY_LLM_MODEL)
    assert replay_meta.cached is True


@pytest.mark.asyncio
async def test_role_pinned_eval_does_not_replay_another_models_cache(
    tmp_path: Path,
) -> None:
    class FakeExecutor:
        def __init__(self, model: str) -> None:
            self.model = model
            self.calls = 0
            self.meta = CodexExecutionMeta(
                model=model,
                executor_hash=_hash(model),
                reasoning_effort="medium" if model == "gpt-5.6-luna" else None,
            )

        async def generate_structured(self, *_args, **_kwargs):
            self.calls += 1
            return ReferenceSnapshotBatch(
                references=[
                    ReferenceSnapshotItem(
                        reference_id="fact-1",
                        reference={"answer": "答案"},
                        supporting_chapter_indices=[1],
                    )
                ]
            )

    kwargs = {
        "suite": "rag",
        "source_excerpt": "fixture",
        "chapter_indices": [1],
        "scenarios": ["exact_name"],
        "count": 1,
    }
    primary = FakeExecutor(HIGH_QUALITY_LLM_MODEL)
    await HighQualityEvalLLM(  # type: ignore[arg-type]
        primary,
        cache=EvalCache(tmp_path),
    ).generate_reference_snapshot(**kwargs)
    pinned = FakeExecutor("gpt-5.6-luna")
    _, meta = await HighQualityEvalLLM(  # type: ignore[arg-type]
        pinned,
        cache=EvalCache(tmp_path),
        allow_primary_cache_fallback=False,
    ).generate_reference_snapshot(**kwargs)

    assert pinned.calls == 1
    assert meta.model == "gpt-5.6-luna"
    assert meta.cached is False


@pytest.mark.asyncio
async def test_cache_only_generation_never_starts_codex_on_miss(tmp_path: Path) -> None:
    class FakeExecutor:
        calls = 0
        meta = CodexExecutionMeta(
            model=HIGH_QUALITY_LLM_MODEL,
            executor_hash=_hash("executor"),
        )

        async def generate_structured(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("cache-only mode must not start Codex")

    executor = FakeExecutor()
    evaluator = HighQualityEvalLLM(  # type: ignore[arg-type]
        executor,
        cache=EvalCache(tmp_path),
        cache_only=True,
    )

    with pytest.raises(RuntimeError, match="cache-only mode: cache miss"):
        await evaluator.generate_reference_snapshot(
            suite="rag",
            source_excerpt="fixture",
            chapter_indices=[1],
            scenarios=["exact_name"],
            count=1,
        )

    assert executor.calls == 0


def test_judge_status_routes_disagreement_and_safety_to_review() -> None:
    accepted = JudgeDecision(
        natural_query=True,
        answerable=True,
        correctly_no_answer=False,
        reference_faithful=True,
        reference_complete=True,
        hard_negative_valid=True,
        decision="accept",
        reason="ok",
    )
    rejected = accepted.model_copy(update={"decision": "reject"})
    normal = _case(EvalSuite.rag, "rag-judge-1", {"answer": "x"})
    safety = normal.model_copy(update={"risk_level": RiskLevel.safety_critical})

    assert _judge_status(normal, [accepted]) == "accepted"
    assert _judge_status(normal, [accepted, rejected]) == "review"
    assert _judge_status(safety, [accepted, accepted]) == "review"


@pytest.mark.asyncio
async def test_batch_judge_requires_and_returns_every_case_id() -> None:
    cases = [
        _case(EvalSuite.rag, "rag-batch-1", {"answer": "a"}),
        _case(EvalSuite.rag, "rag-batch-2", {"answer": "b"}),
    ]

    class FakeExecutor:
        meta = CodexExecutionMeta(
            model=HIGH_QUALITY_LLM_MODEL,
            executor_hash=_hash("executor"),
        )

        async def generate_structured(self, *_args, **_kwargs):
            return JudgeDecisionBatch(
                decisions=[
                    JudgeDecisionItem(
                        case_id=case.case_id,
                        natural_query=True,
                        answerable=True,
                        correctly_no_answer=False,
                        reference_faithful=True,
                        reference_complete=True,
                        hard_negative_valid=True,
                        decision="accept",
                        reason="ok",
                    )
                    for case in cases
                ]
            )

    decisions, meta = await HighQualityEvalLLM(  # type: ignore[arg-type]
        FakeExecutor()
    ).judge_cases(cases, source_excerpt="fixture", judge_round=1)

    assert set(decisions) == {"rag-batch-1", "rag-batch-2"}
    assert meta.profile_hash == _hash("executor")
    assert meta.duration_ms >= 0


def test_judge_batches_never_mix_source_groups() -> None:
    cases = [
        _case(EvalSuite.rag, f"rag-group-{index}", {"answer": "a"}).model_copy(
            update={"source_group_id": f"group-{index % 2}"}
        )
        for index in range(12)
    ]

    batches = _judge_batches(cases, batch_size=4)

    assert all(len(batch) <= 4 for batch in batches)
    assert all(len({case.source_group_id for case in batch}) == 1 for batch in batches)


def test_pilot_suite_sizes_match_plan_raw_candidate_target() -> None:
    assert PILOT_RAW_STEM.endswith("raw-judged")
    assert PILOT_SUITE_SIZES == {
        "rag": 160,
        "scene": 80,
        "world": 100,
        "outline": 60,
    }
    assert sum(PILOT_SUITE_SIZES.values()) == 400


@pytest.mark.asyncio
async def test_codex_executor_is_ephemeral_isolated_and_schema_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    class FakeProcess:
        returncode = 0

        def __init__(self, args: tuple[str, ...]) -> None:
            self.args = args

        async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
            assert b"fixture-step" in request
            output_index = self.args.index("--output-last-message") + 1
            Path(self.args[output_index]).write_text('{"cases": []}', encoding="utf-8")
            return b"model: gpt-5.3-codex-spark", b""

    async def fake_create_subprocess_exec(*args: str, **kwargs: object) -> FakeProcess:
        captured.extend(args)
        assert kwargs["start_new_session"] is True
        return FakeProcess(args)

    monkeypatch.setattr(
        "evals.codex_executor.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    executor = CodexStructuredExecutor(command="python", attempts=1)
    result = await executor.generate_structured(
        "fixture prompt",
        GeneratedCaseBatch,
        step_name="fixture-step",
    )

    assert result.cases == []
    assert "--ephemeral" in captured
    assert "--ignore-user-config" in captured
    assert "--ignore-rules" in captured
    assert "image_generation" in captured
    assert "plugins" in captured
    assert "shell_tool" in captured
    assert "read-only" in captured
    assert captured[-1] == "-"


@pytest.mark.asyncio
async def test_codex_executor_timeout_kills_the_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[tuple[int, int]] = []

    class HangingProcess:
        pid = 43210
        returncode = None

        async def communicate(self, _request: bytes):
            await asyncio.Future()

        async def wait(self) -> None:
            self.returncode = -9

        def kill(self) -> None:
            raise AssertionError("process-group kill should be used")

    async def fake_create_subprocess_exec(*_args: str, **kwargs: object):
        assert kwargs["start_new_session"] is True
        return HangingProcess()

    monkeypatch.setattr(
        "evals.codex_executor.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        "evals.codex_executor.os.killpg",
        lambda pid, sig: killed.append((pid, sig)),
    )

    executor = CodexStructuredExecutor(timeout_seconds=0.01, attempts=1)
    with pytest.raises(Exception, match="timed out"):
        await executor.generate_structured(
            "quota probe",
            GeneratedCaseBatch,
            step_name="quota-probe",
        )

    assert killed == [(43210, 9)]


def test_codex_executor_rejects_model_fallback() -> None:
    with pytest.raises(ValueError, match="eval model must be"):
        CodexStructuredExecutor(model="some-other-model")


def test_codex_executor_allows_explicit_luna_fallback(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_CODEX_MODEL", "gpt-5.6-luna")

    executor = CodexStructuredExecutor()

    assert executor.model == "gpt-5.6-luna"
    assert executor.reasoning_effort == "medium"
    assert executor.meta.model == "gpt-5.6-luna"
    assert executor.meta.reasoning_effort == "medium"


def test_codex_executor_rejects_reviewer_model_for_generator_judge() -> None:
    with pytest.raises(ValueError, match="eval model must be"):
        CodexStructuredExecutor(model="gpt-5.6-terra")

    reviewer = CodexStructuredExecutor(
        model="gpt-5.6-terra",
        allowed_models=ALLOWED_CODEX_REVIEW_MODELS,
    )
    assert reviewer.model == "gpt-5.6-terra"


def test_codex_executor_normalizes_pydantic_schema_for_strict_output() -> None:
    schema = _strict_json_schema(GeneratedCaseBatch.model_json_schema())
    draft_schema = schema["$defs"]["GeneratedCaseDraft"]

    assert set(schema["required"]) == {"cases"}
    assert set(draft_schema["required"]) == set(draft_schema["properties"])


@pytest.mark.asyncio
async def test_reference_snapshot_is_generated_before_questions() -> None:
    calls: list[str] = []

    class FakeExecutor:
        meta = CodexExecutionMeta(
            model=HIGH_QUALITY_LLM_MODEL,
            executor_hash=_hash("executor"),
        )

        async def generate_structured(self, _prompt, response_model, *, step_name):
            calls.append(step_name)
            if response_model is ReferenceSnapshotBatch:
                return ReferenceSnapshotBatch(
                    references=[
                        ReferenceSnapshotItem(
                            reference_id="fact-1",
                            reference={"answer": "冻结答案"},
                            supporting_chapter_indices=[1],
                        )
                    ]
                )
            return GeneratedCaseBatch(
                cases=[
                    GeneratedCaseDraft(
                        scenario="exact_name",
                        reference_id="fact-1",
                        input={"query": "自然问题"},
                    )
                ]
            )

    evaluator = HighQualityEvalLLM(FakeExecutor())  # type: ignore[arg-type]
    snapshot, _ = await evaluator.generate_reference_snapshot(
        suite="rag",
        source_excerpt="fixture",
        chapter_indices=[1],
        scenarios=["exact_name"],
        count=1,
    )
    cases, _ = await evaluator.generate_cases(
        suite="rag",
        source_excerpt="fixture",
        chapter_indices=[1],
        scenarios=["exact_name"],
        count=1,
        reference_snapshot=snapshot,
    )

    assert calls == [
        "eval.dataset.generate_reference_snapshot.structured",
        "eval.dataset.generate_cases.structured",
    ]
    assert cases.cases[0].reference_id == "fact-1"


@pytest.mark.asyncio
async def test_ragas_adapter_routes_structured_calls_to_local_codex() -> None:
    class FixtureResult(BaseModel):
        accepted: bool

    class FakeExecutor:
        async def generate_structured(
            self,
            prompt: str,
            response_model: type[BaseModel],
            *,
            step_name: str,
        ) -> BaseModel:
            assert prompt == "fixture"
            assert step_name == "eval.ragas.FixtureResult"
            return response_model.model_validate({"accepted": True})

    llm = build_codex_ragas_llm(FakeExecutor())  # type: ignore[arg-type]
    result = await llm.agenerate("fixture", FixtureResult)

    assert result.accepted is True


@pytest.mark.asyncio
async def test_rag_runner_uses_facade_shape_and_scores_ids() -> None:
    case = _case(
        EvalSuite.rag,
        "rag-0001",
        {
            "answer": "答案",
            "context_ids": ["fixture:chapter:1"],
            "no_answer": False,
        },
    )
    captured: dict[str, object] = {}

    async def retrieve(*_args, **kwargs):
        captured.update(kwargs)
        return RagResultBundle(
            chunks=[
                RagChunkContract(
                    id=str(uuid.uuid4()),
                    novel_id=str(uuid.uuid4()),
                    source_type="chapter_text",
                    chapter_index=1,
                )
            ],
            total=1,
            query="问题",
        )

    result = await evaluate_rag_cases(
        None,  # type: ignore[arg-type]
        str(uuid.uuid4()),
        [case],
        dataset_id="fixture",
        dataset_version="v1",
        retrieve_fn=retrieve,
    )

    assert {metric.name: metric.value for metric in result.metrics}["mrr"] == 1.0
    assert captured["visibility"] is None
    rag_metrics = {metric.name: metric for metric in result.metrics}
    assert rag_metrics["source_hash_validity"].available is False
    assert rag_metrics["ragas_context_precision"].available is False
    assert rag_metrics["macro_scenario_mrr"].details["scenario_count"] == 1
    assert result.completed_at is not None
    assert result.started_at <= result.completed_at


@pytest.mark.asyncio
async def test_rag_ranking_metrics_exclude_no_answer_cases() -> None:
    answerable = _case(
        EvalSuite.rag,
        "rag-answerable",
        {
            "answer": "答案",
            "context_ids": ["fixture:chapter:1"],
            "no_answer": False,
        },
    )
    no_answer = _case(
        EvalSuite.rag,
        "rag-no-answer",
        {"no_answer": True, "context_ids": []},
    )

    async def retrieve(_db, _novel_id, query, **_kwargs):
        chunks = []
        if query == "问题" and not chunks:
            # The first invocation belongs to the answerable fixture.
            retrieve.calls += 1
            if retrieve.calls == 1:
                chunks = [
                    RagChunkContract(
                        id=str(uuid.uuid4()),
                        novel_id=str(uuid.uuid4()),
                        source_type="chapter_text",
                        chapter_index=1,
                    )
                ]
        return RagResultBundle(chunks=chunks, total=len(chunks), query=query)

    retrieve.calls = 0
    result = await evaluate_rag_cases(
        None,  # type: ignore[arg-type]
        str(uuid.uuid4()),
        [answerable, no_answer],
        dataset_id="fixture",
        dataset_version="v1",
        retrieve_fn=retrieve,
    )

    metrics = {metric.name: metric for metric in result.metrics}
    assert metrics["p_at_5"].value == 1.0
    assert metrics["mrr"].value == 1.0
    assert metrics["r_at_10"].value == 1.0
    assert metrics["no_answer_false_positive_rate"].value == 0.0
    assert metrics["mrr"].details == {
        "aggregation_scope": "answerable_cases_only",
        "eligible_case_count": 1,
        "no_answer_case_count": 1,
    }
    assert result.case_results[1]["ranking_eligible"] is False


@pytest.mark.asyncio
async def test_rag_preflight_requires_sources_and_fresh_index_per_chapter() -> None:
    refs = [
        LogicalSourceRef(
            corpus_id="fixture",
            source_alias="fixture",
            source_group_id="group-1",
            chapter_index=chapter,
            content_hash=_hash(f"chapter-{chapter}"),
        )
        for chapter in (1, 2)
    ]
    case = _case(
        EvalSuite.rag,
        "rag-preflight-1",
        {"context_ids": ["fixture:chapter:1"]},
    ).model_copy(update={"source_refs": refs})

    async def list_sources(*_args, **_kwargs):
        return [type("Source", (), {"chapter_index": chapter})() for chapter in (1, 2)]

    async def fresh(*_args, **kwargs):
        chapter = kwargs["chapter_from"]
        return {"total": 1, "fresh": int(chapter == 1), "stale": int(chapter == 2)}

    async def index_status(*_args, **_kwargs):
        return {
            "embedding_failed_count": 0,
            "pending_vectorization": 0,
            "embedding_dimension_mismatch": False,
            "embedding_provider": "fixture",
            "embedding_model": "fixture",
        }

    with pytest.raises(ValueError, match="stale_index_chapters"):
        await _rag_preflight(
            object(),
            "novel-1",
            [case],
            list_sources_fn=list_sources,
            freshness_fn=fresh,
            index_status_fn=index_status,
        )

    async def all_fresh(*_args, **_kwargs):
        return {"total": 1, "fresh": 1, "stale": 0}

    report = await _rag_preflight(
        object(),
        "novel-1",
        [case],
        list_sources_fn=list_sources,
        freshness_fn=all_fresh,
        index_status_fn=index_status,
    )
    assert report["ready"] is True
    assert report["content_modes"]["canonical"]["fresh_index_chapter_count"] == 2


def test_structured_suite_runners_enforce_safety_metrics() -> None:
    scene_case = _case(
        EvalSuite.scene,
        "scene-0001",
        {"boundary_offsets": [100]},
    )
    world_case = _case(
        EvalSuite.world,
        "world-0001",
        {"entity": {"name": "克莱恩"}},
    )
    outline_case = _case(EvalSuite.outline, "outline-0001", {})

    scene = evaluate_scene_cases(
        [scene_case],
        {"scene-0001": {"boundary_offsets": [120], "chapter_indices": [1]}},
        dataset_id="fixture",
        dataset_version="v1",
    )
    world = evaluate_world_cases(
        [world_case],
        {"world-0001": {"entity": {"name": "克莱恩"}}},
        dataset_id="fixture",
        dataset_version="v1",
    )
    outline = evaluate_outline_cases(
        [outline_case],
        {
            "outline-0001": {
                "source_refs_valid": True,
                "rubric_score": 5,
            }
        },
        dataset_id="fixture",
        dataset_version="v1",
    )

    assert all(metric.passed is not False for metric in scene.metrics)
    assert all(metric.passed is not False for metric in world.metrics)
    assert all(metric.passed is not False for metric in outline.metrics)
    assert all(
        result.completed_at is not None and result.started_at <= result.completed_at
        for result in (scene, world, outline)
    )
    assert {
        "chapter_coverage",
        "wrong_mapping_attribution_count",
        "source_hash_invalid_count",
        "high_quality_fallback_rate",
    }.issubset({metric.name for metric in scene.metrics})
    assert {
        "ordinary_object_pollution_rate",
        "unresolved_endpoint_valid_relation_count",
        "source_quote_range_validity",
        "workflow_rollback_overreach_count",
    }.issubset({metric.name for metric in world.metrics})


def test_world_frozen_reference_shape_has_honest_zero_prediction_metrics() -> None:
    cases = [
        _case(
            EvalSuite.world,
            "world-frozen-entity",
            {"entity": {"name": "克莱恩", "entity_type": "durable_entity"}},
        ).model_copy(update={"scenario": "durable_entity"}),
        _case(
            EvalSuite.world,
            "world-frozen-alias",
            {"entity": {"name": "黑荆棘安保公司", "entity_type": "alias"}},
        ).model_copy(update={"scenario": "alias"}),
        _case(
            EvalSuite.world,
            "world-frozen-relation",
            {"entity": {"name": "克莱恩-哥哥", "entity_type": "relation"}},
        ).model_copy(update={"scenario": "relation"}),
    ]

    result = evaluate_world_cases(
        cases,
        {},
        dataset_id="fixture",
        dataset_version="v1",
    )
    metrics = {metric.name: metric for metric in result.metrics}
    for target_kind in ("entity", "alias", "relation"):
        precision = metrics[f"{target_kind}_precision"]
        assert precision.available is False
        assert precision.value is None
        assert precision.passed is None
        assert precision.details == {
            "definition": "case_target",
            "reference_count": 1,
            "prediction_count": 0,
            "true_positive_count": 0,
            "false_positive_count": 0,
            "false_negative_count": 1,
            "reason": f"World output has no {target_kind} predictions",
        }
        assert metrics[f"{target_kind}_recall"].value == 0.0
        assert metrics[f"{target_kind}_prediction_coverage"].value == 0.0
    assert result.case_results == [
        {
            "case_id": "world-frozen-entity",
            "target_kind": "entity",
            "reference_available": True,
            "prediction_available": False,
            "entity_correct": False,
        },
        {
            "case_id": "world-frozen-alias",
            "target_kind": "alias",
            "reference_available": True,
            "prediction_available": False,
            "alias_correct": False,
        },
        {
            "case_id": "world-frozen-relation",
            "target_kind": "relation",
            "reference_available": True,
            "prediction_available": False,
            "relation_correct": False,
        },
    ]


def test_world_frozen_scenario_labels_are_not_production_entity_types() -> None:
    cases = [
        _case(
            EvalSuite.world,
            "world-frozen-entity-match",
            {"entity": {"name": "邓恩·史密斯", "entity_type": "durable_entity"}},
        ).model_copy(update={"scenario": "durable_entity"}),
        _case(
            EvalSuite.world,
            "world-frozen-alias-match",
            {"entity": {"name": "黑荆棘安保公司", "entity_type": "alias"}},
        ).model_copy(update={"scenario": "alias"}),
        _case(
            EvalSuite.world,
            "world-frozen-relation-match",
            {"entity": {"name": "克莱恩-哥哥", "entity_type": "relation"}},
        ).model_copy(update={"scenario": "relation"}),
    ]
    predictions = {
        "world-frozen-entity-match": {
            "entity": {"name": "邓恩·史密斯", "entity_type": "character"}
        },
        "world-frozen-alias-match": {
            "alias_target": {
                "name": "黑荆棘安保公司",
                "entity_type": "organization",
            }
        },
        "world-frozen-relation-match": {
            "relation": {"name": "克莱恩-哥哥", "entity_type": "character"}
        },
    }

    result = evaluate_world_cases(
        cases,
        predictions,
        dataset_id="fixture",
        dataset_version="v1",
    )
    metrics = {metric.name: metric for metric in result.metrics}
    for target_kind in ("entity", "alias", "relation"):
        assert metrics[f"{target_kind}_precision"].value == 1.0
        assert metrics[f"{target_kind}_recall"].value == 1.0
        assert metrics[f"{target_kind}_prediction_coverage"].value == 1.0
    assert [
        result.case_results[index].get(f"{target_kind}_correct")
        for index, target_kind in enumerate(("entity", "alias", "relation"))
    ] == [True, True, True]


def test_world_legacy_reference_fields_remain_supported() -> None:
    alias_case = _case(
        EvalSuite.world,
        "world-legacy-alias",
        {"alias_target": "莫雷蒂先生"},
    )
    relation_case = _case(
        EvalSuite.world,
        "world-legacy-relation",
        {"relation": {"source": "克莱恩", "target": "梅丽莎"}},
    )
    result = evaluate_world_cases(
        [alias_case, relation_case],
        {
            alias_case.case_id: {"alias_target": "莫雷蒂先生"},
            relation_case.case_id: {"relation": {"source": "克莱恩", "target": "梅丽莎"}},
        },
        dataset_id="fixture",
        dataset_version="v1",
    )
    metrics = {metric.name: metric for metric in result.metrics}
    assert metrics["alias_precision"].value == 1.0
    assert metrics["relation_precision"].value == 1.0


@pytest.mark.asyncio
async def test_scene_workflow_runner_uses_stage_commit_and_span_seams() -> None:
    case = _case(
        EvalSuite.scene,
        "scene-workflow-1",
        {"boundary_offsets": [0, 40], "chapter_indices": [1]},
    ).model_copy(
        update={
            "source_refs": [
                LogicalSourceRef(
                    corpus_id="fixture-corpus",
                    source_alias="fixture",
                    source_group_id="group-1",
                    chapter_index=1,
                    content_hash=_hash("chapter"),
                    range_hash=_hash("chapter:100-140"),
                    start_offset=100,
                    end_offset=140,
                )
            ]
        }
    )
    calls: list[tuple[str, dict]] = []

    async def submit(*_args, **kwargs):
        calls.append(("submit", kwargs))
        return {"task_id": "task-1", "requires_confirmation": False}

    async def run(*_args, **kwargs):
        calls.append(("run", kwargs))
        return {"phase": "completed"}

    async def spans(*_args, **kwargs):
        calls.append(("spans", kwargs))
        return [
            type(
                "Span",
                (),
                {
                    "start_offset": 100,
                    "end_offset": 140,
                    "chapter_index": 1,
                    "mapping_status": "exact",
                    "source_content_hash": _hash("chapter"),
                },
            )()
        ]

    async def sources(*_args, **kwargs):
        calls.append(("sources", kwargs))
        return [
            type(
                "Source",
                (),
                {"chapter_index": 1, "content_hash": _hash("chapter")},
            )()
        ]

    result = await run_scene_workflow_cases(
        None,  # type: ignore[arg-type]
        "novel-1",
        [case],
        dataset_id="fixture",
        dataset_version="v1",
        isolated_db=True,
        submit_stage_fn=submit,
        run_stage_fn=run,
        load_spans_fn=spans,
        list_sources_fn=sources,
    )

    assert [name for name, _ in calls] == ["submit", "run", "spans", "sources"]
    assert calls[0][1]["authorization_confirmed"] is True
    assert calls[0][1]["high_quality"] is False
    assert calls[2][1]["content_mode"] == "canonical"
    assert {metric.name: metric.value for metric in result.metrics}["boundary_f1"] == 1.0
    assert result.run_context["boundary_coordinate_system"] == (
        "canonical_chapter_offset"
    )


@pytest.mark.asyncio
async def test_scene_workflow_runner_blocks_input_relative_gold_before_llm() -> None:
    case = _case(
        EvalSuite.scene,
        "scene-workflow-input-relative",
        {"boundary_offsets": [0, 12], "chapter_indices": [1]},
    )
    called = False

    async def submit(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"task_id": "unexpected"}

    result = await run_scene_workflow_cases(
        None,  # type: ignore[arg-type]
        "novel-1",
        [case],
        dataset_id="fixture",
        dataset_version="v1",
        isolated_db=True,
        submit_stage_fn=submit,
    )

    assert called is False
    assert result.errors == ["scene_reference_coordinate_unavailable"]
    assert result.run_context["reference_coordinate_preflight"] == {
        "ready": False,
        "reason": (
            "Scene gold lacks canonical chapter-local source ranges; "
            "input.text-relative offsets cannot be compared with SceneSpan offsets"
        ),
        "invalid_case_count": 1,
        "invalid_case_ids": ["scene-workflow-input-relative"],
    }
    assert all(metric.available is False for metric in result.metrics)


@pytest.mark.asyncio
async def test_scene_workflow_runner_rejects_nonisolated_database() -> None:
    with pytest.raises(ValueError, match="isolated_db=True"):
        await run_scene_workflow_cases(
            None,  # type: ignore[arg-type]
            "novel-1",
            [],
            dataset_id="fixture",
            dataset_version="v1",
            isolated_db=False,
        )


@pytest.mark.asyncio
async def test_world_workflow_runner_uses_deep_import_stage() -> None:
    case = _case(
        EvalSuite.world,
        "world-workflow-1",
        {
            "entity": {"name": "测试人物", "entity_type": "character"},
            "chapter_indices": [1],
        },
    )
    second_case = _case(
        EvalSuite.world,
        "world-workflow-2",
        {
            "entity": {"name": "另一个人物", "entity_type": "character"},
            "chapter_indices": [3],
        },
    )
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    async def submit(*args, **kwargs):
        calls.append(("submit", args, kwargs))
        return {"task_id": "world-task-1", "requires_confirmation": False}

    async def spans(*args, **kwargs):
        calls.append(("spans", args, kwargs))
        chapter_index = int(args[2])
        return [
            type(
                "Span",
                (),
                {
                    "id": f"span-{chapter_index}",
                    "mapping_status": "exact",
                    "start_offset": 0,
                    "end_offset": 10,
                    "source_content_hash": _hash(f"chapter-{chapter_index}"),
                },
            )()
        ]

    async def run(*args, **kwargs):
        calls.append(("run", args, kwargs))
        return {
            "phase": "done",
            "quality_status": "passed",
        }

    async def load(*args, **kwargs):
        calls.append(("load", args, kwargs))
        return [
            {
                "name": "测试人物",
                "entity_type": "character",
                "content_json": {"_meta": {"workflow_id": "world-task-1"}},
            },
            {
                "name": "另一个人物",
                "entity_type": "character",
                "content_json": {"_meta": {"workflow_id": "world-task-1"}},
            },
        ]

    result = await run_world_workflow_cases(
        None,  # type: ignore[arg-type]
        "novel-1",
        [case, second_case],
        dataset_id="fixture",
        dataset_version="v1",
        isolated_db=True,
        submit_stage_fn=submit,
        run_stage_fn=run,
        load_entities_fn=load,
        load_scene_spans_fn=spans,
    )

    assert [call[0] for call in calls[:2]] == ["spans", "spans"]
    assert calls[2] == (
        "submit",
        (None, "novel-1", 1, 3),
        {
            "stage": "world_objects",
            "force": True,
            "high_quality": False,
            "authorization_confirmed": True,
        },
    )
    assert calls[3] == (
        "run",
        (None, "world-task-1"),
        {"stage": "world_objects"},
    )
    assert calls[4][0] == "load"
    assert result.run_context["workflow_batches"]["chapter_indices"] == [1, 3]
    assert {metric.name: metric.value for metric in result.metrics}[
        "entity_precision"
    ] == 1.0


@pytest.mark.asyncio
async def test_world_workflow_runner_requires_persisted_alias_evidence() -> None:
    alias_case = _case(
        EvalSuite.world,
        "world-workflow-alias",
        {
            "entity": {"name": "黑荆棘安保公司", "entity_type": "alias"},
            "chapter_indices": [1],
        },
    ).model_copy(update={"scenario": "alias"})
    relation_case = _case(
        EvalSuite.world,
        "world-workflow-relation",
        {
            "entity": {"name": "克莱恩-哥哥", "entity_type": "relation"},
            "chapter_indices": [1],
        },
    ).model_copy(update={"scenario": "relation"})

    async def submit(*_args, **_kwargs):
        return {"task_id": "world-task-alias", "requires_confirmation": False}

    async def spans(*_args, **_kwargs):
        return [
            type(
                "Span",
                (),
                {
                    "id": "span-1",
                    "mapping_status": "exact",
                    "start_offset": 0,
                    "end_offset": 10,
                    "source_content_hash": _hash("chapter-1"),
                },
            )()
        ]

    async def run(*_args, **_kwargs):
        return {"phase": "done", "quality_status": "passed"}

    async def load(*_args, **_kwargs):
        return [
            {
                "name": "黑荆棘安保公司",
                "entity_type": "organization",
                "content_json": {
                    "aliases": [{"alias": "值夜者小队"}],
                    "_meta": {"workflow_id": "world-task-alias"},
                },
            },
            {
                "name": "克莱恩-哥哥",
                "entity_type": "character",
                "content_json": {
                    "_meta": {"workflow_id": "world-task-alias"},
                },
            },
        ]

    result = await run_world_workflow_cases(
        None,  # type: ignore[arg-type]
        "novel-1",
        [alias_case, relation_case],
        dataset_id="fixture",
        dataset_version="v1",
        isolated_db=True,
        submit_stage_fn=submit,
        run_stage_fn=run,
        load_entities_fn=load,
        load_scene_spans_fn=spans,
    )

    metrics = {metric.name: metric for metric in result.metrics}
    assert metrics["alias_precision"].value == 1.0
    assert metrics["alias_recall"].value == 1.0
    assert metrics["relation_precision"].available is False
    assert metrics["relation_recall"].value == 0.0
    assert result.case_results[0]["alias_correct"] is True
    assert result.case_results[1]["relation_correct"] is False


@pytest.mark.asyncio
async def test_world_workflow_runner_persists_failed_stage_as_unavailable() -> None:
    case = _case(
        EvalSuite.world,
        "world-failed-1",
        {
            "entity": {"name": "测试人物", "entity_type": "character"},
            "chapter_indices": [1],
        },
    )

    async def submit(*args, **kwargs):
        return {"task_id": "world-task-failed", "requires_confirmation": False}

    async def spans(*args, **kwargs):
        return [
            type(
                "Span",
                (),
                {
                    "id": "span-1",
                    "mapping_status": "exact",
                    "start_offset": 0,
                    "end_offset": 10,
                    "source_content_hash": _hash("chapter-1"),
                },
            )()
        ]

    async def run(*args, **kwargs):
        return {
            "phase": "failed",
            "degraded_reason": "phase2a_failed",
            "bulk_error_kind": "unified_activation:batched",
            "completed_scenes": 0,
            "failed_scenes": 43,
        }

    result = await run_world_workflow_cases(
        None,  # type: ignore[arg-type]
        "novel-1",
        [case],
        dataset_id="fixture",
        dataset_version="v1",
        isolated_db=True,
        submit_stage_fn=submit,
        run_stage_fn=run,
        load_scene_spans_fn=spans,
    )

    assert result.errors == ["world_stage_failed:phase2a_failed"]
    assert all(metric.available is False for metric in result.metrics)
    assert all(metric.value is None for metric in result.metrics)
    assert result.run_context["workflow_batches"]["diagnostics"] == {
        "phase": "failed",
        "degraded_reason": "phase2a_failed",
        "bulk_error_kind": "unified_activation:batched",
        "completed_scenes": 0,
        "failed_scenes": 43,
    }


@pytest.mark.asyncio
async def test_world_workflow_runner_blocks_inexact_scene_spans_before_llm() -> None:
    case = _case(
        EvalSuite.world,
        "world-preflight-1",
        {"entity": {"name": "测试人物"}, "chapter_indices": [1]},
    )
    submitted = False

    async def submit(*_args, **_kwargs):
        nonlocal submitted
        submitted = True
        return {"task_id": "unexpected"}

    async def spans(*_args, **_kwargs):
        return [
            type(
                "Span",
                (),
                {
                    "id": "span-unresolved",
                    "mapping_status": "chapter_only",
                    "start_offset": None,
                    "end_offset": None,
                    "source_content_hash": _hash("chapter-1"),
                },
            )()
        ]

    result = await run_world_workflow_cases(
        None,  # type: ignore[arg-type]
        "novel-1",
        [case],
        dataset_id="fixture",
        dataset_version="v1",
        isolated_db=True,
        submit_stage_fn=submit,
        load_scene_spans_fn=spans,
    )

    assert submitted is False
    assert result.errors == ["world_preflight_unavailable:scene_span_coverage_incomplete"]
    assert result.run_context["scene_span_preflight"] == {
        "ready": False,
        "chapter_from": 1,
        "chapter_to": 1,
        "chapter_count": 1,
        "exact_chapter_count": 0,
        "span_count": 1,
        "unresolved_span_count": 1,
        "missing_chapters": [],
        "missing_exact_chapters": [1],
    }
    assert all(metric.available is False for metric in result.metrics)


@pytest.mark.asyncio
async def test_world_preflight_checks_only_dataset_reference_chapters() -> None:
    cases = [
        _case(
            EvalSuite.world,
            f"world-sparse-{chapter}",
            {
                "entity": {"name": f"对象{chapter}"},
                "chapter_indices": [chapter],
            },
        )
        for chapter in (1, 3)
    ]
    requested: list[int] = []

    async def spans(_db, _novel_id, chapter_index, **_kwargs):
        requested.append(chapter_index)
        return [
            type(
                "Span",
                (),
                {
                    "id": f"span-{chapter_index}",
                    "mapping_status": "exact",
                    "start_offset": 0,
                    "end_offset": 10,
                    "source_content_hash": _hash(f"chapter-{chapter_index}"),
                },
            )()
        ]

    async def submit(*_args, **_kwargs):
        return {"task_id": "world-sparse-task", "requires_confirmation": False}

    async def run(*_args, **_kwargs):
        return {"phase": "completed", "quality_status": "complete"}

    async def load(*_args, **_kwargs):
        return []

    await run_world_workflow_cases(
        None,  # type: ignore[arg-type]
        "novel-1",
        cases,
        dataset_id="fixture",
        dataset_version="v1",
        isolated_db=True,
        submit_stage_fn=submit,
        run_stage_fn=run,
        load_entities_fn=load,
        load_scene_spans_fn=spans,
    )

    assert requested == [1, 3]


@pytest.mark.asyncio
async def test_world_preflight_allows_review_span_when_exact_span_exists() -> None:
    case = _case(
        EvalSuite.world,
        "world-mixed-span",
        {"entity": {"name": "对象"}, "chapter_indices": [1]},
    )
    submitted = False

    async def spans(*_args, **_kwargs):
        return [
            type(
                "Span",
                (),
                {
                    "id": "span-exact",
                    "mapping_status": "exact",
                    "start_offset": 0,
                    "end_offset": 10,
                    "source_content_hash": _hash("chapter-1"),
                },
            )(),
            type(
                "Span",
                (),
                {
                    "id": "span-review",
                    "mapping_status": "chapter_only",
                    "start_offset": None,
                    "end_offset": None,
                    "source_content_hash": None,
                },
            )(),
        ]

    async def submit(*_args, **_kwargs):
        nonlocal submitted
        submitted = True
        return {"task_id": "world-mixed-task", "requires_confirmation": False}

    async def run(*_args, **_kwargs):
        return {"phase": "done", "quality_status": "complete"}

    async def load(*_args, **_kwargs):
        return []

    result = await run_world_workflow_cases(
        None,  # type: ignore[arg-type]
        "novel-1",
        [case],
        dataset_id="fixture",
        dataset_version="v1",
        isolated_db=True,
        submit_stage_fn=submit,
        run_stage_fn=run,
        load_entities_fn=load,
        load_scene_spans_fn=spans,
    )

    assert submitted is True
    assert result.run_context["scene_span_preflight"]["ready"] is True
    assert result.run_context["scene_span_preflight"]["unresolved_span_count"] == 1


@pytest.mark.asyncio
async def test_world_workflow_runner_rejects_nonisolated_database() -> None:
    with pytest.raises(ValueError, match="isolated_db=True"):
        await run_world_workflow_cases(
            None,  # type: ignore[arg-type]
            "novel-1",
            [],
            dataset_id="fixture",
            dataset_version="v1",
            isolated_db=False,
        )


@pytest.mark.asyncio
async def test_outline_runner_uses_preview_without_apply() -> None:
    case = _case(EvalSuite.outline, "outline-preview-1", {"action": "preview"})
    calls: list[dict] = []

    async def preview(*_args, **kwargs):
        calls.append(kwargs)
        return {
            "case_predictions": {
                case.case_id: {
                    "source_refs_valid": True,
                    "rubric_score": 5,
                }
            }
        }

    result = await run_outline_preview_cases(
        None,  # type: ignore[arg-type]
        "novel-1",
        [case],
        dataset_id="fixture",
        dataset_version="v1",
        isolated_db=True,
        preview_fn=preview,
    )

    assert calls == [{"limit": 1000, "max_suggestions": 80}]
    metrics = {metric.name: metric for metric in result.metrics}
    assert metrics["source_ref_validity"].value == 1.0
    assert metrics["unconfirmed_asset_write_count"].value == 0.0
    assert metrics["unsupported_fact_rate"].available is False


@pytest.mark.asyncio
async def test_outline_runner_rejects_nonisolated_database() -> None:
    with pytest.raises(ValueError, match="isolated_db=True"):
        await run_outline_preview_cases(
            None,  # type: ignore[arg-type]
            "novel-1",
            [],
            dataset_id="fixture",
            dataset_version="v1",
            isolated_db=False,
        )


@pytest.mark.asyncio
async def test_workflow_eval_cli_dispatches_rag_and_writes_versioned_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = _case(
        EvalSuite.rag,
        "rag-cli-1",
        {"answer": "答案", "context_ids": [], "no_answer": False},
    )
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(case.model_dump_json() + "\n", encoding="utf-8")

    class Database:
        def __init__(self) -> None:
            self.committed = False

        async def commit(self) -> None:
            self.committed = True

    db = Database()

    class SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return None

    class Manager:
        session_factory = SessionContext

        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    manager = Manager()
    captured: dict[str, object] = {}

    async def evaluate(actual_db, novel_id, cases, **kwargs):
        captured.update(
            db=actual_db,
            novel_id=novel_id,
            case_ids=[item.case_id for item in cases],
            kwargs=kwargs,
        )
        return EvalResult(
            suite=EvalSuite.rag,
            dataset_id=kwargs["dataset_id"],
            dataset_version=kwargs["dataset_version"],
            case_results=[{"case_id": cases[0].case_id}],
        )

    monkeypatch.setattr("core.database.get_manager", lambda: manager)
    monkeypatch.setattr("evals.runners.rag.evaluate_rag_cases", evaluate)

    async def preflight(*_args, **_kwargs):
        return {"ready": True, "content_modes": {}}

    monkeypatch.setattr("evals.cli._rag_preflight", preflight)

    @asynccontextmanager
    async def open_profile_client(*_args, **_kwargs):
        yield type(
            "ProfileClient",
            (),
            {
                "profile_summary": {
                    "provider_id": "deepseek",
                    "model": "deepseek-test",
                    "label": "DeepSeek",
                }
            },
        )()

    monkeypatch.setattr(
        "modules.project.facade.open_project_llm_client",
        open_profile_client,
    )
    output_dir = tmp_path / "results"

    await _run_workflow_evaluation(
        dataset=dataset,
        suite="rag",
        novel_id="novel-cli-1",
        dataset_id="pilot-v1",
        dataset_version="1.0.0",
        output_dir=output_dir,
        isolated_db=False,
        allow_unfrozen=True,
    )

    assert captured["db"] is db
    assert captured["novel_id"] == "novel-cli-1"
    assert captured["case_ids"] == ["rag-cli-1"]
    assert db.committed is True
    assert manager.closed is True
    result = EvalResult.model_validate_json(
        (output_dir / "rag.result.json").read_text(encoding="utf-8")
    )
    assert result.dataset_id == "pilot-v1"
    assert result.dataset_version == "1.0.0"
    assert result.system_under_test is not None
    assert result.system_under_test.provider_id == "deepseek"
    assert result.system_under_test.model == "deepseek-test"
    assert len(result.system_under_test.profile_hash) == 64
    assert result.run_context["rag_preflight"]["ready"] is True
    assert result.errors == ["unfrozen_dataset_smoke_only"]


@pytest.mark.asyncio
async def test_workflow_eval_cli_fails_before_db_for_mutating_suite_without_isolation(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="require --isolated-db"):
        await _run_workflow_evaluation(
            dataset=tmp_path / "missing.jsonl",
            suite="outline",
            novel_id="novel-cli-1",
            dataset_id="pilot-v1",
            dataset_version="1.0.0",
            output_dir=tmp_path / "results",
            isolated_db=False,
        )


def test_pilot_baseline_readiness_enforces_counts_and_safety_human_review() -> None:
    cases = _pilot_ready_cases()

    ready = assess_baseline_readiness(
        cases,
        tier="pilot",
        suites=tuple(EvalSuite),
    )
    assert ready["ready"] is True
    assert ready["eligible_count"] == 200

    invalid_model_cases = [case.model_copy(deep=True) for case in cases]
    invalid_model_cases[0].generation_meta.model = "gpt-5.6-terra"
    invalid_model_cases[1].qc.judge_decisions[0]["model"] = "gpt-5.6-terra"
    invalid_models = assess_baseline_readiness(
        invalid_model_cases,
        tier="pilot",
        suites=tuple(EvalSuite),
    )
    assert invalid_models["ready"] is False
    assert (
        invalid_model_cases[0].case_id
        in invalid_models["invalid_generation_provenance_case_ids"]
    )
    assert (
        invalid_model_cases[1].case_id
        in invalid_models["invalid_judge_provenance_case_ids"]
    )

    scene_index = next(
        index for index, case in enumerate(cases) if case.suite == EvalSuite.scene
    )
    original_scene = cases[scene_index]
    source_ref = original_scene.source_refs[0]
    cases[scene_index] = original_scene.model_copy(
        update={
            "source_refs": [
                source_ref.model_copy(
                    update={
                        "start_offset": None,
                        "end_offset": None,
                        "range_hash": None,
                    }
                )
            ]
        }
    )
    invalid_scene = assess_baseline_readiness(
        cases,
        tier="pilot",
        suites=tuple(EvalSuite),
    )
    assert invalid_scene["ready"] is False
    assert invalid_scene["invalid_scene_coordinate_case_ids"] == [original_scene.case_id]
    cases[scene_index] = original_scene

    original_last = cases[-1]
    cases[-1] = original_last.model_copy(update={"split": DatasetSplit.dev})
    leaked = assess_baseline_readiness(
        cases,
        tier="pilot",
        suites=tuple(EvalSuite),
    )
    assert leaked["split_leakage_groups"] == ["group-1"]
    assert leaked["ready"] is False
    cases[-1] = original_last

    safety = cases[0].model_copy(
        update={
            "risk_level": RiskLevel.safety_critical,
            "human_review": HumanReview(),
            "qc": QCDecision(
                status="review",
                deterministic_errors=[SAFETY_REVIEW_ERROR],
                judge_decisions=[
                    {
                        "model": HIGH_QUALITY_LLM_MODEL,
                        "prompt_hash": _hash("judge-1"),
                        "decision": "accept",
                        "rubric_score": 5,
                    },
                    {
                        "model": HIGH_QUALITY_LLM_MODEL,
                        "prompt_hash": _hash("judge-2"),
                        "decision": "accept",
                        "rubric_score": 5,
                    },
                ],
            ),
        }
    )
    cases[0] = safety
    incomplete = assess_baseline_readiness(
        cases,
        tier="pilot",
        suites=tuple(EvalSuite),
    )
    assert incomplete["ready"] is False
    assert incomplete["safety_without_human_acceptance"] == [safety.case_id]

    cases[0] = safety.model_copy(
        update={
            "human_review": HumanReview(
                status="accepted",
                reviewer_version="reviewer-a",
                score=5,
                independent_reviews=[
                    HumanReviewDecision(
                        status="accepted",
                        reviewer_version="reviewer-a",
                    )
                ],
            )
        }
    )
    reviewed = assess_baseline_readiness(
        cases,
        tier="pilot",
        suites=tuple(EvalSuite),
    )
    assert reviewed["ready"] is True


def test_freeze_writes_accepted_dataset_and_auditable_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cases = _pilot_ready_cases()
    scene_index = next(
        index for index, case in enumerate(cases) if case.suite == EvalSuite.scene
    )
    scene_reference = dict(cases[scene_index].reference)
    scene_reference["canonical_range_meta"] = {
        "model": HIGH_QUALITY_LLM_MODEL,
        "prompt_hash": _hash("range-locator"),
    }
    cases[scene_index] = cases[scene_index].model_copy(
        update={"reference": scene_reference}
    )
    rejected = _case(
        EvalSuite.rag,
        "rag-rejected-9999",
        {"answer": "bad fixture"},
    ).model_copy(update={"qc": QCDecision(status="rejected")})
    input_cases = [*cases, rejected]
    dataset = tmp_path / "reviewed.jsonl"
    dataset.write_text(
        "\n".join(case.model_dump_json() for case in input_cases) + "\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("evals.cli.load_corpus_snapshot", lambda _variant: _corpus())
    monkeypatch.setattr("evals.cli.source_path_for_variant", lambda _variant: source)
    monkeypatch.setattr(
        "evals.cli.run_deterministic_qc",
        lambda *_args, **_kwargs: {"errors": {}},
    )
    output = tmp_path / "pilot-v1.jsonl"
    manifest_output = tmp_path / "pilot-v1.manifest.json"
    readiness_output = tmp_path / "pilot-v1.readiness.json"

    _freeze_dataset(
        dataset=dataset,
        variant="pilot",
        tier="pilot",
        dataset_id="semantic-pilot-v1",
        dataset_version="1.0.0",
        output=output,
        manifest_output=manifest_output,
        readiness_output=readiness_output,
    )

    frozen = [
        DatasetCase.model_validate_json(line)
        for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert len(frozen) == 200
    assert rejected.case_id not in {case.case_id for case in frozen}
    manifest = DatasetManifest.model_validate_json(
        manifest_output.read_text(encoding="utf-8")
    )
    assert manifest.case_count == 200
    assert manifest.selection_meta["input_case_count"] == 201
    assert manifest.selection_meta["excluded_case_count"] == 1
    assert len(manifest.selection_meta["source_dataset_hash"]) == 64
    assert manifest.generator_model == HIGH_QUALITY_LLM_MODEL
    assert manifest.judge_model == HIGH_QUALITY_LLM_MODEL
    assert manifest.generation_runs
    assert manifest.generation_runs[0]["executor_hash"] == _hash("executor")
    assert manifest.judge_runs
    assert manifest.judge_runs[0]["model"] == HIGH_QUALITY_LLM_MODEL
    assert manifest.judge_runs[0]["executor_hash"] != "unavailable"
    assert manifest.judge_runs[0]["provenance_status"] == "partial_reconstructed"
    assert manifest.judge_runs[0]["duration_status"] == "unknown_historical"
    assert manifest.range_locator_runs
    assert manifest.range_locator_runs[0]["model"] == HIGH_QUALITY_LLM_MODEL
    assert manifest.range_locator_runs[0]["provenance_status"] == "partial_reconstructed"
    readiness = json.loads(readiness_output.read_text(encoding="utf-8"))
    assert readiness["ready"] is True
    assert readiness["excluded_case_ids"] == [rejected.case_id]
