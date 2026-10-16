from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.operation_trace_models import AssistantOperationTrace
from modules.assistant.operation_trace_service import set_operation_trace_preference
from modules.assistant.schemas import WorkContext
from modules.project.models import Project
from modules.story.character_arcs.operations import OPERATIONS_SPEC
from modules.story.character_arcs.schemas import (
    ArchiveArcPlanInput,
    CharacterArcReadInput,
    ConfirmArcPlanInput,
    RestoreArcPlanInput,
    SceneCharacterReadInput,
)
from modules.story.character_arcs.service import (
    compare_character_arc,
    plan_history,
    preview_plan_save,
    restore_revision,
    save_plan,
)
from modules.story.models import CharacterArcPlanHead, CharacterArcPlanRevision
from tests.e2e.config import DATABASE_URL
from tests.e2e.seed_data import create_full_scene, create_project


@pytest.mark.asyncio
async def test_first_save_and_restore_serialize_across_independent_sessions() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    first_written = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    try:
        async with sessions.begin() as db:
            seeded = await create_full_scene(db)
        novel_id = seeded["project_id"]
        scene_id = seeded["scene_ids"][0]
        character_id = seeded["entity_ids"]["克莱恩·莫雷蒂"]

        async def race(first_input, second_input, operation):
            first_written.clear()
            release_first.clear()
            second_started.clear()
            async with sessions() as db:
                first_preview = await operation[0](db, novel_id, first_input)
            async with sessions() as db:
                second_preview = await operation[0](db, novel_id, second_input)

            async def first():
                async with sessions.begin() as db:
                    result = await operation[1](db, novel_id, first_input, first_preview)
                    first_written.set()
                    await release_first.wait()
                    return result

            async def second():
                await first_written.wait()
                async with sessions.begin() as db:
                    second_started.set()
                    return await operation[1](db, novel_id, second_input, second_preview)

            first_task = asyncio.create_task(first())
            second_task = asyncio.create_task(second())
            try:
                await asyncio.wait_for(second_started.wait(), 5)
                done, _ = await asyncio.wait({second_task}, timeout=0.1)
                assert not done, "the second writer must wait for the first transaction"
            finally:
                release_first.set()
            first_result = await first_task
            try:
                second_result = await second_task
            except ConflictError:
                second_result = None
            return first_result, second_result

        same = ConfirmArcPlanInput(
            operation_id=uuid.uuid4(),
            scene_id=scene_id,
            character_id=character_id,
            expected_version=0,
            plan_text="首次写入的并发幂等计划",
        )
        first, replay = await race(
            same,
            same,
            (
                preview_plan_save,
                lambda db, novel, data, preview: save_plan(
                    db, novel, data, preview.preview_fingerprint
                ),
            ),
        )
        assert first.revision_id == replay.revision_id

        competing = ConfirmArcPlanInput(
            operation_id=uuid.uuid4(),
            scene_id=scene_id,
            character_id=character_id,
            expected_version=1,
            plan_text="并发修订一",
        )
        different = competing.model_copy(
            update={"operation_id": uuid.uuid4(), "plan_text": "并发修订二"}
        )
        second, stale = await race(
            competing,
            different,
            (
                preview_plan_save,
                lambda db, novel, data, preview: save_plan(
                    db, novel, data, preview.preview_fingerprint
                ),
            ),
        )
        assert second.version == 2
        assert stale is None

        restore = RestoreArcPlanInput(
            operation_id=uuid.uuid4(),
            scene_id=scene_id,
            character_id=character_id,
            revision_id=first.revision_id,
            expected_version=2,
        )
        competing_restore = restore.model_copy(update={"operation_id": uuid.uuid4()})

        async def unchanged(_db, _novel, data):
            return data

        restored, stale_restore = await race(
            restore,
            competing_restore,
            (
                unchanged,
                lambda db, novel, data, _preview: restore_revision(db, novel, data),
            ),
        )
        assert restored.version == 3
        assert stale_restore is None
        async with sessions() as db:
            revisions = (
                await db.scalars(
                    select(CharacterArcPlanRevision)
                    .where(
                        CharacterArcPlanRevision.novel_id == uuid.UUID(novel_id),
                        CharacterArcPlanRevision.character_id == character_id,
                    )
                    .order_by(CharacterArcPlanRevision.version_number)
                )
            ).all()
            assert [revision.version_number for revision in revisions] == [1, 2, 3]
    finally:
        release_first.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_arc_http_trace_matches_original_revision_on_restore(
    db_session, async_client
) -> None:
    seeded = await create_full_scene(db_session)
    novel_id = seeded["project_id"]
    scene_id = str(seeded["scene_ids"][0])
    character_id = str(seeded["entity_ids"]["克莱恩·莫雷蒂"])
    await set_operation_trace_preference(db_session, str(BOOTSTRAP_ACCOUNT_ID), True)
    params = {"novel_id": novel_id}
    base = "/api/story/character-arcs/plans"
    save_input = {
        "operation_id": str(uuid.uuid4()),
        "scene_id": scene_id,
        "character_id": character_id,
        "expected_version": 0,
        "plan_text": "合成人物弧：先求助，再行动。",
    }
    preview = await async_client.post(f"{base}/preview", params=params, json=save_input)
    assert preview.status_code == 200, preview.text
    save_input["preview_fingerprint"] = preview.json()["preview_fingerprint"]
    saved = await async_client.post(f"{base}/confirm", params=params, json=save_input)
    assert saved.status_code == 200, saved.text
    save_result = saved.json()

    restore_input = {
        "operation_id": str(uuid.uuid4()),
        "scene_id": scene_id,
        "character_id": character_id,
        "revision_id": save_result["revision_id"],
        "expected_version": 1,
    }
    restored_preview = await async_client.post(
        f"{base}/restore/preview", params=params, json=restore_input
    )
    assert restored_preview.status_code == 200, restored_preview.text
    restore_input["preview_fingerprint"] = restored_preview.json()["fingerprint"]
    restored = await async_client.post(
        f"{base}/restore/confirm", params=params, json=restore_input
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["reversal_ref"] == {
        "type": "revision",
        "id": save_result["revision_id"],
    }
    replay = await async_client.post(
        f"{base}/restore/confirm", params=params, json=restore_input
    )
    assert replay.status_code == 200, replay.text
    traces = (
        await db_session.scalars(
            select(AssistantOperationTrace)
            .where(AssistantOperationTrace.novel_id == uuid.UUID(novel_id))
            .order_by(AssistantOperationTrace.id)
        )
    ).all()
    saved_execution = [
        row
        for row in traces
        if row.op_id == "story.character_arc_plan.save" and row.event_type == "executed"
    ]
    reversal = [
        row
        for row in traces
        if row.op_id == "story.character_arc_plan.save" and row.event_type == "restored"
    ]
    assert len(saved_execution) == len(reversal) == 1
    assert saved_execution[0].call_id == reversal[0].call_id
    assert {"type": "revision", "id": save_result["revision_id"]} in saved_execution[
        0
    ].result_refs
    assert [
        row.event_type
        for row in traces
        if row.op_id == "story.character_arc_plan.restore"
    ].count("executed") == 1
    assert all(
        save_input["plan_text"] not in str(row.parameter_summary) for row in traces
    )


@pytest.mark.asyncio
async def test_arc_read_catalog_enforces_work_scope(db_session) -> None:
    seeded = await create_full_scene(db_session)
    novel_id = seeded["project_id"]
    scene_id = seeded["scene_ids"][0]
    character_id = seeded["entity_ids"]["克莱恩·莫雷蒂"]
    args = {"scene_id": scene_id, "character_id": character_id}
    project = AssistantOperationContext(
        run_id=str(uuid.uuid4()),
        owner_id=str(BOOTSTRAP_ACCOUNT_ID),
        work=WorkContext(scope="project"),
    )
    current = AssistantOperationContext(
        run_id=str(uuid.uuid4()),
        owner_id=str(BOOTSTRAP_ACCOUNT_ID),
        work=WorkContext(scope="current", scene_id=scene_id),
    )
    excluded = AssistantOperationContext(
        run_id=str(uuid.uuid4()),
        owner_id=str(BOOTSTRAP_ACCOUNT_ID),
        work=WorkContext(scope="project", excluded_targets=[f"outline_scene:{scene_id}"]),
    )
    scene_options = await OPERATIONS_SPEC["story.character_arc_plan.scene_characters"][
        "prepare"
    ](db_session, novel_id, SceneCharacterReadInput(scene_id=scene_id), context=current)
    assert any(
        item["character_id"] == str(character_id) for item in scene_options["characters"]
    )
    for name in ("history", "compare"):
        operation = OPERATIONS_SPEC[f"story.character_arc_plan.{name}"]
        read_input = CharacterArcReadInput(**args)
        result = await operation["prepare"](
            db_session, novel_id, read_input, context=project
        )
        assert str(result["character_id"]) == str(character_id)
        with pytest.raises(PermissionError, match="完整作品"):
            await operation["prepare"](db_session, novel_id, read_input, context=current)
        with pytest.raises(ConflictError, match="已排除资料"):
            await operation["prepare"](db_session, novel_id, read_input, context=excluded)


@pytest.mark.asyncio
async def test_author_plan_cas_history_restore_archive_and_cutoff_comparison(
    db_session,
) -> None:
    seeded = await create_full_scene(db_session)
    novel_id = seeded["project_id"]
    scene_id = seeded["scene_ids"][0]
    character_id = seeded["entity_ids"]["克莱恩·莫雷蒂"]
    save = OPERATIONS_SPEC["story.character_arc_plan.save"]
    restore = OPERATIONS_SPEC["story.character_arc_plan.restore"]
    archive = OPERATIONS_SPEC["story.character_arc_plan.archive"]
    unarchive = OPERATIONS_SPEC["story.character_arc_plan.unarchive"]

    initial = ConfirmArcPlanInput(
        operation_id=uuid.uuid4(),
        scene_id=scene_id,
        character_id=character_id,
        expected_version=0,
        plan_text="在失去同伴后，克莱恩逐步学会开口求助。",
    )
    first_preview = await save["prepare"](db_session, novel_id, initial)
    first = await save["apply"](
        db_session,
        novel_id,
        initial.model_copy(
            update={"preview_fingerprint": first_preview["preview_fingerprint"]}
        ),
        first_preview,
    )
    assert first.version == 1
    assert first.audience == "director_only"

    replay_preview = await save["prepare"](db_session, novel_id, initial)
    replay = await save["apply"](
        db_session,
        novel_id,
        initial.model_copy(
            update={"preview_fingerprint": replay_preview["preview_fingerprint"]}
        ),
        replay_preview,
    )
    assert replay.revision_id == first.revision_id
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CharacterArcPlanRevision)
            .where(CharacterArcPlanRevision.novel_id == uuid.UUID(novel_id))
        )
        == 1
    )

    revised = ConfirmArcPlanInput(
        operation_id=uuid.uuid4(),
        scene_id=scene_id,
        character_id=character_id,
        expected_version=1,
        plan_text="她先请求协助，再承担暴露弱点的代价。",
    )
    revised_preview = await save["prepare"](db_session, novel_id, revised)
    second = await save["apply"](
        db_session,
        novel_id,
        revised.model_copy(
            update={"preview_fingerprint": revised_preview["preview_fingerprint"]}
        ),
        revised_preview,
    )
    assert second.version == 2
    stale = initial.model_copy(
        update={"operation_id": uuid.uuid4(), "expected_version": 1}
    )
    with pytest.raises(ConflictError, match="版本已变化"):
        await save["prepare"](db_session, novel_id, stale)

    history = await plan_history(db_session, novel_id, scene_id, character_id)
    first_revision_id = history["items"][-1]["revision_id"]
    restore_input = RestoreArcPlanInput(
        operation_id=uuid.uuid4(),
        scene_id=scene_id,
        character_id=character_id,
        revision_id=first_revision_id,
        expected_version=2,
    )
    restore_preview = await restore["prepare"](db_session, novel_id, restore_input)
    restored = await restore["apply"](
        db_session,
        novel_id,
        restore_input.model_copy(
            update={"preview_fingerprint": restore_preview["fingerprint"]}
        ),
        restore_preview,
    )
    assert restored.version == 3
    assert restored.source == "author_restore"
    assert restored.plan_text == first.plan_text

    archive_input = ArchiveArcPlanInput(
        operation_id=uuid.uuid4(),
        scene_id=scene_id,
        character_id=character_id,
        expected_version=3,
    )
    archive_preview = await archive["prepare"](db_session, novel_id, archive_input)
    archived = await archive["apply"](
        db_session,
        novel_id,
        archive_input.model_copy(
            update={"preview_fingerprint": archive_preview["fingerprint"]}
        ),
        archive_preview,
    )
    assert archived["deleted"] is True
    archived_history = await plan_history(db_session, novel_id, scene_id, character_id)
    assert archived_history["deleted"] is True
    assert archived_history["current_version"] == 4

    unarchive_input = ArchiveArcPlanInput(
        operation_id=uuid.uuid4(),
        scene_id=scene_id,
        character_id=character_id,
        expected_version=4,
    )
    unarchive_preview = await unarchive["prepare"](db_session, novel_id, unarchive_input)
    unarchived = await unarchive["apply"](
        db_session,
        novel_id,
        unarchive_input.model_copy(
            update={"preview_fingerprint": unarchive_preview["fingerprint"]}
        ),
        unarchive_preview,
    )
    assert unarchived.version == 5
    assert unarchived.source == "author_unarchive"

    comparison = await compare_character_arc(db_session, novel_id, scene_id, character_id)
    assert comparison.plan is not None
    assert comparison.plan.version == 5
    assert comparison.plan.source == "author_unarchive"
    assert comparison.cutoff.chapter_cutoff is None
    assert comparison.actual_events == []
    assert comparison.arc_completion == "not_adjudicated"
    assert any("不能核验正文" in gap for gap in comparison.unknowns)


