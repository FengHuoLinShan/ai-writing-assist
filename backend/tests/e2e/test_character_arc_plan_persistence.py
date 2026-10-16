from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError

from core.errors import ConflictError
from modules.project.models import Project
from modules.story.character_arcs.operations import OPERATIONS_SPEC
from modules.story.character_arcs.schemas import (
    ArchiveArcPlanInput,
    ConfirmArcPlanInput,
    RestoreArcPlanInput,
)
from modules.story.character_arcs.service import compare_character_arc, plan_history
from modules.story.models import CharacterArcPlanHead, CharacterArcPlanRevision
from tests.e2e.seed_data import create_full_scene, create_project


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
            select(func.count()).select_from(CharacterArcPlanRevision)
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
