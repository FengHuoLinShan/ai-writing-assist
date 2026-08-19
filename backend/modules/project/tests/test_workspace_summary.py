"""Project author-workspace summary behavior and isolation."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.errors import ValidationError
from modules.project.schemas import ProjectResponse
from modules.project.workspace_service import ProjectWorkspaceSummaryService
from modules.world.contracts import WorldAttentionSummaryContract
from modules.writing.contracts import (
    WritingDraftContract,
    WritingProjectStatsContract,
)


@pytest.mark.asyncio
async def test_workspace_summary_composes_safe_author_projection() -> None:
    db = SimpleNamespace()
    project_reader = AsyncMock(return_value=ProjectResponse(id="novel-1", title="长夜"))
    writing_stats_reader = AsyncMock(
        return_value=WritingProjectStatsContract(
            novel_id="novel-1",
            chapter_count=3,
            word_count=12800,
        )
    )
    chapter_index_reader = AsyncMock(return_value=[1, 2, 3])
    latest_drafts_reader = AsyncMock(
        return_value=[
            WritingDraftContract(
                novel_id="novel-1",
                chapter_index=3,
                title="旧章节",
                status="published",
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            WritingDraftContract(
                novel_id="novel-1",
                chapter_index=2,
                title="最近编辑",
                status="draft",
                updated_at=datetime(2026, 1, 3, tzinfo=UTC),
            ),
        ]
    )
    world_attention_reader = AsyncMock(
        return_value=WorldAttentionSummaryContract(
            novel_id="novel-1",
            world_objects=2,
            world_aliases=3,
            world_relations=4,
        )
    )
    outline_attention_reader = AsyncMock(return_value=6)
    outline_item_reader = AsyncMock(return_value=[])
    service = ProjectWorkspaceSummaryService(
        project_reader=project_reader,
        writing_stats_reader=writing_stats_reader,
        chapter_index_reader=chapter_index_reader,
        latest_drafts_reader=latest_drafts_reader,
        world_attention_reader=world_attention_reader,
        outline_attention_reader=outline_attention_reader,
        outline_item_reader=outline_item_reader,
        writing_attention_reader=AsyncMock(return_value=[]),
    )

    result = await service.get_summary(db, "novel-1")

    assert result.project_id == "novel-1"
    assert result.continuation is not None
    assert result.continuation.chapter_index == 2
    assert result.continuation.title == "最近编辑"
    assert result.continuation.has_unpublished_changes is True
    assert result.writing.model_dump() == {"chapter_count": 3, "word_count": 12800}
    assert result.attention.model_dump() == {
        "world_objects": 2,
        "world_aliases": 3,
        "world_relations": 4,
        "outline_scenes": 6,
        "total": 15,
        "items": [],
        "actionable_total": 0,
        "has_more": False,
        "more_targets": [],
    }
    project_reader.assert_awaited_once_with(db, "novel-1")
    latest_drafts_reader.assert_awaited_once_with(
        db,
        "novel-1",
        [1, 2, 3],
        content_limit=1,
    )
    outline_attention_reader.assert_awaited_once_with(
        db,
        "novel-1",
        status_filter=["candidate", "proposal"],
    )


@pytest.mark.asyncio
async def test_workspace_summary_skips_draft_load_for_empty_project() -> None:
    db = SimpleNamespace()
    latest_drafts_reader = AsyncMock(return_value=[])
    service = ProjectWorkspaceSummaryService(
        project_reader=AsyncMock(
            return_value=ProjectResponse(id="empty-1", title="空白作品")
        ),
        writing_stats_reader=AsyncMock(
            return_value=WritingProjectStatsContract(novel_id="empty-1")
        ),
        chapter_index_reader=AsyncMock(return_value=[]),
        latest_drafts_reader=latest_drafts_reader,
        world_attention_reader=AsyncMock(
            return_value=WorldAttentionSummaryContract(novel_id="empty-1")
        ),
        outline_attention_reader=AsyncMock(return_value=0),
        outline_item_reader=AsyncMock(return_value=[]),
        writing_attention_reader=AsyncMock(return_value=[]),
    )

    result = await service.get_summary(db, "empty-1")

    assert result.continuation is None
    assert result.attention.total == 0
    latest_drafts_reader.assert_not_awaited()


@pytest.mark.asyncio
async def test_workspace_summary_validates_focus_and_sorts_actionable_items() -> None:
    db = SimpleNamespace()

    def item(
        key: str,
        *,
        action: str = "can_improve",
        severity: str = "low",
        chapter_index: int | None = None,
        scene_id: str | None = None,
        scene_ids: tuple[str, ...] = (),
        updated_at: datetime | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            key=key,
            source_kind="outline_scene_health",
            title=key,
            summary="待处理",
            author_action=action,
            severity=severity,
            target_kind="outline_scene",
            item_id=key,
            chapter_index=chapter_index,
            scene_id=scene_id,
            scene_ids=scene_ids,
            updated_at=updated_at,
        )

    scene_reader = AsyncMock(
        return_value=SimpleNamespace(
            id="scene-current",
            chapter_ids=[],
            scene_chunks=[{"chapter_index": 4}],
        )
    )
    service = ProjectWorkspaceSummaryService(
        project_reader=AsyncMock(
            return_value=ProjectResponse(id="novel-1", title="长夜")
        ),
        writing_stats_reader=AsyncMock(
            return_value=WritingProjectStatsContract(novel_id="novel-1")
        ),
        chapter_index_reader=AsyncMock(return_value=[]),
        latest_drafts_reader=AsyncMock(return_value=[]),
        world_attention_reader=AsyncMock(
            return_value=WorldAttentionSummaryContract(novel_id="novel-1")
        ),
        outline_attention_reader=AsyncMock(return_value=0),
        outline_item_reader=AsyncMock(
            return_value=[
                item("general", action="needs_decision", severity="high"),
                item("chapter", chapter_index=4, severity="high"),
                item(
                    "scene-low",
                    chapter_index=3,
                    scene_id="scene-primary",
                    scene_ids=("scene-primary", "scene-current"),
                ),
                item(
                    "scene-decision",
                    action="needs_decision",
                    chapter_index=4,
                    scene_id="scene-current",
                ),
                item("extra-1"),
                item("extra-2"),
                item("extra-3"),
            ]
        ),
        writing_attention_reader=AsyncMock(
            return_value=[
                SimpleNamespace(
                    key="writing",
                    title="重新检查第 4 章",
                    summary="正文已经更新。",
                    author_action="needs_decision",
                    severity="medium",
                    item_id="check-1",
                    chapter_index=None,
                    scene_id=None,
                    updated_at=None,
                )
            ]
        ),
        scene_reader=scene_reader,
    )

    result = await service.get_summary(
        db,
        "novel-1",
        focus_chapter_index=4,
        focus_scene_id="scene-current",
    )

    assert [entry.key for entry in result.attention.items[:4]] == [
        "scene-decision",
        "scene-low",
        "chapter",
        "general",
    ]
    assert result.attention.actionable_total == 8
    assert result.attention.has_more is True
    assert len(result.attention.items) == 6
    assert len(result.attention.more_targets) == 1
    assert result.attention.more_targets[0].target.kind == "outline_scene"
    assert result.attention.more_targets[0].target.item_id is None
    writing = next(entry for entry in result.attention.items if entry.key == "writing")
    assert writing.source_kind == "writing_conflict"
    assert writing.target.kind == "writing_conflict"
    scene_low = next(
        entry for entry in result.attention.items if entry.key == "scene-low"
    )
    assert scene_low.target.scene_id == "scene-current"
    assert scene_low.target.chapter_index == 4
    scene_reader.assert_awaited_once_with(db, "novel-1", "scene-current")

    scene_reader.return_value = SimpleNamespace(
        id="foreign-scene",
        chapter_ids=["9"],
    )
    invalid = await service.get_summary(
        db,
        "novel-1",
        focus_chapter_index=4,
        focus_scene_id="foreign-scene",
    )
    assert invalid.attention.items[0].relevance == "current_chapter"

    scene_reader.side_effect = ValidationError("invalid scene id")
    malformed = await service.get_summary(
        db,
        "novel-1",
        focus_chapter_index=4,
        focus_scene_id="not-a-uuid",
    )
    assert malformed.attention.items[0].relevance == "current_chapter"
