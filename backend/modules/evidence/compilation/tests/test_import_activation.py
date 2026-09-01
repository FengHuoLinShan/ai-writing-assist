from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from modules.evidence.compilation.facade import prepare_import_context_activation
from modules.evidence.compilation.services.import_activation import (
    ImportContextActivationService,
)


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


def test_identity_candidates_keep_all_direct_mentions_then_apply_type_top_k() -> None:
    candidates = [
        {
            "entity_id": f"character-{index}",
            "entity_type": "character",
            "name": f"人物{index}",
            "aliases": [f"人{index}"],
            "summary": None,
            "public_info": None,
            "importance": index / 100,
            "status": "canonical",
        }
        for index in range(10)
    ]
    candidates.extend(
        {
            "entity_id": f"object-{index}",
            "entity_type": "item",
            "name": f"物品{index}",
            "aliases": [],
            "summary": None,
            "public_info": None,
            "importance": index / 100,
            "status": "canonical",
        }
        for index in range(20)
    )
    current_text = "人物0与人1检查物品0。"

    selected, sources = ImportContextActivationService._select_identity_candidates(
        current_text,
        candidates,
        scene_related_ids=set(),
        outline_related_ids=set(),
    )

    reason_by_ref = {
        item["prompt_ref"]: item["selection_reason"] for item in sources
    }
    direct = [
        item
        for item in selected
        if reason_by_ref[item["prompt_ref"]] == "direct_mention"
    ]
    remaining_characters = [
        item
        for item in selected
        if item["entity_type"] == "character"
        and reason_by_ref[item["prompt_ref"]] != "direct_mention"
    ]
    remaining_objects = [
        item
        for item in selected
        if item["entity_type"] != "character"
        and reason_by_ref[item["prompt_ref"]] != "direct_mention"
    ]
    assert [item["name"] for item in direct] == ["人物0", "人物1", "物品0"]
    assert len(remaining_characters) == 6
    assert len(remaining_objects) == 16
    assert all("entity_id" not in item for item in selected)
    assert all(
        set(item) == {"prompt_ref", "entity_type", "name", "aliases", "status"}
        for item in selected
    )
    assert [item["prompt_ref"] for item in selected] == [
        f"entity-{index:03d}" for index in range(1, len(selected) + 1)
    ]
    assert all(source["type"] == "world_entity" for source in sources)


def test_import_activation_context_fingerprint_tracks_selected_context() -> None:
    base = {
        "current_text": "完整 Scene 正文",
        "current_sources": [{"type": "source_range", "content_hash": "hash-1"}],
        "scene_card": {"title": "标题"},
        "outline_context": {"scenes": [], "arcs": [], "plot_threads": []},
        "identity_candidates": [{"prompt_ref": "entity-001", "name": "沈砚"}],
        "previous_briefs": [],
        "previous_evidence": [],
    }

    fingerprint = ImportContextActivationService._context_fingerprint(**base)
    changed = ImportContextActivationService._context_fingerprint(
        **{**base, "scene_card": {"title": "改变后的标题"}}
    )

    assert fingerprint != changed
    assert len(fingerprint) == 64


