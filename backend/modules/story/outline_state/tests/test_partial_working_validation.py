"""Partial working anchors must retain every precise cross-chapter boundary."""

from uuid import UUID, uuid4

import pytest

from core.errors import ValidationError
from modules.story.outline_state.facade import (
    bind_scene_spans_to_source,
    validate_scene_source_ranges,
)
from modules.story.outline_state.repositories import SceneRepository
from modules.story.outline_state.schemas import SceneCreate
from modules.writing.facade import create_draft_only


async def partial_scene(db, nid):
    drafts = [
        await create_draft_only(db, nid, chapter, f"第{chapter}章", text)
        for chapter, text in [(1, "第一章的场景"), (2, "第二章的场景")]
    ]
    sources = [
        {
            "chapter_index": index,
            "draft_id": draft.id,
            "content_hash": draft.content_hash,
            "start_offset": 0,
            "end_offset": len(draft.content),
        }
        for index, draft in enumerate(drafts, 1)
    ]
    scene = await SceneRepository().create(
        db,
        UUID(nid),
        SceneCreate(
            scene_index=1,
            title="跨章场景",
            chapter_ids=["1", "2"],
            scene_chunks=[
                {
                    "chapter_index": s["chapter_index"],
                    "start_offset": s["start_offset"],
                    "end_offset": s["end_offset"],
                    "source_draft_id": s["draft_id"],
                    "source_content_hash": s["content_hash"],
                }
                for s in sources
            ],
            status="draft",
        ),
    )
    await bind_scene_spans_to_source(
        db,
        novel_id=nid,
        chapter_index=1,
        content_mode="working",
        source_draft_id=drafts[0].id,
        source_content_hash=drafts[0].content_hash,
        content=drafts[0].content,
    )
    working = await SceneRepository().get_scene_spans_for_scene(
        db, UUID(nid), scene.id, content_mode="working"
    )
    assert len(working) == 1
    return scene, sources, working[0]


async def test_partial_working_retains_other_canonical_parts(db_session, test_project_id):
    scene, sources, _ = await partial_scene(db_session, test_project_id)
    await validate_scene_source_ranges(
        db_session, test_project_id, str(scene.id), 1, sources
    )
    # No derived anchors are invented or written by validation.
    actual = await SceneRepository().get_scene_spans_for_scene(
        db_session, UUID(test_project_id), scene.id, content_mode="working"
    )
    assert len(actual) == 1
    with pytest.raises(ValidationError, match="does not cover"):
        await validate_scene_source_ranges(
            db_session, test_project_id, str(scene.id), 1, sources[:1]
        )


@pytest.mark.parametrize("drift", ["mapping", "offset", "draft", "hash"])
async def test_working_part_never_hidden_by_canonical_fallback(
    db_session, test_project_id, drift
):
    scene, sources, working = await partial_scene(db_session, test_project_id)
    if drift == "mapping":
        working.mapping_status = "needs_repair"
    elif drift == "offset":
        working.start_offset = 1
    elif drift == "draft":
        working.source_draft_id = uuid4()
    else:
        working.source_content_hash = "0" * 64
    await db_session.flush()
    with pytest.raises(ValidationError, match="changed"):
        await validate_scene_source_ranges(
            db_session, test_project_id, str(scene.id), 1, sources
        )


async def test_missing_part_still_requires_original_revision(db_session, test_project_id):
    scene, sources, _ = await partial_scene(db_session, test_project_id)
    sources[1]["content_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="changed"):
        await validate_scene_source_ranges(
            db_session, test_project_id, str(scene.id), 1, sources
        )
