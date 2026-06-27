from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from modules.outline.schemas import (
    OutlineArcCreate,
    PlotThreadCreate,
    PlotThreadUpdate,
)
from modules.outline.services import (
    OutlineArcService,
    PlotThreadService,
)


def _make_thread(
    *,
    thread_id: str | None = None,
    novel_id: str | None = None,
    name: str = "线",
    thread_type: str = "main",
    **overrides: object,
) -> MagicMock:
    thread = MagicMock()
    thread.id = uuid.UUID(thread_id) if thread_id else uuid.uuid4()
    thread.novel_id = uuid.UUID(novel_id) if novel_id else uuid.uuid4()
    thread.name = name
    thread.thread_type = thread_type
    thread.summary = None
    thread.visible_goal = None
    thread.hidden_truth = None
    thread.start_chapter = None
    thread.planned_payoff_chapter = None
    thread.current_stage = None
    thread.related_character_ids = []
    thread.related_entity_ids = []
    thread.related_memory_ids = []
    thread.reader_known_state = None
    thread.author_known_state = None
    thread.status = "draft"
    thread.created_at = datetime.now(UTC)
    thread.updated_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(thread, key, value)
    return thread


def _make_arc(
    *,
    arc_id: str | None = None,
    novel_id: str | None = None,
    title: str = "卷",
    **overrides: object,
) -> MagicMock:
    arc = MagicMock()
    arc.id = uuid.UUID(arc_id) if arc_id else uuid.uuid4()
    arc.novel_id = uuid.UUID(novel_id) if novel_id else uuid.uuid4()
    arc.title = title
    arc.arc_index = None
    arc.start_chapter = None
    arc.end_chapter = None
    arc.arc_goal = None
    arc.core_conflict = None
    arc.main_opposition = None
    arc.entry_hook = None
    arc.midpoint_turn = None
    arc.climax = None
    arc.result = None
    arc.next_hook = None
    arc.related_thread_ids = []
    arc.related_character_ids = []
    arc.related_entity_ids = []
    arc.status = "draft"
    arc.created_at = datetime.now(UTC)
    arc.updated_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(arc, key, value)
    return arc


class TestPlotThreadService:
    """T2: Service 层 — PlotThread（repo 用 AsyncMock 替换）"""

    @pytest.mark.asyncio
    async def test_create_returns_response(
        self,
        sample_novel_id: str,
        thread_data: PlotThreadCreate,
    ) -> None:
        thread = _make_thread(novel_id=sample_novel_id, name="主角成长之路")
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.create = AsyncMock(return_value=thread)
        db = MagicMock()

        result = await svc.create(db, sample_novel_id, thread_data)

        assert result.id == str(thread.id)
        assert result.name == "主角成长之路"
        assert result.thread_type == "main"
        assert isinstance(result.id, str)
        svc.repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_returns_paginated(
        self,
        sample_novel_id: str,
    ) -> None:
        threads = [
            _make_thread(novel_id=sample_novel_id, name=f"线{i}", thread_type="secondary")
            for i in range(3)
        ]
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get_by_novel = AsyncMock(return_value=(threads, 3))
        db = MagicMock()

        items, total = await svc.list(db, sample_novel_id)

        assert total == 3
        assert len(items) == 3
        assert all(isinstance(item.id, str) for item in items)

    @pytest.mark.parametrize(
        "operation",
        ["get", "delete"],
        ids=["get", "delete"],
    )
    @pytest.mark.asyncio
    async def test_plot_thread_wrong_novel_raises_404(
        self,
        sample_novel_id: str,
        other_novel_id: str,
        operation: str,
    ) -> None:
        thread = _make_thread(novel_id=sample_novel_id)
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=thread)
        svc.repo.delete = AsyncMock(return_value=True)
        db = MagicMock()

        with pytest.raises(HTTPException) as exc:
            if operation == "get":
                await svc.get(db, str(thread.id), novel_id=other_novel_id)
            else:
                await svc.delete(db, str(thread.id), novel_id=other_novel_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_returns_on_correct_novel(
        self,
        sample_novel_id: str,
    ) -> None:
        thread = _make_thread(novel_id=sample_novel_id, name="查询测试")
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=thread)
        db = MagicMock()

        got = await svc.get(db, str(thread.id), novel_id=sample_novel_id)

        assert got is not None
        assert got.name == "查询测试"

    @pytest.mark.asyncio
    async def test_update_partial(
        self,
        sample_novel_id: str,
    ) -> None:
        thread = _make_thread(
            novel_id=sample_novel_id,
            name="原名称",
            thread_type="main",
            current_stage="初期",
        )
        updated = _make_thread(
            id=str(thread.id),
            novel_id=sample_novel_id,
            name="新名称",
            thread_type="main",
            current_stage="初期",
        )
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=thread)
        svc.repo.update = AsyncMock(return_value=updated)
        db = MagicMock()

        result = await svc.update(
            db,
            str(thread.id),
            PlotThreadUpdate(name="新名称"),
            novel_id=sample_novel_id,
        )

        assert result is not None
        assert result.name == "新名称"
        assert result.current_stage == "初期"

    @pytest.mark.asyncio
    async def test_delete_on_correct_novel(
        self,
        sample_novel_id: str,
    ) -> None:
        thread = _make_thread(novel_id=sample_novel_id, name="待删除")
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=thread)
        svc.repo.delete = AsyncMock(return_value=True)
        db = MagicMock()

        await svc.delete(db, str(thread.id), novel_id=sample_novel_id)

        svc.repo.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_active_contract(
        self,
        sample_novel_id: str,
    ) -> None:
        thread = _make_thread(
            novel_id=sample_novel_id,
            name="活跃线",
            thread_type="main",
            start_chapter=1,
            status="canonical",
        )
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get_active = AsyncMock(return_value=[thread])
        db = MagicMock()

        threads = await svc.get_active(db, sample_novel_id, chapter_index=5)

        assert len(threads) == 1
        assert threads[0].name == "活跃线"
        assert threads[0].thread_type == "main"