def test_import_activation_rejects_partial_visible_scene_span_coverage() -> None:
    chunks = [
        {"chapter_index": 1, "start_offset": 0, "end_offset": 10},
        {"chapter_index": 2, "start_offset": 0, "end_offset": 10},
    ]
    spans = [
        SimpleNamespace(
            chapter_index=1,
            start_offset=0,
            end_offset=10,
            mapping_status="exact",
        ),
        SimpleNamespace(
            chapter_index=2,
            start_offset=0,
            end_offset=10,
            mapping_status="unresolved",
        ),
    ]

    assert not ImportContextActivationService._has_complete_visible_span_coverage(
        chunks,
        spans,
        visible_until_chapter=None,
        visible_until_offset=None,
    )
    assert ImportContextActivationService._has_complete_visible_span_coverage(
        chunks,
        spans,
        visible_until_chapter=1,
        visible_until_offset=None,
    )


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
    from modules.story.outline_state.repositories import SceneRepository
    from modules.story.outline_state.schemas import SceneCreate
    from modules.world.facade import create_entity
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
    await create_entity(
        db_session,
        test_project_id,
        {
            "name": "只在资料中出现的正式名",
            "entity_type": "item",
            "status": "canonical",
            "content_json": {"aliases": ["可见线索"]},
        },
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
    assert activation.activation_version == "import-context-v3"
    assert len(activation.context_fingerprint) == 64
    assert activation.budget_events == []
    assert activation.scene_card["title"] == "跨章 Scene"
    alias_candidate = next(
        item
        for item in activation.identity_candidates
        if item["name"] == "只在资料中出现的正式名"
    )
    assert alias_candidate["aliases"] == ["可见线索"]
    assert "entity_id" not in alias_candidate


@pytest.mark.asyncio
async def test_import_activation_pages_through_all_relevant_relations(
    db_session,
    test_project_id,
) -> None:
    from modules.story.outline_state.repositories import SceneRepository
    from modules.story.outline_state.schemas import SceneCreate
    from modules.world.facade import create_entity, create_relation
    from modules.writing.facade import create_draft_only

    text = "甲与乙重申古老盟约。"
    await create_draft_only(db_session, test_project_id, 2, content=text)
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=2,
            title="盟约",
            chapter_ids=["2"],
            scene_chunks=[
                {"chapter_index": 2, "start_offset": 0, "end_offset": len(text)}
            ],
            status="canonical",
        ),
    )
    source = await create_entity(
        db_session,
        test_project_id,
        {"name": "甲", "entity_type": "character", "status": "canonical"},
    )
    target = await create_entity(
        db_session,
        test_project_id,
        {"name": "乙", "entity_type": "character", "status": "canonical"},
    )
    await create_relation(
        db_session,
        test_project_id,
        {
            "source_id": str(source["id"]),
            "target_id": str(target["id"]),
            "relation_type": "ancient-alliance",
            "relation_kind": "social",
            "review_meta": {"scene_index": 0, "source_chapter_index": 1},
        },
    )
    for index in range(50):
        await create_relation(
            db_session,
            test_project_id,
            {
                "source_id": str(source["id"]),
                "target_id": str(target["id"]),
                "relation_type": f"noise-{index:02d}",
                "relation_kind": "state",
                "strength": index / 100,
                "review_meta": (
                    {"scene_index": 0, "source_chapter_index": 1}
                    if index < 2
                    else None
                ),
            },
        )
    await create_relation(
        db_session,
        test_project_id,
        {
            "source_id": str(source["id"]),
            "target_id": str(target["id"]),
            "relation_type": "future-old-workflow",
            "relation_kind": "social",
            "review_meta": {"scene_index": 0, "source_chapter_index": 3},
        },
    )
    await create_relation(
        db_session,
        test_project_id,
        {
            "source_id": str(source["id"]),
            "target_id": str(target["id"]),
            "relation_type": "same-chapter-previous-scene",
            "relation_kind": "social",
            "review_meta": {"scene_index": 1, "source_chapter_index": 2},
        },
    )
    await create_relation(
        db_session,
        test_project_id,
        {
            "source_id": str(source["id"]),
            "target_id": str(target["id"]),
            "relation_type": "future-scene-index",
            "relation_kind": "social",
            "review_meta": {"scene_index": 3, "source_chapter_index": 1},
        },
    )

    activation = await prepare_import_context_activation(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        context_mode="working",
    )

    assert len(activation.relation_candidates) == 4
    assert "ancient-alliance" in {
        item["relation_type"] for item in activation.relation_candidates
    }
    assert "future-old-workflow" not in {
        item["relation_type"] for item in activation.relation_candidates
    }
    assert "same-chapter-previous-scene" in {
        item["relation_type"] for item in activation.relation_candidates
    }
    assert "future-scene-index" not in {
        item["relation_type"] for item in activation.relation_candidates
    }
    assert {
        item["relation_type"]: item["strength"]
        for item in activation.relation_candidates
    }["noise-01"] == 0.01
