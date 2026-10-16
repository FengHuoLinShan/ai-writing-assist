from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError

from modules.project.models import Project
from modules.story.world_progression_models import (
    StoryWorldProgressionBranch,
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)
from tests.e2e.seed_data import create_project


async def _seed_progression(db_session, novel_id: uuid.UUID):
    root = StoryWorldProgressionRoot(
        novel_id=novel_id,
        scene_id=uuid.uuid4(),
        source_hash="a" * 64,
        request_json={},
        source_snapshot_json={},
        llm_execution_snapshot_json={},
        run_envelope_json={},
        context_confirmation_id="postgres-test-confirmation",
        status="done",
    )
    db_session.add(root)
    await db_session.flush()

    branch = StoryWorldProgressionBranch(
        novel_id=novel_id,
        root_id=root.id,
        branch_kind="start",
        basis_choice="current",
        source_hash="a" * 64,
        request_json={},
        source_snapshot_json={},
        status="done",
        pending_step_json={},
        note="",
        starred=False,
    )
    db_session.add(branch)
    await db_session.flush()

    step = StoryWorldProgressionStep(
        novel_id=novel_id,
        root_id=root.id,
        branch_id=branch.id,
        step_number=1,
        source_hash="a" * 64,
        input_hash="b" * 64,
        output_hash="c" * 64,
        input_json={},
        result_json={},
        state_json={},
        metrics_json={},
        basis_changed=False,
    )
    db_session.add(step)
    await db_session.flush()
    return root, branch, step


@pytest.mark.asyncio
async def test_progression_step_rejects_mutation_but_branch_metadata_is_editable(
    db_session,
) -> None:
    project = await create_project(db_session)
    novel_id = project["project_uuid"]
    _, branch, step = await _seed_progression(db_session, novel_id)

    branch.note = "author note"
    await db_session.flush()

    step.result_json = {"edited": True}
    with pytest.raises(DBAPIError, match="world progression steps are immutable"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_progression_step_rejects_direct_delete(db_session) -> None:
    project = await create_project(db_session)
    _, _, step = await _seed_progression(db_session, project["project_uuid"])

    await db_session.delete(step)
    with pytest.raises(DBAPIError, match="world progression steps are immutable"):
        await db_session.flush()


@pytest.mark.parametrize("parent_kind", ["branch", "root"])
@pytest.mark.asyncio
async def test_live_progression_parent_cannot_cascade_delete_steps(
    db_session, parent_kind: str
) -> None:
    project = await create_project(db_session)
    novel_id = project["project_uuid"]
    root, branch, _ = await _seed_progression(db_session, novel_id)
    parent = branch if parent_kind == "branch" else root

    with pytest.raises(DBAPIError, match="world progression steps are immutable"):
        await db_session.execute(delete(type(parent)).where(type(parent).id == parent.id))


@pytest.mark.asyncio
async def test_project_delete_can_cascade_through_retained_progression_history(
    db_session,
) -> None:
    project = await create_project(db_session)
    novel_id = project["project_uuid"]
    await _seed_progression(db_session, novel_id)

    await db_session.execute(delete(Project).where(Project.id == novel_id))
    remaining_steps = await db_session.scalar(
        select(func.count())
        .select_from(StoryWorldProgressionStep)
        .where(StoryWorldProgressionStep.novel_id == novel_id)
    )
    assert remaining_steps == 0


@pytest.mark.asyncio
async def test_temp_project_shadow_cannot_authorize_live_parent_cascade(
    db_session,
) -> None:
    project = await create_project(db_session)
    root, _, _ = await _seed_progression(db_session, project["project_uuid"])
    await db_session.execute(text("CREATE TEMP TABLE projects (id uuid) ON COMMIT DROP"))

    with pytest.raises(DBAPIError, match="world progression steps are immutable"):
        await db_session.execute(
            delete(StoryWorldProgressionRoot).where(
                StoryWorldProgressionRoot.id == root.id
            )
        )


@pytest.mark.asyncio
async def test_nested_trigger_cannot_delete_step_while_project_exists(
    db_session,
) -> None:
    project = await create_project(db_session)
    _, _, step = await _seed_progression(db_session, project["project_uuid"])
    await db_session.execute(text("CREATE TEMP TABLE nested_step_delete (step_id uuid)"))
    await db_session.execute(
        text(
            """
            CREATE FUNCTION pg_temp.try_delete_progression_step() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                DELETE FROM story_world_progression_steps WHERE id = NEW.step_id;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    await db_session.execute(
        text(
            """
            CREATE TRIGGER nested_step_delete_trigger AFTER INSERT
            ON nested_step_delete FOR EACH ROW
            EXECUTE FUNCTION pg_temp.try_delete_progression_step()
            """
        )
    )

    with pytest.raises(DBAPIError, match="world progression steps are immutable"):
        await db_session.execute(
            text("INSERT INTO nested_step_delete (step_id) VALUES (:step_id)"),
            {"step_id": step.id},
        )
