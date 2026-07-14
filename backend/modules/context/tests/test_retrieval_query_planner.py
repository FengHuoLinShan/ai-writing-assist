from __future__ import annotations

import uuid
from time import perf_counter

import pytest

from modules.context.contracts import CompileOptions
from modules.context.services.retrieval_query_planner import RetrievalQueryPlanner


@pytest.mark.parametrize(
    "purpose",
    [
        "writing_generation",
        "conflict_review",
        "outline_generation",
        "world_fusion",
        "world_object_generation",
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


def test_world_object_generation_uses_author_intent_as_retrieval_query() -> None:
    options = CompileOptions(
        novel_id=str(uuid.uuid4()),
        task="设计一枚与主角旧友有关的黑曜钥匙",
        scope="generation_center",
        retrieval_purpose="world_object_generation",
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
