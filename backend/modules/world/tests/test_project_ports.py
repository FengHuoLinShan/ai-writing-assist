"""World adapters for the project workspace stats and dedup ports (AO-4)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.world.project_ports import WorldDedupAdapter, WorldWorkspaceStatsAdapter


def _summary(novel_id: str, *, with_items: bool = False, **counts: int):
    items = (
        [
            SimpleNamespace(
                key="alias-1",
                source_kind="world_alias_review",
                title="别名待复核",
                summary="两条别名指向同一对象",
                author_action="needs_decision",
                severity="high",
                target_kind="world_alias",
                item_id="alias-1",
                chapter_index=None,
                scene_id=None,
                page_id=None,
                suggestion_id=None,
                updated_at=datetime(2026, 1, 1),
            )
        ]
        if with_items
        else []
    )
    return SimpleNamespace(
        novel_id=novel_id,
        world_objects=counts.get("world_objects", 2),
        world_aliases=counts.get("world_aliases", 3),
        world_relations=counts.get("world_relations", 4),
        items=items,
    )


@pytest.mark.asyncio
async def test_workspace_adapter_projects_attention_summary(monkeypatch) -> None:
    db = SimpleNamespace()
    get_summary = AsyncMock(return_value=_summary("novel-1", with_items=True))
    monkeypatch.setattr("modules.world.facade.get_author_attention_summary", get_summary)
    adapter = WorldWorkspaceStatsAdapter()

    summary = await adapter.get_attention_summary(db, "novel-1")

    assert summary.novel_id == "novel-1"
    assert summary.total == 9
    assert summary.world_objects == 2
    assert [item.key for item in summary.items] == ["alias-1"]
    assert summary.items[0].source_kind == "world_alias_review"
    assert summary.items[0].scene_ids == ()
    get_summary.assert_awaited_once_with(db, "novel-1")


@pytest.mark.asyncio
async def test_workspace_adapter_empty_state(monkeypatch) -> None:
    monkeypatch.setattr(
        "modules.world.facade.get_author_attention_summary",
        AsyncMock(
            return_value=_summary(
                "empty-1",
                world_objects=0,
                world_aliases=0,
                world_relations=0,
            )
        ),
    )

    summary = await WorldWorkspaceStatsAdapter().get_attention_summary(
        SimpleNamespace(), "empty-1"
    )

    assert summary.total == 0
    assert summary.items == ()


@pytest.mark.asyncio
async def test_dedup_adapter_delegates_with_same_kwargs(monkeypatch) -> None:
    db = SimpleNamespace()
    suggest = AsyncMock(return_value={"suggestions": []})
    apply_group = AsyncMock(return_value=[{"action": "merge"}])
    apply = AsyncMock(return_value={"applied": 1})
    monkeypatch.setattr("modules.world.facade.suggest_entity_fusion", suggest)
    monkeypatch.setattr("modules.world.facade.apply_entity_fusion_group", apply_group)
    monkeypatch.setattr("modules.world.facade.apply_entity_fusion", apply)
    adapter = WorldDedupAdapter()

    scanned = await adapter.suggest_entity_fusion(
        db,
        "novel-1",
        limit=100,
        max_suggestions=12,
        group_before_budget=False,
        progress_callback=None,
        exclusions=[],
        llm_client=None,
    )
    grouped = await adapter.apply_entity_fusion_group(
        db,
        "novel-1",
        primary_entity_id="e1",
        operations=[{"source_entity_id": "e2"}],
        validate_only=True,
        execution_fingerprints_prevalidated=False,
    )
    applied = await adapter.apply_entity_fusion(
        db,
        "novel-1",
        confirmed=True,
        suggestions=[{"action": "merge"}],
    )

    assert scanned == {"suggestions": []}
    assert grouped == [{"action": "merge"}]
    assert applied == {"applied": 1}
    suggest.assert_awaited_once_with(
        db,
        "novel-1",
        limit=100,
        max_suggestions=12,
        progress_callback=None,
        exclusions=[],
        llm_client=None,
        group_before_budget=False,
    )
    apply_group.assert_awaited_once_with(
        db,
        "novel-1",
        primary_entity_id="e1",
        operations=[{"source_entity_id": "e2"}],
        validate_only=True,
        execution_fingerprints_prevalidated=False,
    )
    apply.assert_awaited_once_with(
        db,
        "novel-1",
        confirmed=True,
        suggestions=[{"action": "merge"}],
    )
