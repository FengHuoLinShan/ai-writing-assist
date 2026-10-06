"""Story adapters for the project workspace stats and dedup ports (AO-4)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.story.project_ports import StoryDedupAdapter, StoryWorkspaceStatsAdapter


def _attention_item(key: str, *, scene_ids: tuple[str, ...] = ()):
    return SimpleNamespace(
        key=key,
        source_kind="outline_scene_health",
        title=key,
        summary="待处理",
        author_action="can_improve",
        severity="low",
        target_kind="outline_scene",
        item_id=key,
        chapter_index=None,
        scene_id=key,
        scene_ids=scene_ids,
        suggestion_id=None,
        updated_at=datetime(2026, 1, 1),
    )


@pytest.mark.asyncio
async def test_workspace_adapter_projects_scene_stats(monkeypatch) -> None:
    db = SimpleNamespace()
    count = AsyncMock(return_value=6)
    attention = AsyncMock(
        return_value=[_attention_item("scene-1", scene_ids=("scene-1", "scene-2"))]
    )
    scene = SimpleNamespace(
        id="scene-1",
        chapter_ids=[1, "3"],
        scene_chunks=[{"chapter_index": 4}, {"chapter_id": "5"}, {"other": None}],
    )
    get_scene = AsyncMock(return_value=scene)
    monkeypatch.setattr("modules.story.facade.count_scenes_by_novel", count)
    monkeypatch.setattr("modules.story.facade.get_author_attention_items", attention)
    monkeypatch.setattr("modules.story.facade.get_scene_contract", get_scene)
    adapter = StoryWorkspaceStatsAdapter()

    scenes = await adapter.count_scenes(
        db,
        "novel-1",
        status_filter=["candidate", "proposal"],
    )
    items = await adapter.get_attention_items(db, "novel-1")
    focus = await adapter.get_scene_focus(db, "novel-1", "scene-1")

    assert scenes == 6
    count.assert_awaited_once_with(
        db,
        "novel-1",
        status_filter=["candidate", "proposal"],
    )
    assert [item.key for item in items] == ["scene-1"]
    assert items[0].scene_ids == ("scene-1", "scene-2")
    assert focus is not None
    assert focus.id == "scene-1"
    assert focus.chapter_indices == (1, 3, 4, 5)
    get_scene.assert_awaited_once_with(db, "novel-1", "scene-1")


@pytest.mark.asyncio
async def test_workspace_adapter_empty_and_missing_states(monkeypatch) -> None:
    monkeypatch.setattr(
        "modules.story.facade.count_scenes_by_novel", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        "modules.story.facade.get_author_attention_items", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "modules.story.facade.get_scene_contract", AsyncMock(return_value=None)
    )
    adapter = StoryWorkspaceStatsAdapter()
    db = SimpleNamespace()

    assert await adapter.count_scenes(db, "empty-1") == 0
    assert await adapter.get_attention_items(db, "empty-1") == ()
    assert await adapter.get_scene_focus(db, "empty-1", "missing") is None


@pytest.mark.asyncio
async def test_dedup_adapter_delegates_with_same_kwargs(monkeypatch) -> None:
    db = SimpleNamespace()
    suggest = AsyncMock(return_value={"suggestions": []})
    apply_group = AsyncMock(return_value=[{"action": "ai_fusion"}])
    apply = AsyncMock(return_value={"applied": 2})
    monkeypatch.setattr("modules.story.facade.suggest_structure_dedup", suggest)
    monkeypatch.setattr("modules.story.facade.apply_structure_dedup_group", apply_group)
    monkeypatch.setattr("modules.story.facade.apply_structure_dedup", apply)
    adapter = StoryDedupAdapter()

    scanned = await adapter.suggest_structure_dedup(
        db,
        "novel-1",
        asset_types=["scene"],
        limit=100,
        max_suggestions=12,
        progress_callback=None,
        exclusions=[],
        llm_client=None,
    )
    grouped = await adapter.apply_structure_dedup_group(
        db,
        "novel-1",
        asset_type="scene",
        primary_asset_id="s1",
        operations=[{"source_asset_id": "s2"}],
        validate_only=True,
        execution_fingerprints_prevalidated=False,
    )
    applied = await adapter.apply_structure_dedup(
        db,
        "novel-1",
        confirmed=True,
        suggestions=[{"asset_type": "scene"}],
    )

    assert scanned == {"suggestions": []}
    assert grouped == [{"action": "ai_fusion"}]
    assert applied == {"applied": 2}
    suggest.assert_awaited_once_with(
        db,
        "novel-1",
        asset_types=["scene"],
        limit=100,
        max_suggestions=12,
        progress_callback=None,
        exclusions=[],
        llm_client=None,
    )
    apply_group.assert_awaited_once_with(
        db,
        "novel-1",
        asset_type="scene",
        primary_asset_id="s1",
        operations=[{"source_asset_id": "s2"}],
        validate_only=True,
        execution_fingerprints_prevalidated=False,
    )
    apply.assert_awaited_once_with(
        db,
        "novel-1",
        confirmed=True,
        suggestions=[{"asset_type": "scene"}],
    )