class TestOutlineArcService:
    """T2: Service 层 — OutlineArc（repo 用 AsyncMock 替换）"""

    @pytest.mark.asyncio
    async def test_create_and_get(
        self,
        sample_novel_id: str,
        arc_data: OutlineArcCreate,
    ) -> None:
        arc = _make_arc(novel_id=sample_novel_id, title="第一卷：启程")
        svc = OutlineArcService()
        svc.repo = MagicMock()
        svc.repo.create = AsyncMock(return_value=arc)
        svc.repo.get = AsyncMock(return_value=arc)
        db = MagicMock()

        created = await svc.create(db, sample_novel_id, arc_data)
        assert created.id == str(arc.id)
        assert created.title == "第一卷：启程"

        fetched = await svc.get(db, str(arc.id), novel_id=sample_novel_id)
        assert fetched is not None
        assert fetched.title == "第一卷：启程"

    @pytest.mark.asyncio
    async def test_get_by_chapter(
        self,
        sample_novel_id: str,
    ) -> None:
        arc = _make_arc(
            novel_id=sample_novel_id,
            title="卷一",
            start_chapter=1,
            end_chapter=5,
        )
        svc = OutlineArcService()
        svc.repo = MagicMock()
        svc.repo.get_by_chapter = AsyncMock(return_value=arc)
        db = MagicMock()

        result = await svc.get_by_chapter(db, sample_novel_id, chapter_index=3)

        assert result is not None
        assert result.title == "卷一"

    @pytest.mark.asyncio
    async def test_get_by_chapter_none(
        self,
        sample_novel_id: str,
    ) -> None:
        svc = OutlineArcService()
        svc.repo = MagicMock()
        svc.repo.get_by_chapter = AsyncMock(return_value=None)
        db = MagicMock()

        arc = await svc.get_by_chapter(db, sample_novel_id, chapter_index=99)

        assert arc is None

    @pytest.mark.asyncio
    async def test_novel_id_isolation(
        self,
        sample_novel_id: str,
        other_novel_id: str,
    ) -> None:
        arc = _make_arc(novel_id=sample_novel_id, title="仅A可见")
        svc = OutlineArcService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=arc)
        db = MagicMock()

        # wrong novel_id should raise 404
        with pytest.raises(HTTPException) as exc:
            await svc.get(db, str(arc.id), novel_id=other_novel_id)
        assert exc.value.status_code == 404
        # correct novel_id returns the arc
        got = await svc.get(db, str(arc.id), novel_id=sample_novel_id)
        assert got is not None
        assert got.title == "仅A可见"
