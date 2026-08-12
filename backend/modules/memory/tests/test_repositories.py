"""Memory Repository 测试 — Round 2"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.models import DeltaLog, MemorySceneCheckpoint, MemorySnapshot
from modules.memory.repositories import (
    DeltaLogRepository,
    EventRepository,
    SceneCheckpointRepository,
    SnapshotRepository,
)


class TestSceneCheckpointRepository:
    async def test_identical_system_replacement_reuses_current_version(
        self,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        repo = SceneCheckpointRepository()
        scene_id = uuid.uuid4()
        values = {
            "status": "ready",
            "confirmed": False,
            "is_current": True,
            "state_json": {"entities": {}},
            "evidence_refs": [],
            "display_summary": "人物与对象 0 条",
            "source_hash": "same-projection",
            "retry_count": 0,
        }

        first = await repo.replace_system(
            db_with_project,
            novel_id=sample_novel_id,
            scene_id=scene_id,
            scene_index=0,
            dimension="entities",
            values=values,
        )
        second = await repo.replace_system(
            db_with_project,
            novel_id=sample_novel_id,
            scene_id=scene_id,
            scene_index=0,
            dimension="entities",
            values=values,
        )

        assert second.id == first.id
        rows = list(
            (
                await db_with_project.execute(
                    select(MemorySceneCheckpoint).where(
                        MemorySceneCheckpoint.novel_id == sample_novel_id,
                        MemorySceneCheckpoint.scene_id == scene_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == [first]


class TestEventRepository:
    """EventRepository 数据访问层测试"""

    async def test_create(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """创建单条事件，验证返回字段"""
        event = await event_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=3,
            sequence=1,
            event_type="entity_created",
            snapshot_after={"name": "张三"},
            entity_id=uuid.uuid4(),
            entity_type="character",
        )
        assert event.id is not None
        assert event.chapter_index == 3
        assert event.sequence == 1
        assert event.event_type == "entity_created"
        assert event.snapshot_after == {"name": "张三"}
        assert event.source == "ai_extraction"

    async def test_create_many(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        rows = [
            {
                "novel_id": sample_novel_id,
                "chapter_index": 3,
                "sequence": 1,
                "event_type": "entity_created",
                "snapshot_after": {"name": "张三"},
                "entity_id": uuid.uuid4(),
                "entity_type": "character",
            },
            {
                "novel_id": sample_novel_id,
                "chapter_index": 3,
                "sequence": 2,
                "event_type": "entity_moved",
                "snapshot_after": {"location_id": "loc-1"},
                "entity_id": uuid.uuid4(),
                "entity_type": "character",
            },
        ]

        events = await event_repo.create_many(db_with_project, rows)

        assert [event.sequence for event in events] == [1, 2]
        saved = await event_repo.get_by_chapter(db_with_project, sample_novel_id, 3)
        assert [event.event_type for event in saved] == [
            "entity_created",
            "entity_moved",
        ]

    async def test_get_by_chapter(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """创建 Ch3 + Ch5 事件，按 Ch3 查返回正确数量和排序"""
        eid = uuid.uuid4()
        # Ch3: 3条
        await event_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=3,
            sequence=1,
            event_type="entity_created",
            snapshot_after={"n": 1},
            entity_id=eid,
        )
        await event_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=3,
            sequence=2,
            event_type="entity_updated",
            snapshot_after={"n": 2},
            entity_id=eid,
        )
        await event_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=3,
            sequence=3,
            event_type="entity_moved",
            snapshot_after={"loc": "A"},
            entity_id=eid,
        )
        # Ch5: 2条
        await event_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=5,
            sequence=1,
            event_type="entity_created",
            snapshot_after={"n": 3},
            entity_id=uuid.uuid4(),
        )

        result = await event_repo.get_by_chapter(db_with_project, sample_novel_id, 3)
        assert len(result) == 3
        assert [r.sequence for r in result] == [1, 2, 3]

    async def test_get_by_chapter_range(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """创建 Ch1-5 各一条，查 Ch2-4 返回 3 条"""
        eid = uuid.uuid4()
        for ch in range(1, 6):
            await event_repo.create(
                db_with_project,
                novel_id=sample_novel_id,
                chapter_index=ch,
                sequence=1,
                event_type="entity_created",
                snapshot_after={"ch": ch},
                entity_id=eid,
            )

        result = await event_repo.get_by_chapter_range(
            db_with_project, sample_novel_id, 2, 4
        )
        assert len(result) == 3
        assert sorted(r.chapter_index for r in result) == [2, 3, 4]

    async def test_count_and_max_chapter_in_range(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        eid = uuid.uuid4()
        sequence_by_chapter: dict[int, int] = {}
        for ch in (1, 2, 2, 5):
            sequence_by_chapter[ch] = sequence_by_chapter.get(ch, 0) + 1
            await event_repo.create(
                db_with_project,
                novel_id=sample_novel_id,
                chapter_index=ch,
                sequence=sequence_by_chapter[ch],
                event_type="entity_created",
                snapshot_after={"ch": ch},
                entity_id=eid,
            )

        count = await event_repo.count_by_chapter_range(
            db_with_project, sample_novel_id, 2, 4
        )
        max_chapter = await event_repo.get_max_chapter_in_range(
            db_with_project, sample_novel_id, 2, 4
        )
        empty_max = await event_repo.get_max_chapter_in_range(
            db_with_project, sample_novel_id, 6, 9
        )

        assert count == 2
        assert max_chapter == 2
        assert empty_max is None

    async def test_get_by_chapter_range_page_after_orders_across_boundaries(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        eid = uuid.uuid4()
        for chapter, sequence in [(1, 1), (1, 2), (2, 1), (3, 1), (3, 2)]:
            await event_repo.create(
                db_with_project,
                novel_id=sample_novel_id,
                chapter_index=chapter,
                sequence=sequence,
                event_type="entity_created",
                snapshot_after={"chapter": chapter, "sequence": sequence},
                entity_id=eid,
            )

        first = await event_repo.get_by_chapter_range_page_after(
            db_with_project,
            sample_novel_id,
            1,
            3,
            after=None,
            limit=2,
        )
        second = await event_repo.get_by_chapter_range_page_after(
            db_with_project,
            sample_novel_id,
            1,
            3,
            after=(first[-1].chapter_index, first[-1].sequence, first[-1].id),
            limit=2,
        )
        third = await event_repo.get_by_chapter_range_page_after(
            db_with_project,
            sample_novel_id,
            1,
            3,
            after=(second[-1].chapter_index, second[-1].sequence, second[-1].id),
            limit=2,
        )

        ordered = [
            (event.chapter_index, event.sequence) for event in [*first, *second, *third]
        ]
        assert ordered == [(1, 1), (1, 2), (2, 1), (3, 1), (3, 2)]
        assert len(first) == 2
        assert len(second) == 2
        assert len(third) == 1

    async def test_get_by_entity(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """同一 entity_id 跨章查询返回正确数量和 total"""
        target_eid = uuid.uuid4()
        other_eid = uuid.uuid4()
        await event_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=1,
            sequence=1,
            event_type="entity_created",
            snapshot_after={"x": 1},
            entity_id=target_eid,
        )
        await event_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=3,
            sequence=1,
            event_type="entity_moved",
            snapshot_after={"x": 2},
            entity_id=target_eid,
        )
        await event_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=2,
            sequence=1,
            event_type="entity_created",
            snapshot_after={"x": 3},
            entity_id=other_eid,
        )

        items, total = await event_repo.get_by_entity(
            db_with_project, sample_novel_id, target_eid
        )
        assert len(items) == 2
        assert total == 2

    async def test_get_by_entity_pagination(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """创建 30 条同实体事件，验证分页"""
        eid = uuid.uuid4()
        for i in range(30):
            await event_repo.create(
                db_with_project,
                novel_id=sample_novel_id,
                chapter_index=i + 1,
                sequence=1,
                event_type="entity_updated",
                snapshot_after={"i": i},
                entity_id=eid,
            )

        items, total = await event_repo.get_by_entity(
            db_with_project, sample_novel_id, eid, skip=10, limit=5
        )
        assert len(items) == 5
        assert total == 30

    async def test_delete_by_chapter(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """删除 Ch3 事件，Ch5 仍存在"""
        eid = uuid.uuid4()
        for ch, seq in [(3, 1), (3, 2), (3, 3), (5, 1), (5, 2)]:
            await event_repo.create(
                db_with_project,
                novel_id=sample_novel_id,
                chapter_index=ch,
                sequence=seq,
                event_type="entity_updated",
                snapshot_after={"ch": ch},
                entity_id=eid,
            )

        count = await event_repo.delete_by_chapter(db_with_project, sample_novel_id, 3)
        assert count == 3

        remaining = await event_repo.get_by_chapter(db_with_project, sample_novel_id, 5)
        assert len(remaining) == 2

    async def test_delete_from_chapter(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """删除 from_chapter 及之后，之前保留"""
        eid = uuid.uuid4()
        for ch in range(1, 6):
            await event_repo.create(
                db_with_project,
                novel_id=sample_novel_id,
                chapter_index=ch,
                sequence=1,
                event_type="entity_created",
                snapshot_after={"ch": ch},
                entity_id=eid,
            )

        count = await event_repo.delete_from_chapter(db_with_project, sample_novel_id, 3)
        assert count == 3  # Ch3,4,5

        all_remaining = await event_repo.get_by_chapter_range(
            db_with_project, sample_novel_id, 1, 5
        )
        assert len(all_remaining) == 2
        assert set(r.chapter_index for r in all_remaining) == {1, 2}

    async def test_get_max_sequence(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """空章返回 0，三条事件后返回 3"""
        eid = uuid.uuid4()
        max_seq = await event_repo.get_max_sequence(db_with_project, sample_novel_id, 1)
        assert max_seq == 0

        for seq in range(1, 4):
            await event_repo.create(
                db_with_project,
                novel_id=sample_novel_id,
                chapter_index=1,
                sequence=seq,
                event_type="entity_updated",
                snapshot_after={"s": seq},
                entity_id=eid,
            )

        max_seq = await event_repo.get_max_sequence(db_with_project, sample_novel_id, 1)
        assert max_seq == 3

    async def test_novel_isolation(
        self,
        event_repo: EventRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """两个 novel_id 各建事件，互不干扰"""
        nid2 = uuid.uuid4()
        from modules.project.models import Project

        p2 = Project(id=nid2, title="另一个项目", genre="科幻")
        db_with_project.add(p2)
        await db_with_project.flush()

        eid1 = uuid.uuid4()
        eid2 = uuid.uuid4()
        await event_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=1,
            sequence=1,
            event_type="entity_created",
            snapshot_after={"n": "A"},
            entity_id=eid1,
        )
        await event_repo.create(
            db_with_project,
            novel_id=nid2,
            chapter_index=1,
            sequence=1,
            event_type="entity_created",
            snapshot_after={"n": "B"},
            entity_id=eid2,
        )

        result1 = await event_repo.get_by_chapter(db_with_project, sample_novel_id, 1)
        result2 = await event_repo.get_by_chapter(db_with_project, nid2, 1)
        assert len(result1) == 1
        assert len(result2) == 1
        assert result1[0].snapshot_after["n"] == "A"
        assert result2[0].snapshot_after["n"] == "B"


class TestDeltaLogRepository:
    async def test_workflow_queries_filter_in_database_and_keep_novel_isolation(
        self,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        other_novel_id = uuid.uuid4()
        matching = DeltaLog(
            id=uuid.UUID(int=1),
            novel_id=sample_novel_id,
            category="location_changed",
            source="deep_import",
            meta={"workflow_id": "wf-1", "auto_ingested": True},
        )
        explicit_false = DeltaLog(
            id=uuid.UUID(int=2),
            novel_id=sample_novel_id,
            category="location_changed",
            source="deep_import",
            meta={
                "workflow_id": "wf-1",
                "auto_ingested": True,
                "rolled_back": False,
            },
        )
        non_boolean_rollback = DeltaLog(
            id=uuid.UUID(int=3),
            novel_id=sample_novel_id,
            category="location_changed",
            source="deep_import",
            meta={
                "workflow_id": "wf-1",
                "auto_ingested": True,
                "rolled_back": "true",
            },
        )
        db_with_project.add_all(
            [
                matching,
                explicit_false,
                non_boolean_rollback,
                DeltaLog(
                    id=uuid.UUID(int=4),
                    novel_id=sample_novel_id,
                    category="location_changed",
                    source="deep_import",
                    meta={"workflow_id": "wf-2", "auto_ingested": True},
                ),
                DeltaLog(
                    id=uuid.UUID(int=5),
                    novel_id=sample_novel_id,
                    category="location_changed",
                    source="deep_import",
                    meta={
                        "workflow_id": "wf-1",
                        "auto_ingested": True,
                        "rolled_back": True,
                    },
                ),
                DeltaLog(
                    id=uuid.UUID(int=6),
                    novel_id=sample_novel_id,
                    category="location_changed",
                    source="deep_import",
                    meta={"workflow_id": "wf-1", "auto_ingested": "true"},
                ),
                DeltaLog(
                    id=uuid.UUID(int=7),
                    novel_id=sample_novel_id,
                    category="location_changed",
                    source="deep_import",
                    meta={"workflow_id": "wf-1", "auto_ingested": 1},
                ),
                DeltaLog(
                    id=uuid.UUID(int=8),
                    novel_id=sample_novel_id,
                    category="location_changed",
                    source="deep_import",
                    meta={"workflow_id": 123, "auto_ingested": True},
                ),
                DeltaLog(
                    id=uuid.UUID(int=9),
                    novel_id=other_novel_id,
                    category="location_changed",
                    source="deep_import",
                    meta={"workflow_id": "wf-1", "auto_ingested": True},
                ),
            ]
        )
        await db_with_project.flush()
        repository = DeltaLogRepository()

        count = await repository.count_active_by_workflow(
            db_with_project, sample_novel_id, "wf-1"
        )
        page = await repository.get_active_by_workflow_page_after(
            db_with_project,
            sample_novel_id,
            "wf-1",
            after_id=None,
            limit=10,
        )

        assert count == 3
        assert [item.id for item in page] == [
            matching.id,
            explicit_false.id,
            non_boolean_rollback.id,
        ]
        assert (
            await repository.count_active_by_workflow(
                db_with_project,
                sample_novel_id,
                "123",
            )
            == 0
        )

    def test_workflow_filter_sql_preserves_json_types_in_both_dialects(self) -> None:
        novel_id = uuid.uuid4()
        repository = DeltaLogRepository()

        sqlite_stmt = select(DeltaLog.id).where(
            *repository._active_workflow_conditions(
                novel_id,
                "wf-1",
                dialect_name="sqlite",
            )
        )
        postgres_stmt = select(DeltaLog.id).where(
            *repository._active_workflow_conditions(
                novel_id,
                "wf-1",
                dialect_name="postgresql",
            )
        )

        sqlite_sql = str(sqlite_stmt.compile(dialect=sqlite.dialect()))
        postgres_sql = str(postgres_stmt.compile(dialect=postgresql.dialect()))
        assert "json_type" in sqlite_sql
        assert "json_typeof" in postgres_sql
        assert "CASE WHEN" in postgres_sql


class TestSnapshotRepository:
    """SnapshotRepository 数据访问层测试"""

    async def test_create(
        self,
        snapshot_repo: SnapshotRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """创建快照，验证 status='current'"""
        snap = await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=5,
            full_state={
                "entities": [{"id": "x", "name": "test"}],
                "relations": [],
                "character_locations": {},
                "character_knowledge": [],
            },
            events_until=10,
        )
        assert snap.status == "current"
        assert snap.chapter_index == 5
        assert snap.events_until == 10

    async def test_create_supersedes_only_same_novel_and_chapter_current(
        self,
        snapshot_repo: SnapshotRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        from modules.project.models import Project

        empty_state = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        other_novel_id = uuid.uuid4()
        db_with_project.add(Project(id=other_novel_id, title="另一项目", genre="奇幻"))
        await db_with_project.flush()
        other = await snapshot_repo.create(
            db_with_project,
            novel_id=other_novel_id,
            chapter_index=5,
            full_state=empty_state,
        )
        first = await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=5,
            full_state=empty_state,
        )
        unaffected_chapter = await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=4,
            full_state=empty_state,
        )
        replacement = await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=5,
            full_state=empty_state,
        )

        await db_with_project.refresh(first)
        await db_with_project.refresh(other)
        await db_with_project.refresh(unaffected_chapter)
        assert first.status == "stale"
        assert replacement.status == "current"
        assert other.status == "current"
        assert unaffected_chapter.status == "current"
        latest = await snapshot_repo.get_latest(
            db_with_project,
            sample_novel_id,
            5,
        )
        assert latest is not None
        assert latest.id == replacement.id

    async def test_get_nearest(
        self,
        snapshot_repo: SnapshotRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """get_nearest 返回 ≤ chapter_index 的最近 current 快照"""
        empty_state = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=5,
            full_state=empty_state,
        )
        await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=10,
            full_state=empty_state,
        )

        nearest_8 = await snapshot_repo.get_nearest(db_with_project, sample_novel_id, 8)
        assert nearest_8 is not None
        assert nearest_8.chapter_index == 5

        nearest_3 = await snapshot_repo.get_nearest(db_with_project, sample_novel_id, 3)
        assert nearest_3 is None

    async def test_list_for_novel(
        self,
        snapshot_repo: SnapshotRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """列表按 chapter_index 排序"""
        empty_state = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=10,
            full_state=empty_state,
        )
        await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=5,
            full_state=empty_state,
        )

        result = await snapshot_repo.list_for_novel(db_with_project, sample_novel_id)
        assert len(result) == 2
        assert result[0].chapter_index == 5
        assert result[1].chapter_index == 10

    async def test_get_status_summary_aggregates_in_database(
        self,
        snapshot_repo: SnapshotRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        from modules.project.models import Project

        empty_state = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=5,
            full_state=empty_state,
        )
        stale = await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=10,
            full_state=empty_state,
        )
        stale.status = "stale"
        other_novel_id = uuid.uuid4()
        db_with_project.add(Project(id=other_novel_id, title="另一项目", genre="奇幻"))
        await db_with_project.flush()
        other = await snapshot_repo.create(
            db_with_project,
            novel_id=other_novel_id,
            chapter_index=99,
            full_state=empty_state,
        )
        other.status = "stale"
        await db_with_project.flush()

        summary = await snapshot_repo.get_status_summary(db_with_project, sample_novel_id)

        assert summary == (2, 10, 5, 10)

    async def test_get_status_summary_ignores_superseded_snapshot_history(
        self,
        snapshot_repo: SnapshotRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        empty_state = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=5,
            full_state=empty_state,
        )
        await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=5,
            full_state={**empty_state, "entities": [{"id": "replacement"}]},
        )

        summary = await snapshot_repo.get_status_summary(db_with_project, sample_novel_id)

        assert summary == (2, 5, 5, None)

    async def test_mark_stale_from(
        self,
        snapshot_repo: SnapshotRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """mark_stale_from 只影响 >= from_chapter 的 current 快照"""
        empty_state = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=5,
            full_state=empty_state,
        )
        await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=10,
            full_state=empty_state,
        )
        await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=15,
            full_state=empty_state,
        )

        count = await snapshot_repo.mark_stale_from(db_with_project, sample_novel_id, 8)
        assert count == 2  # Ch10, Ch15

        nearest = await snapshot_repo.get_nearest(db_with_project, sample_novel_id, 5)
        assert nearest is not None
        assert nearest.status == "current"  # Ch5 不变

    async def test_delete_stale(
        self,
        snapshot_repo: SnapshotRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """delete_stale 删除所有 stale 快照"""
        empty_state = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        s1 = await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=5,
            full_state=empty_state,
        )
        # 手动改为 stale（用 update 语句）
        from sqlalchemy import update

        stmt = (
            update(MemorySnapshot)
            .where(MemorySnapshot.id == s1.id)
            .values(status="stale")
        )
        await db_with_project.execute(stmt)
        await db_with_project.flush()

        count = await snapshot_repo.delete_stale(db_with_project, sample_novel_id)
        assert count == 1

        remaining = await snapshot_repo.list_for_novel(db_with_project, sample_novel_id)
        assert len(remaining) == 0
