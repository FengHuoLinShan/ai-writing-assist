"""Post-commit optional I/O uses durable journals, not detached tasks."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.base import Base
from modules.evolution.commit import ApplierResult
from modules.evolution.contracts import CommittedPrefix
from modules.evolution.facade import switch_project_engine
from modules.evolution.pipeline import SceneSourceBinding, _run_scene_call, run_scene_step
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_source_integrity import request
from modules.evolution.tests.test_source_integrity import seed as seed_unmapped
from modules.project.models import Project
from modules.story.outline_state.models import SceneSpan
from modules.world.models import WorldEntity
from modules.writing.facade import get_latest_draft_for_chapter


async def seed(db, nid, chapters):
    scene_id = await seed_unmapped(db, nid, chapters)
    for chapter, text in chapters.items():
        draft = await get_latest_draft_for_chapter(db, nid, chapter)
        db.add(
            SceneSpan(
                novel_id=UUID(nid),
                scene_id=UUID(scene_id),
                chapter_index=chapter,
                content_mode="working",
                source_draft_id=UUID(str(draft.id)),
                source_content_hash=draft.content_hash,
                start_offset=0,
                end_offset=len(text),
                part_no=0,
                mapping_status="exact",
                status="draft",
            )
        )
    await db.commit()
    return scene_id


class Sample:
    calls = 0

    async def sample(self, *, scene_text, input_manifest):
        self.calls += 1
        return {
            "observations": [
                {
                    "quote": scene_text,
                    "predicate": "城门开启",
                    "modality": "event_observed",
                }
            ],
            "scene_events": [],
        }


async def plan_run(db, nid, *, optional_version=1, remaining=20):
    store = PostgresAttemptStore(db, nid)
    run = await store.register_run(
        "source-integrity", mode="append", budget_total=remaining
    )
    run.reading_plan_json = {
        "spatial_version": 1,
        "steps": [],
        "optional_stage_version": optional_version,
        "optional_step_quotas": {
            key: {"limit": 8, "used": 0, "remaining": 8} for key in ("details", "spatial")
        },
        "mandatory_scene_calls": [{"scene_index": 1, "calls": {"scene_sample": 1}}],
    }
    await db.commit()
    return store


def optional_call(key, provider):
    async def finish(db, store, frozen, source, caller):
        return await _run_scene_call(
            db,
            store,
            frozen,
            source,
            journal_key=key,
            inputs={"method": key},
            call_inputs={},
            call=provider,
        )

    return finish


@pytest.mark.parametrize("optional_version", [0, 1])
async def test_hanging_optional_has_committed_receipt_and_world_in_another_session(
    tmp_path, monkeypatch, optional_version
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'optional.sqlite'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    entered, release = asyncio.Event(), asyncio.Event()
    active = None
    try:
        async with sessions() as db:
            project = Project(title="合成可选阶段测试", settings={})
            db.add(project)
            await db.flush()
            nid = str(project.id)
            await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
            await db.commit()
            scene_id = await seed(db, nid, {1: "城门开启。"})
            store = await plan_run(db, nid, optional_version=optional_version)
            draft = await get_latest_draft_for_chapter(db, nid, 1)
            source = SceneSourceBinding(
                draft_id=str(draft.id),
                content_hash=draft.content_hash,
                chapter_index=1,
                start_offset=0,
                end_offset=5,
            )

            async def provider(**kwargs):
                entered.set()
                await release.wait()
                return {"result": {}, "paid_call_receipt": {"provider": "fixture"}}

            monkeypatch.setattr(
                "modules.evolution.spatial.finish_scene_spatial",
                optional_call("scene_spatial_discovery", provider),
            )
            entity_id = uuid4()

            async def applier(session, frozen):
                session.add(
                    WorldEntity(
                        id=entity_id,
                        novel_id=UUID(nid),
                        entity_type="location",
                        name="城门",
                        status="candidate",
                    )
                )
                return ApplierResult(
                    committed_prefix=CommittedPrefix(
                        through_scene_index=0, through_source_revision=1
                    ),
                    world_result_refs=[{"entity_id": str(entity_id)}],
                )

            active = asyncio.create_task(
                run_scene_step(
                    db,
                    store,
                    run_key="source-integrity",
                    scene_index=0,
                    scene_text="城门开启。",
                    source=source,
                    scene_id=scene_id,
                    sampler=Sample(),
                    applier=applier,
                    state_review_version=0,
                    spatial_version=1,
                    source_content_mode="working",
                )
            )
            await asyncio.wait_for(entered.wait(), 3)
            assert not active.done()
            async with sessions() as observer:
                other = PostgresAttemptStore(observer, nid)
                receipt = await other.load_committed_scene_receipt("source-integrity", 0)
                if optional_version == 1:
                    assert receipt is not None
                    before = receipt.model_dump(mode="json")
                    assert receipt.world_result_refs == [{"entity_id": str(entity_id)}]
                    assert await observer.get(WorldEntity, entity_id) is not None
                    frozen = await other.load_frozen(receipt.run_id, receipt.attempt_id)
                    assert (
                        frozen.payload["optional_scene_stage"]["steps"]["spatial"][
                            "status"
                        ]
                        == "running"
                    )
                    assert (
                        frozen.payload["scene_spatial_discovery"]["stage"] == "sampling"
                    )
                else:
                    assert receipt is None
                    assert await observer.get(WorldEntity, entity_id) is None
            release.set()
            await active
            receipt = await store.load_committed_scene_receipt("source-integrity", 0)
            final = await store.load_frozen(receipt.run_id, receipt.attempt_id)
            if optional_version == 1:
                assert receipt.model_dump(mode="json") == before
                assert (
                    final.payload["optional_scene_stage"]["steps"]["spatial"]["status"]
                    == "complete"
                )
            else:
                assert "optional_scene_stage" not in final.payload
            assert (await store.load_run(receipt.run_id)).budget_remaining == 18
    finally:
        if active and not active.done():
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
        await engine.dispose()


@pytest.mark.parametrize("interruption", ["failure", "cancel", "quota"])
async def test_task_resume_isolates_optional_unknown_and_preserves_budget(
    db_session, evolution_project_id, monkeypatch, interruption
):
    db, nid = db_session, evolution_project_id
    scene_id = await seed(db, nid, {1: "城门开启。"})
    store = await plan_run(db, nid, remaining=2 if interruption == "quota" else 20)
    sampler = Sample()
    register_scene_sampler("source-integrity", lambda db, novel_id: sampler)
    calls = []

    async def provider(**kwargs):
        calls.append("details")
        if interruption == "cancel":
            raise asyncio.CancelledError
        raise RuntimeError("synthetic optional timeout")

    async def spatial_provider(**kwargs):
        calls.append("spatial")
        return {"result": {}}

    monkeypatch.setattr(
        "modules.evolution.discovery.finish_scene_discovery",
        optional_call("scene_discovery_0", provider),
    )
    monkeypatch.setattr(
        "modules.evolution.spatial.finish_scene_spatial",
        optional_call("scene_spatial_discovery", spatial_provider),
    )
    # Fixed boundary output tests journal isolation; typed materialization has its
    # existing domain tests. This is not evidence of live-model quality.
    monkeypatch.setattr("modules.evolution.discovery.apply_discovery", _no_materialize)
    task = request(
        nid,
        scene_id,
        "城门开启。",
        state_review_version=0,
        discovery_version=1,
        spatial_version=1,
        source_content_mode="working",
        budget_total=2 if interruption == "quota" else 20,
    )
    monkeypatch.setattr("modules.evolution.workflow.advance_reading", _no_advance)
    if interruption == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await handle_evolution_scene_step(db, task)
        await db.rollback()
        receipt = await store.load_committed_scene_receipt("source-integrity", 0)
        frozen = await store.load_frozen(receipt.run_id, receipt.attempt_id)
        assert (
            frozen.payload["optional_scene_stage"]["steps"]["details"]["status"]
            == "running"
        )
    else:
        await handle_evolution_scene_step(db, task)
        receipt = await store.load_committed_scene_receipt("source-integrity", 0)
    before = receipt.model_dump(mode="json")
    await handle_evolution_scene_step(db, task)
    frozen = await store.load_frozen(receipt.run_id, receipt.attempt_id)
    steps = frozen.payload["optional_scene_stage"]["steps"]
    assert sampler.calls == 1
    assert (await store.load_receipt(receipt.run_id, receipt.attempt_id)).model_dump(
        mode="json"
    ) == before
    run = await store.load_run("source-integrity")
    if interruption == "quota":
        assert calls == []
        assert run.budget_remaining == 1
        assert steps["details"]["status"] == "failed"
    else:
        assert calls == ["details", "spatial"]
        assert steps["details"]["status"] == "unknown"
        assert steps["spatial"]["status"] == "complete"
        assert run.budget_remaining == 17
    assert (
        frozen.payload["optional_scene_stage"]["receipt_attempt_id"] == receipt.attempt_id
    )


async def _no_materialize(*args):
    return []


async def _no_advance(*args):
    return {}


async def test_committed_optional_cancel_resumes_original_durable_reading_task(
    db_session, evolution_project_id, monkeypatch
):
    from infrastructure.tasks.models import AsyncTask
    from modules.evolution.workflow import reading_status, resume_reading

    db, nid = db_session, evolution_project_id
    scene_id = await seed(db, nid, {1: "城门开启。"})
    store = await plan_run(db, nid)
    sampler = Sample()
    register_scene_sampler("source-integrity", lambda db, novel_id: sampler)
    calls = []

    async def provider(**kwargs):
        calls.append("provider")
        raise asyncio.CancelledError

    monkeypatch.setattr(
        "modules.evolution.spatial.finish_scene_spatial",
        optional_call("scene_spatial_discovery", provider),
    )
    meta = request(
        nid,
        scene_id,
        "城门开启。",
        state_review_version=0,
        spatial_version=1,
        source_content_mode="working",
        budget_total=20,
    ).meta
    task = AsyncTask(
        id=uuid4(),
        novel_id=UUID(nid),
        task_type="evolution_scene_step_v2",
        recovery_policy="manual_resume",
        meta=meta,
        status="running",
    )
    db.add(task)
    run = await store.load_run("source-integrity")
    draft = await get_latest_draft_for_chapter(db, nid, 1)
    binding = SceneSourceBinding(
        draft_id=str(draft.id),
        content_hash=draft.content_hash,
        chapter_index=1,
        start_offset=0,
        end_offset=5,
    )
    run.reading_plan_json = {
        **run.reading_plan_json,
        "steps": [
            {
                "scene_id": scene_id,
                "scene_index": 0,
                "source_content_mode": "working",
                "source_binding": binding.model_dump(mode="json"),
            }
        ],
        "task_id": str(task.id),
    }
    await db.commit()
    with pytest.raises(asyncio.CancelledError):
        await handle_evolution_scene_step(db, task)
    await db.rollback()
    # Worker crash checkpoint boundary: the durable task is resumable, while the
    # provider journal remains sampling/unknown. No provider output is invented.
    task = await db.get(AsyncTask, task.id)
    task.meta = {**meta, "recovery_required": True}
    task.result = {"recovery_required": True}
    task.mark_failed("synthetic interruption")
    await db.commit()
    state = (await reading_status(db, nid, "source-integrity"))["run"]
    assert state["completed_scenes"] == 1 and state["status"] == "failed"
    assert state["can_resume"] is True
    resumed = (await resume_reading(db, nid, "source-integrity"))["run"]
    assert resumed["task_id"] == str(task.id) and resumed["status"] == "pending"
    await handle_evolution_scene_step(db, task)
    assert calls == ["provider"] and sampler.calls == 1
    task.status = "done"
    await db.commit()
    final = (await reading_status(db, nid, "source-integrity"))["run"]
    assert final["status"] == "completed"
    assert final["optional_step_coverage"]["spatial"]["counts"]["gap"] == 1


async def test_real_optional_protocol_uses_strict_earlier_scene_context(
    db_session, evolution_project_id, monkeypatch
):
    from modules.evolution.spatial import spatial_method_fingerprint
    from modules.story.outline_state.models import Scene

    db, nid = db_session, evolution_project_id
    text = "城门在东侧，渡口在西侧。"
    scene_id = await seed(db, nid, {1: text})
    store = await plan_run(db, nid)
    run = await store.load_run("source-integrity")
    run.reading_plan_json = {
        **run.reading_plan_json,
        "spatial_method_fingerprint": spatial_method_fingerprint(),
    }
    await db.commit()
    calls = []

    class TypedSample(Sample):
        async def discover_details(self, *, inputs):
            calls.append(("details", inputs))
            return {
                "result": {
                    "changes": [],
                    "coverage": "inspected",
                    "coverage_note": "合成资料已检查",
                }
            }

        async def review_discovery(self, *, inputs):
            return {"result": {"verdicts": []}}

        async def discover_spatial(self, *, inputs):
            calls.append(("spatial", inputs))
            return {
                "result": {
                    "clues": [
                        {
                            "kind": "bearing",
                            "subject_surface": "城门",
                            "target_surface": "渡口",
                            "relation": "east_of",
                            "modality": "event_observed",
                            "quote": inputs["scene_text"],
                        }
                    ],
                    "coverage_note": "合成资料已检查",
                }
            }

        async def review_spatial(self, *, inputs):
            return {
                "result": {
                    "reviews": [
                        {
                            "clue_index": 0,
                            "verdict": "supported",
                            "reason": "合成资料明确方位",
                        }
                    ],
                    "coverage_note": "合成资料已复核",
                }
            }

    sampler = TypedSample()
    register_scene_sampler("source-integrity", lambda db, novel_id: sampler)
    monkeypatch.setattr("modules.evolution.workflow.advance_reading", _no_advance)
    first = request(
        nid,
        scene_id,
        text,
        state_review_version=0,
        discovery_version=1,
        spatial_version=1,
        source_content_mode="working",
        budget_total=20,
    )
    result = await handle_evolution_scene_step(db, first)
    frozen = await store.load_frozen("source-integrity", result["attempt_id"])
    assert (
        frozen.payload["optional_scene_stage"]["steps"]["details"]["status"] == "complete"
    )
    assert frozen.payload["discovery_materialization"] == {"applied": [], "pending": []}
    assert (
        frozen.payload["discovery_preparation"]["coverage"]["total_prior_observations"]
        == 0
    )
    # Add the next authoritative Scene without changing the first source.
    from modules.writing.facade import create_draft_only

    await create_draft_only(db, nid, 2, "第二章", text)
    scene = Scene(
        novel_id=UUID(nid),
        scene_index=1,
        title="后场",
        chapter_ids=[2],
        scene_chunks=[],
        status="draft",
    )
    db.add(scene)
    await db.flush()
    second_id = str(scene.id)
    draft = await get_latest_draft_for_chapter(db, nid, 2)
    db.add(
        SceneSpan(
            novel_id=UUID(nid),
            scene_id=scene.id,
            chapter_index=2,
            content_mode="working",
            source_draft_id=UUID(str(draft.id)),
            source_content_hash=draft.content_hash,
            start_offset=0,
            end_offset=len(text),
            part_no=0,
            mapping_status="exact",
            status="draft",
        )
    )
    await db.commit()
    second = request(
        nid,
        second_id,
        text,
        scene_index=1,
        chapter_index=2,
        state_review_version=0,
        discovery_version=1,
        spatial_version=1,
        source_content_mode="working",
        budget_total=20,
    )
    result2 = await handle_evolution_scene_step(db, second)
    frozen2 = await store.load_frozen("source-integrity", result2["attempt_id"])
    assert frozen2.previous_receipt == frozen.attempt_id
    assert (
        frozen2.payload["optional_scene_stage"]["steps"]["details"]["status"]
        == "complete"
    )
    assert (
        frozen2.payload["discovery_preparation"]["coverage"]["total_prior_observations"]
        == 1
    )
    assert sampler.calls == 2
    assert [key for key, _ in calls] == ["details", "spatial", "details", "spatial"]
    assert len(frozen2.payload["spatial_stage_result"]["accepted"]) == 1
    second_spatial_inputs = [inputs for key, inputs in calls if key == "spatial"][1]
    assert all(item["scene_index"] < 1 for item in second_spatial_inputs["clues"])
    before_budget = (await store.load_run("source-integrity")).budget_remaining
    replay = await handle_evolution_scene_step(db, first)
    assert replay["recovered"] and sampler.calls == 2
    assert (await store.load_run("source-integrity")).budget_remaining == before_budget


async def test_shadow_optional_protocol_is_settled_without_domain_writes(
    db_session, evolution_project_id
):
    from modules.evolution.optional_scene import load_pending_optional_stage

    db, nid = db_session, evolution_project_id
    scene_id = await seed(db, nid, {1: "城门开启。"})
    store = PostgresAttemptStore(db, nid)
    run = await store.register_run(
        "shadow-optional", mode="append", budget_total=5, execution_mode="shadow"
    )
    run.reading_plan_json = {"optional_stage_version": 1, "spatial_version": 1}
    draft = await get_latest_draft_for_chapter(db, nid, 1)
    source = SceneSourceBinding(
        draft_id=str(draft.id),
        content_hash=draft.content_hash,
        chapter_index=1,
        start_offset=0,
        end_offset=5,
    )
    await db.commit()

    async def forbidden(*args):
        raise AssertionError("shadow cannot write production domains")

    result = await run_scene_step(
        db,
        store,
        run_key=run.run_key,
        scene_index=0,
        scene_text="城门开启。",
        source=source,
        scene_id=scene_id,
        sampler=Sample(),
        applier=forbidden,
        state_review_version=0,
        spatial_version=1,
        source_content_mode="working",
    )
    frozen = await store.load_frozen(run.run_key, result.receipt_attempt_id)
    assert frozen.payload["optional_scene_stage"]["steps"]["spatial"] == {
        "status": "not_run",
        "gaps": [{"reason": "shadow_isolated"}],
    }
    assert (
        await load_pending_optional_stage(store, await store.load_run(run.run_key))
        is None
    )
    assert (await store.load_run(run.run_key)).budget_remaining == 4


@pytest.mark.parametrize("mutation", ["scene", "owner", "source"])
async def test_optional_result_revalidates_after_main_commit(
    db_session, evolution_project_id, monkeypatch, mutation
):
    from modules.evolution.commit import CommitConflictError
    from modules.story.outline_state.models import Scene
    from modules.writing.facade import create_draft_only

    db, nid = db_session, evolution_project_id
    scene_id = await seed(db, nid, {1: "城门开启。"})
    store = await plan_run(db, nid)
    register_scene_sampler("source-integrity", lambda db, novel_id: Sample())
    calls = []

    async def provider(**kwargs):
        calls.append("provider")
        if mutation == "scene":
            scene = await db.get(Scene, UUID(scene_id))
            scene.title = "作者修订后的卡片"
        elif mutation == "owner":
            await store.advance_owner_epoch("source-integrity")
        else:
            await create_draft_only(db, nid, 1, "第一章新稿", "城门关闭。")
        await db.commit()
        return {"result": {}}

    monkeypatch.setattr(
        "modules.evolution.spatial.finish_scene_spatial",
        optional_call("scene_spatial_discovery", provider),
    )
    task = request(
        nid,
        scene_id,
        "城门开启。",
        state_review_version=0,
        spatial_version=1,
        source_content_mode="working",
        budget_total=20,
    )
    if mutation == "scene":
        await handle_evolution_scene_step(db, task)
    else:
        with pytest.raises(CommitConflictError):
            await handle_evolution_scene_step(db, task)
        await db.rollback()
    receipt = await store.load_committed_scene_receipt("source-integrity", 0)
    assert receipt is not None and calls == ["provider"]
    frozen = await store.load_frozen(receipt.run_id, receipt.attempt_id)
    assert "spatial_stage_result" not in frozen.payload
    assert frozen.payload["optional_scene_stage"]["steps"]["spatial"]["status"] == (
        "stale" if mutation == "scene" else "running"
    )
