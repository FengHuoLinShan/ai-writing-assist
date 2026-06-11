from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.schemas import (
    OutlineArcCreate,
    PlotThreadCreate,
    PlotThreadUpdate,
)
from modules.outline.services import (
    OutlineArcService,
    PlotThreadService,
)


class TestPlotThreadService:
    """T2: Service 层 — PlotThread"""

    @pytest.mark.asyncio
    async def test_create_returns_response(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        thread_data: PlotThreadCreate,
    ) -> None:
        svc = PlotThreadService()
        result = await svc.create(db_session, sample_novel_id, thread_data)
        assert result.id is not None
        assert result.name == "主角成长之路"
        assert result.thread_type == "main"
        assert isinstance(result.id, str)

    @pytest.mark.asyncio
    async def test_list_returns_paginated(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        svc = PlotThreadService()
        for i in range(3):
            await svc.create(
                db_session,
                sample_novel_id,
                PlotThreadCreate(
                    name=f"线{i}",
                    thread_type="secondary",
                ),
            )
        items, total = await svc.list(db_session, sample_novel_id)
        assert total >= 3
        assert len(items) >= 3
        assert all(isinstance(item.id, str) for item in items)

    @pytest.mark.asyncio
    async def test_get_raises_on_wrong_novel(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        other_novel_id: str,
    ) -> None:
        svc = PlotThreadService()
        created = await svc.create(
            db_session,
            sample_novel_id,
            PlotThreadCreate(
                name="隔离测试",
                thread_type="main",
            ),
        )
        with pytest.raises(HTTPException) as exc:
            await svc.get(db_session, created.id, novel_id=other_novel_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_returns_on_correct_novel(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        svc = PlotThreadService()
        created = await svc.create(
            db_session,
            sample_novel_id,
            PlotThreadCreate(
                name="查询测试",
                thread_type="main",
            ),
        )
        got = await svc.get(db_session, created.id, novel_id=sample_novel_id)
        assert got is not None
        assert got.name == "查询测试"

    @pytest.mark.asyncio
    async def test_update_partial(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        svc = PlotThreadService()
        created = await svc.create(
            db_session,
            sample_novel_id,
            PlotThreadCreate(
                name="原名称",
                thread_type="main",
                current_stage="初期",
            ),
        )
        updated = await svc.update(
            db_session,
            created.id,
            PlotThreadUpdate(name="新名称"),
            novel_id=sample_novel_id,
        )
        assert updated is not None
        assert updated.name == "新名称"
        assert updated.current_stage == "初期"

    @pytest.mark.asyncio
    async def test_delete_raises_on_wrong_novel(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        other_novel_id: str,
    ) -> None:
        svc = PlotThreadService()
        created = await svc.create(
            db_session,
            sample_novel_id,
            PlotThreadCreate(
                name="隔离删除",
                thread_type="main",
            ),
        )
        with pytest.raises(HTTPException) as exc:
            await svc.delete(db_session, created.id, novel_id=other_novel_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_on_correct_novel(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        svc = PlotThreadService()
        created = await svc.create(
            db_session,
            sample_novel_id,
            PlotThreadCreate(
                name="待删除",
                thread_type="main",
            ),
        )
        await svc.delete(db_session, created.id, novel_id=sample_novel_id)
        # get after delete should raise 404
        with pytest.raises(HTTPException) as exc:
            await svc.get(db_session, created.id, novel_id=sample_novel_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_active_contract(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        svc = PlotThreadService()
        await svc.create(
            db_session,
            sample_novel_id,
            PlotThreadCreate(
                name="活跃线",
                thread_type="main",
                start_chapter=1,
                status="canonical",
            ),
        )
        threads = await svc.get_active(db_session, sample_novel_id, chapter_index=5)
        assert len(threads) >= 1
        assert threads[0].name == "活跃线"
        assert threads[0].thread_type == "main"


class TestOutlineArcService:
    """T2: Service 层 — OutlineArc"""

    @pytest.mark.asyncio
    async def test_create_and_get(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        arc_data: OutlineArcCreate,
    ) -> None:
        svc = OutlineArcService()
        created = await svc.create(db_session, sample_novel_id, arc_data)
        assert created.id is not None
        assert created.title == "第一卷：启程"

        fetched = await svc.get(db_session, created.id, novel_id=sample_novel_id)
        assert fetched is not None
        assert fetched.title == "第一卷：启程"

    @pytest.mark.asyncio
    async def test_get_by_chapter(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        svc = OutlineArcService()
        await svc.create(
            db_session,
            sample_novel_id,
            OutlineArcCreate(
                title="卷一",
                start_chapter=1,
                end_chapter=5,
            ),
        )
        await svc.create(
            db_session,
            sample_novel_id,
            OutlineArcCreate(
                title="卷二",
                start_chapter=6,
                end_chapter=10,
            ),
        )

        arc = await svc.get_by_chapter(db_session, sample_novel_id, chapter_index=3)
        assert arc is not None
        assert arc.title == "卷一"

    @pytest.mark.asyncio
    async def test_get_by_chapter_none(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        svc = OutlineArcService()
        arc = await svc.get_by_chapter(db_session, sample_novel_id, chapter_index=99)
        assert arc is None

    @pytest.mark.asyncio
    async def test_novel_id_isolation(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        other_novel_id: str,
    ) -> None:
        svc = OutlineArcService()
        created = await svc.create(
            db_session,
            sample_novel_id,
            OutlineArcCreate(
                title="仅A可见",
                start_chapter=1,
                end_chapter=10,
            ),
        )
        # wrong novel_id should raise 404
        with pytest.raises(HTTPException) as exc:
            await svc.get(db_session, created.id, novel_id=other_novel_id)
        assert exc.value.status_code == 404
        # correct novel_id returns the arc
        got = await svc.get(db_session, created.id, novel_id=sample_novel_id)
        assert got is not None
        assert got.title == "仅A可见"
