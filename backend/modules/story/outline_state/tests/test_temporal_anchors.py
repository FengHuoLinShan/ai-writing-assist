"""Temporal consumers see current order and retired identities within one project."""

from uuid import UUID, uuid4

import pytest

from modules.story.facade import read_temporal_anchor_scenes
from modules.story.outline_state.models import Scene
from modules.story.scene_source_port import SceneSourcePort


async def test_temporal_anchor_port_keeps_replacements_and_current_order(
    db_session, test_project_id, project_factory
):
    other = await project_factory.create_project()
    replacement_id = uuid4()
    retired = Scene(
        novel_id=UUID(test_project_id),
        scene_index=0,
        status="deprecated",
        chapter_ids=["chapter-a"],
        structure_meta={"replaced_by_scene_ids": [str(replacement_id)]},
    )
    replacement = Scene(
        id=replacement_id,
        novel_id=UUID(test_project_id),
        scene_index=3,
        status="draft",
        chapter_ids=["chapter-a"],
    )
    hidden = Scene(novel_id=other, scene_index=1, status="canonical")
    db_session.add_all([retired, replacement, hidden])
    await db_session.flush()

    rows = await SceneSourcePort.read_temporal_anchor_scenes(db_session, test_project_id)
    assert [row["scene_id"] for row in rows] == [str(retired.id), str(replacement.id)]
    assert rows[0]["replaced_by_scene_ids"] == [str(replacement.id)]
    assert rows[1]["chapter_ids"] == ["chapter-a"]

    replacement.scene_index = -1
    await db_session.flush()
    reordered = await read_temporal_anchor_scenes(db_session, test_project_id)
    assert [row["scene_id"] for row in reordered] == [
        str(replacement.id),
        str(retired.id),
    ]
    assert await read_temporal_anchor_scenes(db_session, str(uuid4())) == []


@pytest.mark.parametrize("replacement_ids", [None, 123, "not-a-list", {"id": "invalid"}])
async def test_temporal_anchor_port_treats_malformed_replacements_as_unresolved(
    db_session, test_project_id, replacement_ids
):
    # structure_meta is an open author-editable dict, including null values.
    from modules.story.outline_state.schemas import SceneCreate

    payload = SceneCreate(
        scene_index=0, structure_meta={"replaced_by_scene_ids": replacement_ids}
    )
    scene = Scene(
        novel_id=UUID(test_project_id),
        scene_index=payload.scene_index,
        status="deprecated",
        structure_meta=payload.structure_meta,
    )
    db_session.add(scene)
    await db_session.flush()
    rows = await read_temporal_anchor_scenes(db_session, test_project_id)
    assert rows == [
        {
            "scene_id": str(scene.id),
            "scene_index": 0,
            "status": "deprecated",
            "chapter_ids": [],
            "replaced_by_scene_ids": [],
        }
    ]
