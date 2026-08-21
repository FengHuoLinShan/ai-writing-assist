"""World author-attention summary projection tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.world.services.attention_summary_service import (
    WorldAttentionSummaryService,
)


@pytest.mark.asyncio
async def test_attention_summary_uses_review_queues_for_one_novel() -> None:
    db = SimpleNamespace()
    entity_service = SimpleNamespace(
        list=AsyncMock(return_value=SimpleNamespace(total=2))
    )
    alias_service = SimpleNamespace(
        list_review_groups=AsyncMock(return_value=SimpleNamespace(item_total=3))
    )
    relation_service = SimpleNamespace(
        list_review_groups=AsyncMock(return_value=SimpleNamespace(item_total=4))
    )
    conflict_service = SimpleNamespace(list=AsyncMock(return_value=([], 0)))
    suggestion_service = SimpleNamespace(list=AsyncMock(return_value=([], 0)))
    service = WorldAttentionSummaryService(
        entity_service=entity_service,
        alias_service=alias_service,
        relation_service=relation_service,
        conflict_service=conflict_service,
        suggestion_service=suggestion_service,
    )

    result = await service.get_summary(db, "novel-1")

    assert result.novel_id == "novel-1"
    assert result.total == 9
    entity_service.list.assert_awaited_once_with(
        db,
        "novel-1",
        display_state="review",
        skip=0,
        limit=50,
    )
    alias_service.list_review_groups.assert_awaited_once_with(
        db, "novel-1", skip=0, limit=50
    )
    relation_service.list_review_groups.assert_awaited_once_with(
        db, "novel-1", skip=0, limit=50
    )


@pytest.mark.asyncio
async def test_attention_summary_projects_actionable_world_items_without_duplicates() -> (
    None
):
    db = SimpleNamespace()
    entity_service = SimpleNamespace(
        list=AsyncMock(
            return_value=SimpleNamespace(
                total=1,
                items=[
                    SimpleNamespace(
                        id="entity-1",
                        name="灰塔",
                        content_json={
                            "_meta": {
                                "scene_id": "scene-1",
                                "source_chapter_index": 3,
                            }
                        },
                        updated_at=None,
                    )
                ],
            )
        )
    )
    alias_service = SimpleNamespace(
        list_review_groups=AsyncMock(
            return_value=SimpleNamespace(
                groups=[
                    SimpleNamespace(
                        group_id="alias-group-1",
                        entity_name="灰塔",
                        member_count=1,
                        members=[
                            SimpleNamespace(
                                scene_id="scene-alias",
                                source_chapter_index=5,
                                updated_at=None,
                            )
                        ],
                    )
                ],
                group_total=1,
                item_total=1,
            )
        )
    )
    relation_service = SimpleNamespace(
        list_review_groups=AsyncMock(
            return_value=SimpleNamespace(groups=[], group_total=0, item_total=0)
        )
    )
    conflict_service = SimpleNamespace(
        list=AsyncMock(
            return_value=(
                [
                    SimpleNamespace(
                        id="conflict-1",
                        target={"page_id": "page-1"},
                        resolution_json={"author_action": "needs_decision"},
                        severity="high",
                        summary="两条设定互相矛盾",
                        updated_at=None,
                    )
                ],
                1,
            )
        )
    )
    suggestion_service = SimpleNamespace(
        list=AsyncMock(
            return_value=(
                [
                    SimpleNamespace(
                        id="checkpoint",
                        target_type="world_core_checkpoint",
                        status="pending",
                        result_ref_json={},
                    ),
                    SimpleNamespace(
                        id="design-checkpoint",
                        target_type="world_design_checkpoint",
                        status="pending",
                        result_ref_json={},
                    ),
                    SimpleNamespace(
                        id="shadowed",
                        target_type="core_entity_draft",
                        status="pending",
                        result_ref_json={"type": "core_entity_compatibility"},
                    ),
                    SimpleNamespace(
                        id="page-suggestion",
                        target_type="world_bible_page",
                        status="pending",
                        result_ref_json={},
                        payload_json={
                            "page": {"title": "北境"},
                            "source_chapter_index": 3,
                        },
                        risk_level="low",
                        updated_at=None,
                    ),
                    SimpleNamespace(
                        id="adoption-package",
                        target_type="world_adoption_package",
                        status="pending",
                        result_ref_json={},
                        payload_json={},
                        risk_level="medium",
                        updated_at=None,
                    ),
                    SimpleNamespace(
                        id="worldbook-import",
                        target_type="worldbook_import",
                        status="pending",
                        result_ref_json={},
                        payload_json={"counts": {"conflict": 1}},
                        risk_level="high",
                        updated_at=None,
                    ),
                ],
                6,
            )
        )
    )
    service = WorldAttentionSummaryService(
        entity_service=entity_service,
        alias_service=alias_service,
        relation_service=relation_service,
        conflict_service=conflict_service,
        suggestion_service=suggestion_service,
    )

    result = await service.get_summary(db, "novel-1")

    assert result.world_objects == 1
    assert [item.key for item in result.items] == [
        "world:conflict:conflict-1",
        "world:object:entity-1",
        "world:alias:alias-group-1",
        "world:suggestion:page-suggestion",
        "world:suggestion:adoption-package",
        "world:suggestion:worldbook-import",
    ]
    assert result.items[0].page_id == "page-1"
    assert result.items[1].scene_id == "scene-1"
    assert result.items[2].scene_id == "scene-alias"
    assert result.items[2].chapter_index == 5
    assert result.items[3].chapter_index == 3
    assert result.items[3].title == "确认待采用建议：北境"
    assert result.items[4].title == "确认待采用建议：世界设定采用包"
    assert result.items[5].title == "确认待采用建议：世界书目录导入"
    assert result.items[5].target_kind == "worldbook_import"
    assert result.items[4].target_kind == "world_adoption"
    conflict_service.list.assert_awaited_once_with(db, "novel-1", status="pending")
