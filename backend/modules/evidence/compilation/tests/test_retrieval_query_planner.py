from __future__ import annotations

import uuid
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.services.context_compiler import SCOPE_LOADERS
from modules.evidence.compilation.services.retrieval_query_planner import (
    LLMQueryPlannerOutput,
    LLMQueryVariant,
    QueryPlannerIntent,
    QueryPlannerRole,
    RetrievalQueryPlanner,
    expand_query_plan,
    query_complexity_score,
)


@pytest.mark.parametrize(
    "purpose",
    [
        "writing_generation",
        "conflict_review",
        "outline_generation",
        "world_fusion",
        "world_generation",
        "map_atlas",
        "import_scene_activation",
        "reader_context",
        "character_context",
        "manual_search",
        "generic_context",
    ],
)
def test_all_supported_purposes_produce_bounded_deterministic_plans(
    purpose: str,
) -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="核对当前正文证据",
        scope="chapter",
        chapter_index=3,
        scene_id=str(uuid.uuid4()),
        entity_ids=[str(uuid.uuid4())],
        retrieval_purpose=purpose,
    )
    planner = RetrievalQueryPlanner()

    first = planner.plan(options)
    second = planner.plan(options)

    assert first == second
    assert first.purpose == purpose
    assert len(first.clauses) <= 3
    assert sum(clause.top_k for clause in first.clauses) <= 16


def test_planner_is_deterministic_and_bounded() -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="请根据以下资料生成 当前 Scene 中主角与密室的冲突",
        scope="chapter",
        chapter_index=3,
        visible_until_chapter=4,
        scene_id=str(uuid.uuid4()),
        entity_ids=[str(uuid.uuid4())],
        character_ids=[str(uuid.uuid4())],
        thread_ids=[str(uuid.uuid4())],
        retrieval_purpose="writing_generation",
        top_k=8,
    )
    planner = RetrievalQueryPlanner()

    first = planner.plan(options)
    second = planner.plan(options)

    assert first == second
    assert first.plan_hash == second.plan_hash
    assert first.version == "context-query-v1"
    assert first.purpose == "writing_generation"
    assert 1 <= len(first.clauses) <= 3
    assert sum(clause.top_k for clause in first.clauses) <= 16
    assert first.visible_until_chapter == 4
    assert {clause.reason_code for clause in first.clauses} == {
        "current_scene",
        "structured_relation_focus",
    }
    assert all(clause.chapter_index == 3 for clause in first.clauses)


def test_scene_scope_is_a_real_scene_anchored_compile() -> None:
    assert SCOPE_LOADERS["scene"] == SCOPE_LOADERS["chapter"]
    assert "scene" in SCOPE_LOADERS["scene"]

    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="生成本场人物反应",
        scope="scene",
        scene_id=str(uuid.uuid4()),
        character_ids=[str(uuid.uuid4())],
        reveal_mode="character",
        viewpoint_character_id=str(uuid.uuid4()),
        visible_until_scene_id=str(uuid.uuid4()),
        retrieval_purpose="story_character_reaction",
    )
    plan = RetrievalQueryPlanner().plan(options)
    assert plan.purpose == "story_character_reaction"
    assert plan.visible_until_scene_id == options.visible_until_scene_id


def test_author_safe_scene_cannot_widen_its_visibility_cursor() -> None:
    scene_id = str(uuid.uuid4())
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="生成当前 Scene",
        scope="chapter",
        scene_id=scene_id,
        reveal_mode="author_safe",
        visible_until_scene_id=str(uuid.uuid4()),
    )

    assert options.visible_until_scene_id == scene_id
    assert RetrievalQueryPlanner().plan(options).visible_until_scene_id == scene_id

    legacy = CompileOptions(
        novel_id=options.novel_id,
        task=options.task,
        scope=options.scope,
        scene_id=scene_id,
        reveal_mode="author_safe",
        visible_until_scene_id=None,
    )
    author_full = CompileOptions(
        novel_id=options.novel_id,
        task=options.task,
        scope=options.scope,
        scene_id=scene_id,
        reveal_mode="author_full",
    )

    assert legacy.visible_until_scene_id == scene_id
    assert author_full.visible_until_scene_id is None


def test_character_plan_never_adds_chapter_wide_task_fallback() -> None:
    scene_id = str(uuid.uuid4())
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="续写这一章并揭示未来真相",
        scope="chapter",
        chapter_index=5,
        scene_id=scene_id,
        reveal_mode="character",
        viewpoint_character_id=str(uuid.uuid4()),
        retrieval_purpose="character_context",
    )

    plan = RetrievalQueryPlanner().plan(options)

    assert len(plan.clauses) == 1
    clause = plan.clauses[0]
    assert clause.scene_id == scene_id
    assert clause.strict_scene_filter is True
    assert clause.reason_code == "current_scene"


