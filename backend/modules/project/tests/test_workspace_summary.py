"""Project author-workspace summary behavior and isolation."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
            map_items=5,
        )
    )
    outline_attention_reader = AsyncMock(return_value=6)
    service = ProjectWorkspaceSummaryService(
        project_reader=project_reader,
        writing_stats_reader=writing_stats_reader,
        chapter_index_reader=chapter_index_reader,
        latest_drafts_reader=latest_drafts_reader,
        world_attention_reader=world_attention_reader,
        outline_attention_reader=outline_attention_reader,
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
        "map_items": 5,
        "total": 20,
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
    )

    result = await service.get_summary(db, "empty-1")

    assert result.continuation is None
    assert result.attention.total == 0
    latest_drafts_reader.assert_not_awaited()
