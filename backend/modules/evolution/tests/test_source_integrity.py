"""真实 handler/来源/冻结恢复链；固定 provider 输出仅验证工程契约。"""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from modules.evolution.commit import CommitConflictError
from modules.evolution.pipeline import (
    SceneSourceBinding,
    SceneSourceRange,
    load_current_source,
)
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.story.continuity.models import MemoryEvent
from modules.story.outline_state.models import Scene
from modules.writing.facade import create_draft_only, get_latest_draft_for_chapter
from tests.support.evolution_review import frozen_state_review


class Sampler:
    verify_state_events = staticmethod(frozen_state_review)

    def __init__(self, observation):
        self.observation = observation
        self.calls = 0

    async def sample(self, *, scene_text, input_manifest):
        self.calls += 1
        return {
            "observations": [self.observation],
            "scene_events": [
                {
                    "dimension": "timeline",
                    "event_type": "time_advanced",
                    "snapshot_after": {"text_state": "晨起"},
                    "source_observation_indices": [0],
                }
            ],
            "paid_call_receipt": {"provider": "fixture", "usage": {"total_tokens": 7}},
        }


async def seed(db, nid, chapters):
    scene = Scene(
        novel_id=uuid.UUID(nid),
        scene_index=0,
        title="跨章场景",
        chapter_ids=list(chapters),
        scene_chunks=[],
        status="draft",
    )
    db.add(scene)
    await db.flush()
    scene_id = str(scene.id)
    for chapter, text in chapters.items():
        await create_draft_only(db, nid, chapter, f"第{chapter}章", text)
    await db.commit()
    return scene_id


def request(nid, scene_id, text, **kwargs):
    return SimpleNamespace(
        meta={
            "novel_id": nid,
            "scene_id": scene_id,
            "scene_index": 0,
            "scene_text": text,
            "chapter_index": 1,
            "run_key": "source-integrity",
            "budget_total": 4,
            "sampler_provider": "source-integrity",
            **kwargs,
        }
    )


