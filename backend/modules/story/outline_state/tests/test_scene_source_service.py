from __future__ import annotations

import uuid

import pytest

from modules.story.outline_state.facade import (
    bind_scene_spans_to_source,
    get_scene_summary_checkpoint,
    rebuild_scene_summary_checkpoint,
)
from modules.story.outline_state.repositories import SceneRepository
from modules.story.outline_state.schemas import SceneCreate
from modules.writing.facade import create_draft_only, create_published_draft_only


@pytest.mark.asyncio
async def test_scene_span_binds_to_concrete_published_source(
    db_session,
    test_project_id,
) -> None:
    content = "第一段\n灰雾笼罩城门\n第三段"
    draft = await create_published_draft_only(
        db_session,
        test_project_id,
        1,
        content=content,
    )
    start = content.index("灰雾")
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=1,
            title="城门灰雾",
            scene_chunks=[
                {
                    "chapter_index": 1,
                    "start_offset": start,
                    "end_offset": start + len("灰雾笼罩城门"),
                }
            ],
            chapter_ids=["1"],
            status="canonical",
        ),
    )

    spans = await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=1,
        content_mode="canonical",
        source_draft_id=draft.id or "",
        source_content_hash=draft.content_hash,
        content=content,
    )

    assert spans[0].source_draft_id == draft.id
    assert spans[0].source_content_hash == draft.content_hash
    assert spans[0].mapping_status == "exact"
    assert spans[0].scene_id == str(scene.id)


@pytest.mark.asyncio
async def test_legacy_chapter_only_span_is_not_promoted_from_untrusted_offsets(
    db_session,
    test_project_id,
) -> None:
    content = "旧数据偏移看似可用"
    draft = await create_published_draft_only(
        db_session,
        test_project_id,
        2,
        content=content,
    )
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=2,
            scene_chunks=[
                {
                    "chapter_index": 2,
                    "start_offset": 0,
                    "end_offset": len(content),
                }
            ],
            chapter_ids=["2"],
            status="canonical",
        ),
    )
    stored = await SceneRepository().get_scene_spans_for_scene(
        db_session,
        uuid.UUID(test_project_id),
        scene.id,
        statuses=("canonical",),
        content_mode="canonical",
    )
    stored[0].mapping_status = "chapter_only"
    stored[0].anchor_hash = None
    stored[0].anchor_excerpt = None
    await db_session.flush()

    spans = await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=2,
        content_mode="canonical",
        source_draft_id=draft.id or "",
        source_content_hash=draft.content_hash,
        content=content,
    )

    assert spans[0].mapping_status == "chapter_only"
    assert spans[0].source_draft_id == draft.id
    assert spans[0].anchor_hash is None


@pytest.mark.asyncio
async def test_checkpoint_reads_only_visible_bound_spans(
    db_session,
    test_project_id,
) -> None:
    content = "第八十章线索\n第八十一章真相"
    draft = await create_published_draft_only(
        db_session,
        test_project_id,
        80,
        content=content,
    )
    cutoff = content.index("\n")
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=80,
            scene_chunks=[
                {
                    "chapter_index": 80,
                    "start_offset": 0,
                    "end_offset": len(content),
                }
            ],
            chapter_ids=["80"],
            status="canonical",
        ),
    )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=80,
        content_mode="canonical",
        source_draft_id=draft.id or "",
        source_content_hash=draft.content_hash,
        content=content,
    )

    checkpoint = await rebuild_scene_summary_checkpoint(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        content_mode="canonical",
        through_chapter=80,
        through_offset=cutoff,
    )
    loaded = await get_scene_summary_checkpoint(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        content_mode="canonical",
        through_chapter=80,
        through_offset=cutoff,
    )

    assert checkpoint is not None
    assert loaded is not None
    assert "线索" in loaded.summary
    assert "真相" not in loaded.summary


@pytest.mark.asyncio
async def test_working_span_reanchors_only_on_unique_anchor(
    db_session,
    test_project_id,
) -> None:
    anchor = "铜铃在雨夜响起"
    canonical_content = f"开场\n{anchor}\n结尾"
    canonical = await create_published_draft_only(
        db_session,
        test_project_id,
        7,
        content=canonical_content,
    )
    start = canonical_content.index(anchor)
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=7,
            scene_chunks=[
                {
                    "chapter_index": 7,
                    "start_offset": start,
                    "end_offset": start + len(anchor),
                }
            ],
            chapter_ids=["7"],
            status="canonical",
        ),
    )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=7,
        content_mode="canonical",
        source_draft_id=canonical.id or "",
        source_content_hash=canonical.content_hash,
        content=canonical_content,
    )
    working_content = f"新增引子\n{canonical_content}"
    working = await create_draft_only(
        db_session,
        test_project_id,
        7,
        content=working_content,
    )

    spans = await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=7,
        content_mode="working",
        source_draft_id=working.id or "",
        source_content_hash=working.content_hash,
        content=working_content,
    )

    assert len(spans) == 1
    assert spans[0].scene_id == str(scene.id)
    assert spans[0].mapping_status == "reanchored"
    assert spans[0].start_offset == working_content.index(anchor)


@pytest.mark.asyncio
async def test_working_span_with_ambiguous_anchor_becomes_unresolved(
    db_session,
    test_project_id,
) -> None:
    anchor = "重复的暗号"
    canonical_content = f"开场\n{anchor}\n结尾"
    canonical = await create_published_draft_only(
        db_session,
        test_project_id,
        8,
        content=canonical_content,
    )
    start = canonical_content.index(anchor)
    await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=8,
            scene_chunks=[
                {
                    "chapter_index": 8,
                    "start_offset": start,
                    "end_offset": start + len(anchor),
                }
            ],
            chapter_ids=["8"],
            status="canonical",
        ),
    )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=8,
        content_mode="canonical",
        source_draft_id=canonical.id or "",
        source_content_hash=canonical.content_hash,
        content=canonical_content,
    )
    working_content = f"位置已移动\n{anchor}\n中间\n{anchor}"
    working = await create_draft_only(
        db_session,
        test_project_id,
        8,
        content=working_content,
    )

    spans = await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=8,
        content_mode="working",
        source_draft_id=working.id or "",
        source_content_hash=working.content_hash,
        content=working_content,
    )

    assert spans[0].mapping_status == "unresolved"


@pytest.mark.asyncio
async def test_checkpoint_is_ignored_after_working_source_hash_changes(
    db_session,
    test_project_id,
) -> None:
    content = "可见工作稿摘录"
    draft = await create_draft_only(
        db_session,
        test_project_id,
        9,
        content=content,
    )
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=9,
            scene_chunks=[
                {
                    "chapter_index": 9,
                    "start_offset": 0,
                    "end_offset": len(content),
                }
            ],
            chapter_ids=["9"],
            status="canonical",
        ),
    )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=9,
        content_mode="working",
        source_draft_id=draft.id or "",
        source_content_hash=draft.content_hash,
        content=content,
    )
    checkpoint = await rebuild_scene_summary_checkpoint(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        content_mode="working",
        through_chapter=9,
    )
    assert checkpoint is not None
    await create_draft_only(
        db_session,
        test_project_id,
        9,
        content="新版本工作稿已改变",
    )

    loaded = await get_scene_summary_checkpoint(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        content_mode="working",
        through_chapter=9,
    )

    assert loaded is None
