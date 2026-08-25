from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.outline_state.models import OutlineArc, PlotThread
from modules.story.outline_state.repositories import (
    OutlineArcRepository,
    PlotThreadRepository,
    SceneRepository,
)
from modules.story.outline_state.schemas import (
    OutlineArcCreate,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadUpdate,
    SceneCreate,
)


class TestPlotThreadRepository:
    """T1: Repository 层 — PlotThread"""

    async def _make(self, db: AsyncSession, nid: uuid.UUID, **kw) -> PlotThread:
        data = PlotThreadCreate(
            name=kw.get("name", "测试线程"),
            thread_type=kw.get("thread_type", "main"),
            start_chapter=kw.get("start_chapter"),
            planned_payoff_chapter=kw.get("planned_payoff_chapter"),
            current_stage=kw.get("current_stage"),
            status=kw.get("status", "draft"),
            **{
                k: v
                for k, v in kw.items()
                if k
                not in (
                    "name",
                    "thread_type",
                    "start_chapter",
                    "planned_payoff_chapter",
                    "current_stage",
                    "status",
                )
            },
        )
        return await PlotThreadRepository().create(db, nid, data)

    @pytest.mark.asyncio
    async def test_create_and_get(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        thread_data: PlotThreadCreate,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        repo = PlotThreadRepository()
        created = await repo.create(db_session, nid, thread_data)
        assert created.name == "主角成长之路"
        assert created.thread_type == "main"
        assert created.start_chapter == 1
        assert created.planned_payoff_chapter == 30
        assert created.status == "draft"

        fetched = await repo.get(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "主角成长之路"

    @pytest.mark.asyncio
    async def test_create_many(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        repo = PlotThreadRepository()

        created = await repo.create_many(
            db_session,
            nid,
            [
                PlotThreadCreate(name="批量线 1", thread_type="main"),
                PlotThreadCreate(name="批量线 2", thread_type="secondary"),
            ],
        )

        assert [item.name for item in created] == ["批量线 1", "批量线 2"]
        fetched = [await repo.get(db_session, item.id) for item in created]
        assert [item.name for item in fetched if item is not None] == [
            "批量线 1",
            "批量线 2",
        ]

    @pytest.mark.parametrize(
        "operation,expected",
        [
            ("get", None),
            ("update", None),
            ("delete", False),
        ],
        ids=["get", "update", "delete"],
    )
    @pytest.mark.asyncio
    async def test_not_found(
        self,
        db_session: AsyncSession,
        operation: str,
        expected: None | bool,
    ) -> None:
        repo = PlotThreadRepository()
        fake_id = uuid.uuid4()
        if operation == "get":
            result = await repo.get(db_session, fake_id)
        elif operation == "update":
            update = PlotThreadUpdate(name="不存在")
            result = await repo.update(db_session, fake_id, update)
        else:
            result = await repo.delete(db_session, fake_id)
        assert result is expected

    @pytest.mark.asyncio
    async def test_get_by_novel(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        for i in range(3):
            await self._make(db_session, nid, name=f"线{i}", thread_type="secondary")
        items, total = await PlotThreadRepository().get_by_novel(db_session, nid)
        assert total >= 3
        assert len(items) >= 3

    @pytest.mark.asyncio
    async def test_get_by_novel_pagination(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        for i in range(5):
            await self._make(db_session, nid, name=f"页{i}", thread_type="secondary")
        page1, total = await PlotThreadRepository().get_by_novel(
            db_session, nid, skip=0, limit=2
        )
        assert len(page1) == 2
        assert total >= 5

    @pytest.mark.asyncio
    async def test_novel_id_isolation(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        other_novel_id: str,
    ) -> None:
        nid_a = uuid.UUID(hex=sample_novel_id)
        nid_b = uuid.UUID(hex=other_novel_id)
        await self._make(db_session, nid_a, name="仅A可见")
        items_b, total_b = await PlotThreadRepository().get_by_novel(db_session, nid_b)
        assert total_b == 0
        assert items_b == []

    @pytest.mark.asyncio
    async def test_update(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        repo = PlotThreadRepository()
        created = await self._make(db_session, nid, name="原名称", current_stage="初期")
        update = PlotThreadUpdate(name="新名称", current_stage="中期")
        updated = await repo.update(db_session, created.id, update)
        assert updated is not None
        assert updated.name == "新名称"
        assert updated.current_stage == "中期"

    @pytest.mark.asyncio
    async def test_update_partial(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        repo = PlotThreadRepository()
        created = await self._make(db_session, nid, name="原名称", summary="原有概要")
        update = PlotThreadUpdate(name="新名称")
        updated = await repo.update(db_session, created.id, update)
        assert updated is not None
        assert updated.name == "新名称"
        assert updated.summary == "原有概要"

    @pytest.mark.asyncio
    async def test_update_reuses_loaded_thread(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = PlotThreadRepository()
        thread_id = uuid.uuid4()
        thread = type(
            "Thread",
            (),
            {
                "id": thread_id,
                "name": "旧线程",
                "current_stage": "初期",
                "related_entity_ids": [],
            },
        )()
        get_calls = 0

        async def fake_get(_db, requested_id):
            nonlocal get_calls
            get_calls += 1
            assert requested_id == thread_id
            return thread

        class Session:
            def __init__(self) -> None:
                self.added = []
                self.flush_count = 0

            def add(self, obj):
                self.added.append(obj)

            async def flush(self) -> None:
                self.flush_count += 1

        monkeypatch.setattr(repo, "get", fake_get)
        db = Session()

        updated = await repo.update(
            db,  # type: ignore[arg-type]
            thread_id,
            PlotThreadUpdate(
                name="新线程",
                current_stage="中期",
                related_entity_ids=["e1"],
            ),
        )

        assert updated is thread
        assert thread.name == "新线程"
        assert thread.current_stage == "中期"
        assert thread.related_entity_ids == ["e1"]
        assert get_calls == 1
        assert db.added == [thread]
        assert db.flush_count == 1

    @pytest.mark.asyncio
    async def test_delete(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        repo = PlotThreadRepository()
        created = await self._make(db_session, nid, name="待删除")
        deleted = await repo.delete(db_session, created.id)
        assert deleted is True
        assert await repo.get(db_session, created.id) is None

    @pytest.mark.asyncio
    async def test_get_active_filters_by_chapter(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        await self._make(
            db_session, nid, name="早期线", start_chapter=1, status="canonical"
        )
        await self._make(
            db_session, nid, name="后期线", start_chapter=10, status="canonical"
        )
        early = await PlotThreadRepository().get_active(db_session, nid, chapter_index=5)
        names = [t.name for t in early]
        assert "早期线" in names
        assert "后期线" not in names


class TestOutlineArcRepository:
    """T1: Repository 层 — OutlineArc"""

    async def _make(self, db: AsyncSession, nid: uuid.UUID, **kw) -> OutlineArc:
        data = OutlineArcCreate(
            title=kw.get("title", "测试篇章"),
            arc_index=kw.get("arc_index", 1),
            start_chapter=kw.get("start_chapter", 1),
            end_chapter=kw.get("end_chapter", 10),
            arc_goal=kw.get("arc_goal"),
            core_conflict=kw.get("core_conflict"),
            status=kw.get("status", "draft"),
        )
        return await OutlineArcRepository().create(db, nid, data)

    @pytest.mark.asyncio
    async def test_create_and_get(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        arc_data: OutlineArcCreate,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        repo = OutlineArcRepository()
        created = await repo.create(db_session, nid, arc_data)
        assert created.title == "第一卷：启程"
        assert created.arc_index == 1
        assert created.start_chapter == 1
        assert created.end_chapter == 10
        assert created.arc_goal == "建立世界观，主角踏上旅途"

        fetched = await repo.get(db_session, created.id)
        assert fetched is not None
        assert fetched.title == "第一卷：启程"

    @pytest.mark.asyncio
    async def test_create_many(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        repo = OutlineArcRepository()

        created = await repo.create_many(
            db_session,
            nid,
            [
                OutlineArcCreate(title="批量篇章 1", arc_index=1),
                OutlineArcCreate(title="批量篇章 2", arc_index=2),
            ],
        )

        assert [item.title for item in created] == ["批量篇章 1", "批量篇章 2"]
        fetched = [await repo.get(db_session, item.id) for item in created]
        assert [item.title for item in fetched if item is not None] == [
            "批量篇章 1",
            "批量篇章 2",
        ]

    @pytest.mark.asyncio
    async def test_get_by_chapter(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        repo = OutlineArcRepository()
        await self._make(db_session, nid, title="卷一", start_chapter=1, end_chapter=5)
        await self._make(db_session, nid, title="卷二", start_chapter=6, end_chapter=10)

        found = await repo.get_by_chapter(db_session, nid, chapter_index=3)
        assert found is not None
        assert found.title == "卷一"

        found2 = await repo.get_by_chapter(db_session, nid, chapter_index=8)
        assert found2 is not None
        assert found2.title == "卷二"

    @pytest.mark.asyncio
    async def test_get_by_chapter_outside_range(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        await self._make(db_session, nid, title="卷一", start_chapter=1, end_chapter=5)
        result = await OutlineArcRepository().get_by_chapter(
            db_session, nid, chapter_index=99
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_update_arc(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        repo = OutlineArcRepository()
        created = await self._make(db_session, nid, title="原标题", arc_goal="原目标")
        update = OutlineArcUpdate(title="新标题", core_conflict="新冲突")
        updated = await repo.update(db_session, created.id, update)
        assert updated is not None
        assert updated.title == "新标题"
        assert updated.core_conflict == "新冲突"
        assert updated.arc_goal == "原目标"

    @pytest.mark.asyncio
    async def test_update_arc_can_clear_nullable_chapter_boundary(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        repo = OutlineArcRepository()
        created = await self._make(db_session, nid, start_chapter=1, end_chapter=10)

        updated = await repo.update(
            db_session,
            created.id,
            OutlineArcUpdate(end_chapter=None),
        )

        assert updated is not None
        assert updated.start_chapter == 1
        assert updated.end_chapter is None

    @pytest.mark.asyncio
    async def test_update_reuses_loaded_arc(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = OutlineArcRepository()
        arc_id = uuid.uuid4()
        arc = type(
            "Arc",
            (),
            {
                "id": arc_id,
                "title": "旧篇章",
                "core_conflict": None,
                "related_thread_ids": [],
            },
        )()
        get_calls = 0

        async def fake_get(_db, requested_id):
            nonlocal get_calls
            get_calls += 1
            assert requested_id == arc_id
            return arc

        class Session:
            def __init__(self) -> None:
                self.added = []
                self.flush_count = 0

            def add(self, obj):
                self.added.append(obj)

            async def flush(self) -> None:
                self.flush_count += 1

        monkeypatch.setattr(repo, "get", fake_get)
        db = Session()

        updated = await repo.update(
            db,  # type: ignore[arg-type]
            arc_id,
            OutlineArcUpdate(
                title="新篇章",
                core_conflict="新冲突",
                related_thread_ids=["t1"],
            ),
        )

        assert updated is arc
        assert arc.title == "新篇章"
        assert arc.core_conflict == "新冲突"
        assert arc.related_thread_ids == ["t1"]
        assert get_calls == 1
        assert db.added == [arc]
        assert db.flush_count == 1

    @pytest.mark.asyncio
    async def test_delete_arc(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=sample_novel_id)
        repo = OutlineArcRepository()
        created = await self._make(db_session, nid, title="待删除")
        assert await repo.delete(db_session, created.id) is True
        assert await repo.get(db_session, created.id) is None


class TestSceneWorkbenchHealthProjectionRepository:
    @pytest.mark.asyncio
    async def test_projects_setup_fields_without_sql_derived_health(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        novel_id = uuid.UUID(hex=sample_novel_id)
        repo = SceneRepository()
        created = await repo.create(
            db_session,
            novel_id,
            SceneCreate(
                scene_index=0,
                title="无冲突 Scene",
                goal="完成观察",
                core_conflict=None,
                must_happen="看见潮水变化",
                must_not_happen="引入正文不存在的对抗",
                source="deep_import",
                structure_meta={"core_conflict_status": "not_applicable"},
            ),
        )

        projections = await repo.get_workbench_health_projections(
            db_session,
            novel_id,
        )

        projection = next(item for item in projections if item.id == created.id)
        assert projection.goal == "完成观察"
        assert projection.core_conflict is None
        assert projection.must_happen == "看见潮水变化"
        assert projection.must_not_happen == "引入正文不存在的对抗"
        assert projection.structure_meta["core_conflict_status"] == "not_applicable"