@pytest.mark.asyncio
async def test_postgres_rejects_revision_mutation(db_session) -> None:
    project = await create_project(db_session)
    novel_id = project["project_uuid"]
    character_id = uuid.uuid4()
    head = CharacterArcPlanHead(
        novel_id=novel_id,
        character_id=character_id,
        owner_id=uuid.uuid4(),
        version_number=0,
        current_revision_id=None,
    )
    db_session.add(head)
    await db_session.flush()
    revision = CharacterArcPlanRevision(
        novel_id=novel_id,
        head_id=head.id,
        character_id=character_id,
        owner_id=head.owner_id,
        version_number=1,
        plan_text="作者计划",
        source="author_confirmed",
        audience="director_only",
        operation_id=uuid.uuid4(),
        request_hash="a" * 64,
        content_hash="b" * 64,
        base_revision_id=None,
        restored_from_revision_id=None,
    )
    db_session.add(revision)
    await db_session.flush()
    head.current_revision_id = revision.id
    head.version_number = 1
    await db_session.flush()

    revision.plan_text = "不允许直接改写历史"
    with pytest.raises(
        DBAPIError, match="Story character arc plan revisions are immutable"
    ):
        await db_session.flush()


@pytest.mark.asyncio
async def test_project_deletion_cascades_through_retained_arc_history(db_session) -> None:
    project = await create_project(db_session)
    novel_id = project["project_uuid"]
    character_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    head = CharacterArcPlanHead(
        novel_id=novel_id,
        character_id=character_id,
        owner_id=owner_id,
        version_number=0,
        current_revision_id=None,
    )
    db_session.add(head)
    await db_session.flush()
    revision = CharacterArcPlanRevision(
        novel_id=novel_id,
        head_id=head.id,
        character_id=character_id,
        owner_id=owner_id,
        version_number=1,
        plan_text="项目删除时级联清理",
        source="author_confirmed",
        audience="director_only",
        operation_id=uuid.uuid4(),
        request_hash="c" * 64,
        content_hash="d" * 64,
        base_revision_id=None,
        restored_from_revision_id=None,
    )
    db_session.add(revision)
    await db_session.flush()
    head.current_revision_id = revision.id
    head.version_number = 1
    await db_session.flush()

    await db_session.execute(delete(Project).where(Project.id == novel_id))
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CharacterArcPlanHead)
            .where(CharacterArcPlanHead.novel_id == novel_id)
        )
        == 0
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CharacterArcPlanRevision)
            .where(CharacterArcPlanRevision.novel_id == novel_id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_arc_history_guard_rejects_direct_and_nested_deletes_with_temp_shadow(
    db_session,
) -> None:
    project = await create_project(db_session)
    novel_id = project["project_uuid"]
    owner_id, character_id = uuid.uuid4(), uuid.uuid4()
    head = CharacterArcPlanHead(
        novel_id=novel_id,
        character_id=character_id,
        owner_id=owner_id,
        version_number=0,
        current_revision_id=None,
    )
    db_session.add(head)
    await db_session.flush()
    revision = CharacterArcPlanRevision(
        novel_id=novel_id,
        head_id=head.id,
        character_id=character_id,
        owner_id=owner_id,
        version_number=1,
        plan_text="不可变作者历史",
        source="author_confirmed",
        audience="director_only",
        operation_id=uuid.uuid4(),
        request_hash="e" * 64,
        content_hash="f" * 64,
        base_revision_id=None,
        restored_from_revision_id=None,
    )
    db_session.add(revision)
    await db_session.flush()
    head.current_revision_id = revision.id
    head.version_number = 1
    await db_session.flush()

    for table, target_id in (
        ("story_character_arc_plan_revisions", revision.id),
        ("story_character_arc_plan_heads", head.id),
    ):
        with pytest.raises(DBAPIError, match="immutable|soft-deleted"):
            async with db_session.begin_nested():
                await db_session.execute(
                    text(f"DELETE FROM {table} WHERE id = :id"), {"id": target_id}
                )

    # Empty TEMP projects would make an unqualified existence check claim that
    # the real Project was deleted. A nested trigger must still reject cleanup.
    await db_session.execute(text("CREATE TEMP TABLE projects (id uuid)"))
    for table, target_id in (
        ("story_character_arc_plan_revisions", revision.id),
        ("story_character_arc_plan_heads", head.id),
    ):
        probe = f"arc_guard_probe_{'revision' if table.endswith('revisions') else 'head'}"
        await db_session.execute(text(f"CREATE TEMP TABLE {probe} (id uuid)"))
        await db_session.execute(
            text(f"INSERT INTO {probe} (id) VALUES (:id)"), {"id": target_id}
        )
        await db_session.execute(
            text(
                f"""CREATE FUNCTION pg_temp.try_delete_{probe}() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN
                    DELETE FROM public.{table} WHERE id = OLD.id;
                    RETURN OLD;
                END $$"""
            )
        )
        await db_session.execute(
            text(
                f"""CREATE TRIGGER {probe}_nested BEFORE DELETE ON {probe}
                FOR EACH ROW EXECUTE FUNCTION pg_temp.try_delete_{probe}()"""
            )
        )
        with pytest.raises(DBAPIError, match="immutable|soft-deleted"):
            async with db_session.begin_nested():
                await db_session.execute(
                    text(f"DELETE FROM {probe} WHERE id = :id"), {"id": target_id}
                )
