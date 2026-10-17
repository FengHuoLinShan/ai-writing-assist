from __future__ import annotations

import uuid

import pytest

from core.errors import ConflictError
from modules.story.character_arcs.schemas import (
    ArchiveArcPlanInput,
    ConfirmArcPlanInput,
    RestoreArcPlanInput,
)
from modules.story.character_arcs.service import (
    archive_plan,
    plan_history,
    preview_plan_save,
    restore_revision,
    save_plan,
    unarchive_plan,
)
from modules.story.outline_state.repositories import SceneRepository
from modules.story.outline_state.schemas import SceneCreate
from modules.world.models import Character


@pytest.mark.asyncio
async def test_author_arc_plan_full_lifecycle_on_sqlite(
    db_session, test_project_id, test_character_id
) -> None:
    db_session.add(
        Character(
            entity_id=uuid.UUID(test_character_id),
            novel_id=uuid.UUID(test_project_id),
            name="测试主角",
            status="canonical",
        )
    )
    await db_session.flush()
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=0,
            title="测试场景",
            chapter_ids=["1"],
            pov_character_id=test_character_id,
            status="canonical",
        ),
    )

    first_input = ConfirmArcPlanInput(
        operation_id=uuid.uuid4(),
        scene_id=scene.id,
        character_id=uuid.UUID(test_character_id),
        expected_version=0,
        plan_text="克服独自承担的习惯。",
    )
    first_preview = await preview_plan_save(db_session, test_project_id, first_input)
    first = await save_plan(
        db_session, test_project_id, first_input, first_preview.preview_fingerprint
    )
    assert first.version == 1

    stale_input = first_input.model_copy(
        update={
            "operation_id": uuid.uuid4(),
            "expected_version": 1,
            "plan_text": "过期计划",
        }
    )
    stale_preview = await preview_plan_save(db_session, test_project_id, stale_input)
    second_input = first_input.model_copy(
        update={
            "operation_id": uuid.uuid4(),
            "expected_version": 1,
            "plan_text": "先请求协助，再承担风险。",
        }
    )
    second_preview = await preview_plan_save(db_session, test_project_id, second_input)
    second = await save_plan(
        db_session, test_project_id, second_input, second_preview.preview_fingerprint
    )
    assert second.version == 2
    with pytest.raises(ConflictError, match="版本已变化"):
        await save_plan(
            db_session, test_project_id, stale_input, stale_preview.preview_fingerprint
        )

    restore_input = RestoreArcPlanInput(
        operation_id=uuid.uuid4(),
        scene_id=scene.id,
        character_id=uuid.UUID(test_character_id),
        revision_id=first.revision_id,
        expected_version=2,
    )
    restored = await restore_revision(db_session, test_project_id, restore_input)
    assert restored.version == 3
    assert restored.source == "author_restore"
    assert restored.plan_text == first.plan_text

    archive_input = ArchiveArcPlanInput(
        operation_id=uuid.uuid4(),
        scene_id=scene.id,
        character_id=uuid.UUID(test_character_id),
        expected_version=3,
    )
    archived = await archive_plan(db_session, test_project_id, archive_input)
    assert archived["deleted"] is True
    assert archived["version"] == 4

    unarchive_input = archive_input.model_copy(
        update={"operation_id": uuid.uuid4(), "expected_version": 4}
    )
    unarchived = await unarchive_plan(db_session, test_project_id, unarchive_input)
    assert unarchived.version == 5
    assert unarchived.source == "author_unarchive"

    history = await plan_history(
        db_session, test_project_id, str(scene.id), test_character_id
    )
    assert history["deleted"] is False
    assert history["current_version"] == 5
    assert [item["source"] for item in reversed(history["items"])] == [
        "author_confirmed",
        "author_confirmed",
        "author_restore",
        "author_archive",
        "author_unarchive",
    ]