def test_world_fusion_without_structured_relations_does_not_widen_to_task() -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="分析这些世界设定",
        scope="world",
        retrieval_purpose="world_fusion",
    )

    plan = RetrievalQueryPlanner().plan(options)

    assert plan.clauses == []


def test_world_generation_uses_author_intent_as_retrieval_query() -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="设计一枚与主角旧友有关的黑曜钥匙",
        scope="generation_center",
        retrieval_purpose="world_generation",
    )

    plan = RetrievalQueryPlanner().plan(options)

    assert len(plan.clauses) == 1
    assert plan.clauses[0].reason_code == "task_intent"
    assert "黑曜钥匙" in plan.clauses[0].query_text


def test_empty_generic_input_produces_no_clause() -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="   ",
        scope="full",
    )

    plan = RetrievalQueryPlanner().plan(options)

    assert plan.clauses == []


def test_single_clause_uses_final_top_k_without_double_candidate_pool() -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="查找精确证据",
        scope="full",
        retrieval_purpose="manual_search",
        top_k=8,
    )

    plan = RetrievalQueryPlanner().plan(options)

    assert len(plan.clauses) == 1
    assert plan.clauses[0].top_k == 8


def test_planner_normalizes_and_bounds_task_text() -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="请你分析 " + "很长的任务描述" * 80,
        scope="full",
        retrieval_purpose="manual_search",
    )

    plan = RetrievalQueryPlanner().plan(options)

    assert len(plan.clauses) == 1
    assert len(plan.clauses[0].query_text) <= 160
    assert not plan.clauses[0].query_text.startswith("请你分析")


def test_planner_local_p95_is_below_two_milliseconds() -> None:
    planner = RetrievalQueryPlanner()
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="续写当前 Scene，保持人物与剧情线一致",
        scope="chapter",
        chapter_index=8,
        scene_id=str(uuid.uuid4()),
        entity_ids=[str(uuid.uuid4())],
        thread_ids=[str(uuid.uuid4())],
        retrieval_purpose="writing_generation",
    )
    durations = []
    for _ in range(500):
        started = perf_counter()
        planner.plan(options)
        durations.append((perf_counter() - started) * 1000)

    durations.sort()
    assert durations[int(len(durations) * 0.95) - 1] < 2.0


@pytest.mark.asyncio
async def test_simple_query_does_not_call_llm_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="查找克莱恩",
        scope="full",
        retrieval_purpose="manual_search",
    )
    plan = RetrievalQueryPlanner().plan(options)
    generate = AsyncMock()
    monkeypatch.setattr(
        "modules.evidence.compilation.services.retrieval_query_planner.run_managed_structured",
        generate,
    )

    outcome = await expand_query_plan(
        None,  # type: ignore[arg-type]
        options,
        plan,
        enabled=True,
        llm_client=SimpleNamespace(  # type: ignore[arg-type]
            model_name="deepseek-v4-flash",
            provider="deepseek",
        ),
    )

    assert query_complexity_score(options) == 0
    assert outcome.plan == plan
    assert outcome.invoked is False
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_complex_query_adds_grounded_soft_clause_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    character_ids = [str(uuid.uuid4())]
    thread_ids = [str(uuid.uuid4())]
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="克莱恩在决裂之前为什么改变立场？",
        scope="full",
        chapter_index=7,
        visible_until_chapter=6,
        entity_ids=entity_ids,
        character_ids=character_ids,
        thread_ids=thread_ids,
        retrieval_purpose="conflict_review",
    )
    plan = RetrievalQueryPlanner().plan(options)
    generate = AsyncMock(
        return_value=LLMQueryPlannerOutput(
            intent=QueryPlannerIntent.causal,
            queries=[
                LLMQueryVariant(
                    role=QueryPlannerRole.support,
                    query_text="克莱恩决裂之前改变立场的原因",
                    grounding_spans=["克莱恩", "决裂之前"],
                ),
                LLMQueryVariant(
                    role=QueryPlannerRole.counter,
                    query_text="克莱恩决裂之前没有改变立场的证据",
                    grounding_spans=["克莱恩", "改变立场"],
                ),
            ],
        )
    )
    monkeypatch.setattr(
        "modules.evidence.compilation.services.retrieval_query_planner.run_managed_structured",
        generate,
    )

    outcome = await expand_query_plan(
        None,  # type: ignore[arg-type]
        options,
        plan,
        enabled=True,
        llm_client=SimpleNamespace(  # type: ignore[arg-type]
            model_name="deepseek-v4-flash",
            provider="deepseek",
        ),
    )

    assert outcome.invoked is True
    assert outcome.expanded is True
    assert outcome.degraded is False
    assert len(outcome.plan.clauses) == 3
    assert outcome.plan.clauses[0].query_text == plan.clauses[0].query_text
    assert {clause.reason_code for clause in outcome.plan.clauses[1:]} == {
        "llm_support_query",
        "llm_counter_query",
    }
    base = outcome.plan.clauses[0]
    for clause in outcome.plan.clauses[1:]:
        assert clause.entity_ids == base.entity_ids == entity_ids
        assert clause.character_ids == base.character_ids == character_ids
        assert clause.thread_ids == base.thread_ids == thread_ids
        assert clause.chapter_index == base.chapter_index == 7
        assert clause.scene_id == base.scene_id
        assert clause.strict_scene_filter == base.strict_scene_filter
    assert outcome.plan.visible_until_chapter == plan.visible_until_chapter
    generate.assert_awaited_once()
    request = generate.await_args.args[1]
    assert request.max_tokens == 8_192
    assert request.extra == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }
    assert generate.await_args.kwargs["max_fix_attempts"] == 0
    assert generate.await_args.kwargs["transport_retries"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError(), ValueError("schema invalid")])
