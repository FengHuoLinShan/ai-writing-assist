"""Writing adapter for the project workspace stats provider (AO-4)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.writing.project_ports import WritingWorkspaceStatsAdapter


def _contract(novel_id: str, *, chapters: int = 0, words: int = 0):
    return SimpleNamespace(
        novel_id=novel_id,
        chapter_count=chapters,
        word_count=words,
    )


@pytest.mark.asyncio
async def test_stats_adapter_projects_writing_contracts(monkeypatch) -> None:
    db = SimpleNamespace()
    get_stats = AsyncMock(return_value=_contract("novel-1", chapters=3, words=120))
    list_stats = AsyncMock(
        return_value={
            "novel-1": _contract("novel-1", chapters=3, words=120),
            "novel-2": _contract("novel-2"),
        }
    )
    list_indices = AsyncMock(return_value=[1, 2])
    list_drafts = AsyncMock(
        return_value=[
            SimpleNamespace(
                chapter_index=2,
                title="第二章",
                status="draft",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        ]
    )
    attention = AsyncMock(
        return_value=[
            SimpleNamespace(
                key="check-1",
                title="重新检查",
                summary="正文已更新",
                author_action="needs_decision",
                severity="medium",
                item_id="check-1",
                chapter_index=2,
                scene_id=None,
                updated_at=None,
            )
        ]
    )
    monkeypatch.setattr(
        "modules.writing.facade.get_project_writing_stats", get_stats
    )
    monkeypatch.setattr(
        "modules.writing.facade.list_project_writing_stats", list_stats
    )
    monkeypatch.setattr("modules.writing.facade.list_chapter_indices", list_indices)
    monkeypatch.setattr(
        "modules.writing.facade.list_latest_drafts_for_chapters", list_drafts
    )
    monkeypatch.setattr("modules.writing.facade.get_author_attention_items", attention)
    adapter = WritingWorkspaceStatsAdapter()

    stats = await adapter.get_project_stats(db, "novel-1")
    batch = await adapter.list_project_stats(db, ["novel-1", "novel-2"])
    indices = await adapter.list_chapter_indices(db, "novel-1")
    drafts = await adapter.list_latest_drafts(db, "novel-1", [1, 2], content_limit=1)
    items = await adapter.get_attention_items(db, "novel-1")

    assert (stats.novel_id, stats.chapter_count, stats.word_count) == (
        "novel-1",
        3,
        120,
    )
    assert set(batch) == {"novel-1", "novel-2"}
    assert batch["novel-2"].chapter_count == 0
    assert indices == [1, 2]
    assert [draft.chapter_index for draft in drafts] == [2]
    assert drafts[0].title == "第二章"
    assert drafts[0].status == "draft"
    assert [item.key for item in items] == ["check-1"]
    assert items[0].author_action == "needs_decision"
    assert items[0].source_kind is None
    get_stats.assert_awaited_once_with(db, "novel-1")
    list_drafts.assert_awaited_once_with(db, "novel-1", [1, 2], content_limit=1)


@pytest.mark.asyncio
async def test_stats_adapter_empty_project_states(monkeypatch) -> None:
    db = SimpleNamespace()
    monkeypatch.setattr(
        "modules.writing.facade.get_project_writing_stats",
        AsyncMock(return_value=_contract("empty-1")),
    )
    monkeypatch.setattr(
        "modules.writing.facade.list_project_writing_stats",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "modules.writing.facade.list_chapter_indices", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "modules.writing.facade.list_latest_drafts_for_chapters",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "modules.writing.facade.get_author_attention_items", AsyncMock(return_value=[])
    )
    adapter = WritingWorkspaceStatsAdapter()

    stats = await adapter.get_project_stats(db, "empty-1")
    drafts = await adapter.list_latest_drafts(db, "empty-1", [])

    assert stats.chapter_count == 0
    assert stats.word_count == 0
    assert drafts == []
