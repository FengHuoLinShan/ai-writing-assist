from __future__ import annotations

import uuid

import pytest

from modules.context.facade import prepare_import_context_activation
from modules.context.services.import_activation import ImportContextActivationService


def test_import_activation_prefers_offset_spans() -> None:
    text = "0123456789"
    result = ImportContextActivationService._slice_text(
        text,
        [{"start_offset": 2, "end_offset": 6}],
    )
    assert result == "2345"


def test_import_activation_rejects_paragraph_only_mapping() -> None:
    text = "one\n\ntwo\n\nthree"
    result = ImportContextActivationService._slice_text(
        text,
        [{"start_paragraph": 1, "end_paragraph": 2}],
    )
    assert result == ""


def test_world_context_deduplicates_groups_and_records_budget_event() -> None:
    text, events = ImportContextActivationService._world_context(
        [
            {"group": "entity:a", "title": "A", "summary": "first"},
            {"group": "entity:a", "title": "A2", "summary": "duplicate"},
            {"group": "entity:b", "title": "B", "summary": "long " * 300},
        ],
        budget_tokens=20,
    )
    assert "A: first" in text
    assert "A2" not in text
    assert events


def test_import_activation_clips_cross_chapter_scene_at_visibility_cursor() -> None:
    chunks = [
        {"chapter_index": 79, "start_offset": 1, "end_offset": 8},
        {"chapter_index": 80, "start_offset": 2, "end_offset": 9},
        {"chapter_index": 81, "start_offset": 0, "end_offset": 6},
    ]

    result = ImportContextActivationService._clip_chunks_to_visibility(
        chunks,
        visible_until_chapter=80,
        visible_until_offset=5,
    )

    assert result == [
        {"chapter_index": 79, "start_offset": 1, "end_offset": 8},
        {"chapter_index": 80, "start_offset": 2, "end_offset": 5},
    ]
    assert chunks[1]["end_offset"] == 9


def test_import_activation_rejects_offset_without_cutoff_chapter() -> None:
    try:
        ImportContextActivationService._clip_chunks_to_visibility(
            [],
            visible_until_chapter=None,
            visible_until_offset=5,
        )
    except ValueError as exc:
        assert str(exc) == "visible_until_offset_requires_chapter"
    else:
        raise AssertionError("offset-only visibility cursor must be rejected")


@pytest.mark.asyncio
async def test_import_activation_excludes_future_span_from_cross_chapter_scene(
    db_session,
    test_project_id,
) -> None:
    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate
    from modules.writing.facade import create_draft_only

    visible = "第八十章可见线索"
    future = "第八十一章未来真相"
    await create_draft_only(
        db_session,
        test_project_id,
        80,
        content=visible,
    )
    await create_draft_only(
        db_session,
        test_project_id,
        81,
        content=future,
    )
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=80,
            title="跨章 Scene",
            chapter_ids=["80", "81"],
            scene_chunks=[
                {"chapter_index": 80, "start_offset": 0, "end_offset": len(visible)},
                {"chapter_index": 81, "start_offset": 0, "end_offset": len(future)},
            ],
            status="canonical",
        ),
    )

    activation = await prepare_import_context_activation(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        context_mode="working",
        visible_until_chapter=80,
    )

    assert visible in activation.current_scene_text
    assert future not in activation.current_scene_text
    assert activation.chapter_index == 80
    assert {source["chapter_index"] for source in activation.current_scene_sources} == {
        80
    }