async def test_cross_chapter_quotes_persist_exact_sources_and_replay(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    first, second = "前言。🌙夜色渐淡，", "晨光照进城门。尾声。"
    scene_id = await seed(db, nid, {1: first, 2: second})
    text = first[3:] + second[:8]
    sampler = Sampler(
        {"predicate": "夜去晨来", "modality": "event_observed", "quote": "渐淡，晨光"}
    )
    register_scene_sampler("source-integrity", lambda db, novel_id: sampler)
    task = request(
        nid,
        scene_id,
        text,
        start_offset=3,
        state_review_version=1,
        additional_sources=[{"chapter_index": 2, "end_offset": 8}],
    )
    result = await handle_evolution_scene_step(db, task)
    store = PostgresAttemptStore(db, nid)
    frozen = await store.load_frozen("source-integrity", result["attempt_id"])
    observation = frozen.payload["compiled_observations"][0]
    evidence = observation["evidence_quotes"]
    assert [item["quote"] for item in evidence] == ["渐淡，", "晨光"]
    assert [
        (
            item["source_ref"]["chapter_identity"],
            item["source_ref"]["start_offset"],
            item["source_ref"]["end_offset"],
        )
        for item in evidence
    ] == [("chapter:1", 6, 9), ("chapter:2", 0, 2)]
    for item in evidence:
        ref = item["source_ref"]
        chapter = int(ref["chapter_identity"].split(":")[1])
        draft = await get_latest_draft_for_chapter(db, nid, chapter)
        assert str(draft.id) == ref["draft_id"]
        assert draft.content[ref["start_offset"] : ref["end_offset"]] == item["quote"]
    events = (
        (
            await db.execute(
                select(MemoryEvent).where(MemoryEvent.novel_id == uuid.UUID(nid))
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].chapter_index == 2  # 跨章 Scene 原子提交在末章，不能泄漏到首章
    assert events[0].snapshot_after["meta"]["source_observation_ids"] == [
        observation["observation_id"]
    ]
    assert events[0].snapshot_after["meta"]["authority_basis"] == "derived_observation"
    replay = await handle_evolution_scene_step(db, task)
    assert replay["attempt_id"] == result["attempt_id"] and replay["recovered"]
    assert sampler.calls == 1
    assert (await store.load_run("source-integrity")).budget_remaining == 2


@pytest.mark.parametrize(
    "observation",
    [
        {"quote": "原文不存在"},
        {"quote": "晨光", "start_offset": 0, "end_offset": 1000},
        {"quote": "晨光", "start_offset": -1, "end_offset": 1},
        {"quote": "晨光", "start_offset": 0},
        {"quote": "晨光", "start_offset": True, "end_offset": 3},
        {"quote": "晨光"},  # 两次出现，禁止猜测引用位置
    ],
)
async def test_bad_quote_never_commits_or_repays_on_recovery(
    db_session, evolution_project_id, observation
):
    db, nid = db_session, evolution_project_id
    text = "晨光照进城门。晨光照进客栈。"
    scene_id = await seed(db, nid, {1: text})
    sampler = Sampler({"predicate": "晨起", "modality": "event_observed", **observation})
    register_scene_sampler("source-integrity", lambda db, novel_id: sampler)
    task = request(nid, scene_id, text)
    for _ in range(2):
        with pytest.raises(CommitConflictError) as caught:
            await handle_evolution_scene_step(db, task)
        assert caught.value.code == "invalid_observation_source"
    store = PostgresAttemptStore(db, nid)
    frozen = await store.load_pending_frozen("source-integrity", 0)
    assert frozen.payload["stage"] == "sampled"
    assert frozen.payload["paid_call_receipt"]["usage"]["total_tokens"] == 7
    assert await store.load_head_receipt("source-integrity") is None
    assert (await store.load_run("source-integrity")).budget_remaining == 3
    assert sampler.calls == 1
    assert (
        not (
            await db.execute(
                select(MemoryEvent).where(MemoryEvent.novel_id == uuid.UUID(nid))
            )
        )
        .scalars()
        .all()
    )


async def test_pending_attempt_requires_identical_request_then_recovers(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    text = "晨光。晨光。"
    scene_id = await seed(db, nid, {1: text})
    sampler = Sampler(
        {"predicate": "晨起", "modality": "event_observed", "quote": "晨光。"}
    )
    register_scene_sampler("source-integrity", lambda db, novel_id: sampler)
    original = request(nid, scene_id, "晨光。", end_offset=3)
    with patch.object(
        PostgresAttemptStore,
        "save_receipt",
        autospec=True,
        side_effect=RuntimeError("lost commit"),
    ):
        with pytest.raises(RuntimeError, match="lost commit"):
            await handle_evolution_scene_step(db, original)
    await db.rollback()
    # 相同文字来自另一位置，也不准把第一处的旧结果应用到第二处。
    with pytest.raises(CommitConflictError) as caught:
        await handle_evolution_scene_step(
            db, request(nid, scene_id, "晨光。", start_offset=3, end_offset=6)
        )
    assert caught.value.code == "request_changed"
    assert sampler.calls == 1
    replay = await handle_evolution_scene_step(db, original)
    assert replay["recovered"] and sampler.calls == 1
    assert (
        await PostgresAttemptStore(db, nid).load_run("source-integrity")
    ).budget_remaining == 3


async def test_second_chapter_revision_blocks_frozen_recovery(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    scene_id = await seed(db, nid, {1: "夜色。", 2: "晨光。"})
    sampler = Sampler(
        {"predicate": "晨起", "modality": "event_observed", "quote": "晨光。"}
    )
    register_scene_sampler("source-integrity", lambda db, novel_id: sampler)
    task = request(
        nid, scene_id, "夜色。晨光。", additional_sources=[{"chapter_index": 2}]
    )
    with patch.object(
        PostgresAttemptStore,
        "save_receipt",
        autospec=True,
        side_effect=RuntimeError("lost commit"),
    ):
        with pytest.raises(RuntimeError):
            await handle_evolution_scene_step(db, task)
    await db.rollback()
    store = PostgresAttemptStore(db, nid)
    frozen = await store.load_pending_frozen("source-integrity", 0)
    source = SceneSourceBinding.model_validate(frozen.payload["source_binding"])
    await create_draft_only(db, nid, 2, "第二章修订", "暮光。")
    await db.commit()
    assert await load_current_source(db, nid, source) is None
    from modules.evolution.pipeline import recover_scene_step

    async def forbidden_applier(db, frozen):
        pytest.fail("stale source reached domain writes")

    with pytest.raises(CommitConflictError) as caught:
        await recover_scene_step(
            db,
            store,
            run_key="source-integrity",
            scene_index=0,
            applier=forbidden_applier,
        )
    assert caught.value.code == "source_changed"
    assert (
        sampler.calls == 1 and await store.load_head_receipt("source-integrity") is None
    )


async def test_shadow_checks_scene_identity_before_sampling(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    scene_id = await seed(db, nid, {1: "晨光。"})
    with pytest.raises(ValueError, match="scene_index does not match"):
        await handle_evolution_scene_step(
            db, request(nid, scene_id, "晨光。", scene_index=1, execution_mode="shadow")
        )
    assert await PostgresAttemptStore(db, nid).load_run("source-integrity") is None


@pytest.mark.parametrize("existing, requested", [("live", "shadow"), ("shadow", "live")])
async def test_run_mode_cannot_change_on_retry(
    db_session, evolution_project_id, existing, requested
):
    db, nid = db_session, evolution_project_id
    scene_id = await seed(db, nid, {1: "晨光。"})
    store = PostgresAttemptStore(db, nid)
    await store.register_run(
        "source-integrity", mode="append", budget_total=4, execution_mode=existing
    )
    await db.commit()
    with pytest.raises(CommitConflictError) as caught:
        await handle_evolution_scene_step(
            db, request(nid, scene_id, "晨光。", execution_mode=requested)
        )
    assert caught.value.code == "run_mode_conflict"
    assert (await store.load_run("source-integrity")).budget_remaining == 4
    assert await store.load_head_receipt("source-integrity") is None


def test_multi_source_order_and_hash_binding():
    from pydantic import ValidationError

    from modules.evolution.pipeline import compute_scene_manifest_hash

    first = {
        "draft_id": "first",
        "chapter_index": 1,
        "content_hash": "a" * 64,
        "end_offset": 3,
    }
    second = SceneSourceRange(
        draft_id="second", chapter_index=2, content_hash="b" * 64, end_offset=3
    )
    binding = SceneSourceBinding(**first, additional_sources=[second])
    changed = binding.model_copy(
        update={
            "additional_sources": [second.model_copy(update={"content_hash": "c" * 64})]
        }
    )
    assert compute_scene_manifest_hash(
        "run", 0, "晨光。夜色。", binding
    ) != compute_scene_manifest_hash("run", 0, "晨光。夜色。", changed)
    with pytest.raises(ValidationError, match="chapter order"):
        SceneSourceBinding(
            **second.model_dump(), additional_sources=[SceneSourceRange(**first)]
        )
    with pytest.raises(ValidationError, match="overlap"):
        SceneSourceBinding(**first, additional_sources=[SceneSourceRange(**first)])


async def test_repeated_quote_with_explicit_offsets_keeps_selected_occurrence(
    db_session,
    evolution_project_id,
):
    db, nid = db_session, evolution_project_id
    text = "晨光。晨光。"
    scene_id = await seed(db, nid, {1: text})
    sampler = Sampler(
        {
            "predicate": "晨起",
            "modality": "event_observed",
            "quote": "晨光。",
            "start_offset": 3,
            "end_offset": 6,
        }
    )
    register_scene_sampler("source-integrity", lambda db, novel_id: sampler)
    result = await handle_evolution_scene_step(db, request(nid, scene_id, text))
    frozen = await PostgresAttemptStore(db, nid).load_frozen(
        "source-integrity", result["attempt_id"]
    )
    ref = frozen.payload["compiled_observations"][0]["source_ref"]
    assert (ref["start_offset"], ref["end_offset"]) == (3, 6)