async def test_llm_planner_timeout_or_schema_failure_falls_back_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="克莱恩之后为什么与之前的立场冲突？",
        scope="full",
        retrieval_purpose="conflict_review",
    )
    plan = RetrievalQueryPlanner().plan(options)
    generate = AsyncMock(side_effect=failure)
    monkeypatch.setattr(
        "modules.evidence.compilation.services.retrieval_query_planner.run_managed_structured",
        generate,
    )

    outcome = await expand_query_plan(
        None,  # type: ignore[arg-type]
        options,
        plan,
        enabled=True,
        llm_client=SimpleNamespace(model_name="test-model"),  # type: ignore[arg-type]
    )

    assert outcome.plan == plan
    assert outcome.invoked is True
    assert outcome.degraded is True
    assert outcome.warning_code == "llm_query_planner_failed"
    generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_planner_cannot_expand_an_empty_deterministic_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="之前与之后为什么发生冲突？",
        scope="world",
        retrieval_purpose="world_fusion",
    )
    plan = RetrievalQueryPlanner().plan(options)
    generate = AsyncMock()
    monkeypatch.setattr(
        "modules.evidence.compilation.services.retrieval_query_planner.run_managed_structured",
        generate,
    )

    outcome = await expand_query_plan(
        None,  # type: ignore[arg-type]
        options,
        plan,
        enabled=True,
        llm_client=SimpleNamespace(model_name="test-model"),  # type: ignore[arg-type]
    )

    assert plan.clauses == []
    assert outcome.plan == plan
    assert outcome.invoked is False
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_planner_rejects_new_numeric_fact_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="克莱恩之后为什么改变立场？",
        scope="full",
        retrieval_purpose="conflict_review",
    )
    plan = RetrievalQueryPlanner().plan(options)
    monkeypatch.setattr(
        "modules.evidence.compilation.services.retrieval_query_planner.run_managed_structured",
        AsyncMock(
            return_value=LLMQueryPlannerOutput(
                intent=QueryPlannerIntent.causal,
                queries=[
                    LLMQueryVariant(
                        role=QueryPlannerRole.support,
                        query_text="第99章克莱恩之后改变立场的原因",
                        grounding_spans=["克莱恩", "之后"],
                    )
                ],
            )
        ),
    )

    outcome = await expand_query_plan(
        None,  # type: ignore[arg-type]
        options,
        plan,
        enabled=True,
        llm_client=SimpleNamespace(model_name="test-model"),  # type: ignore[arg-type]
    )

    assert outcome.plan == plan
    assert outcome.invoked is True
    assert outcome.degraded is True
    assert outcome.warning_code == "llm_query_planner_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("purpose", "reveal_mode"),
    [
        ("reader_context", "reader"),
        ("character_context", "character"),
        ("import_scene_activation", "author_safe"),
        ("map_atlas", "author_full"),
    ],
)
async def test_llm_planner_never_expands_disabled_safety_paths(
    purpose: str,
    reveal_mode: str,
) -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="之前与之后为什么发生矛盾和变化？",
        scope="full",
        retrieval_purpose=purpose,
        reveal_mode=reveal_mode,
        scene_id=str(uuid.uuid4()) if reveal_mode == "character" else None,
        viewpoint_character_id=(
            str(uuid.uuid4()) if reveal_mode == "character" else None
        ),
    )
    plan = RetrievalQueryPlanner().plan(options)

    outcome = await expand_query_plan(
        None,  # type: ignore[arg-type]
        options,
        plan,
        enabled=True,
        llm_client=SimpleNamespace(model_name="test-model"),  # type: ignore[arg-type]
    )

    assert outcome.invoked is False
    assert outcome.plan == plan
