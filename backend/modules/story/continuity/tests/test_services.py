"""Memory Service 业务逻辑测试 — Round 3"""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.errors import ValidationError
from modules.story.continuity.schemas import EventType
from modules.story.continuity.services import (
    MAX_MEMORY_EVENT_PAYLOAD_CHARS,
    MAX_MEMORY_EVENTS_PER_CHAPTER,
    MemoryService,
)


# 构建 mock 事件对象的工厂
def _event(**kwargs) -> object:
    """创建一个简单的 mock event 对象，属性可访问"""
    defaults = {
        "chapter_index": 1,
        "sequence": 1,
        "event_type": "entity_created",
        "entity_id": uuid.uuid4(),
        "snapshot_before": None,
        "snapshot_after": {"name": "test"},
        "scene_id": None,
        "scene_index": None,
        "scene_sequence": None,
        "dimension": None,
    }
    defaults.update(kwargs)
    return type("MockEvent", (), defaults)()


def _make_memory_event(**overrides: object) -> MagicMock:
    event = MagicMock()
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "chapter_index": 1,
        "sequence": 1,
        "event_type": "entity_created",
        "entity_id": uuid.uuid4(),
        "entity_type": "character",
        "snapshot_before": None,
        "snapshot_after": {"name": "test"},
        "source": "ai_extraction",
        "created_at": datetime.now(UTC),
        "scene_id": None,
        "scene_index": None,
        "scene_sequence": None,
        "dimension": None,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        setattr(event, key, value)
    return event


def _make_snapshot(**overrides: object) -> MagicMock:
    snapshot = MagicMock()
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "chapter_index": 1,
        "status": "current",
        "full_state": {
            "entities": {},
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        },
        "events_until": None,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        setattr(snapshot, key, value)
    return snapshot


@pytest.mark.asyncio
async def test_ingest_delta_events_owns_provenance_and_result_refs(
    db_session: AsyncSession,
    memory_service: MemoryService,
) -> None:
    from sqlalchemy import select

    from modules.story.continuity.contracts import MemoryDeltaEventIngest
    from modules.story.continuity.models import DeltaLog

    novel_id = str(uuid.uuid4())
    result_refs: list[dict[str, str]] = []

    result = await memory_service.ingest_delta_events(
        db_session,
        novel_id,
        [
            MemoryDeltaEventIngest(
                scene_index=3,
                category="location_changed",
                field_path="location",
                old_value={"name": "旧城"},
                new_value={"name": "新城"},
                source="deep_import",
                meta={"confidence": 0.8},
                workflow_id="wf-1",
                scene_id="scene-1",
                scene_provenance_key="wf-1:scene:3",
                context_snapshot_id="ctx-1",
            )
        ],
        result_refs=result_refs,
    )

    assert result.count == 1
    assert result.delta_logs[0]["category"] == "location_changed"
    assert result_refs == [{"type": "delta_log", "id": result.delta_logs[0]["id"]}]

    row = (
        await db_session.execute(
            select(DeltaLog).where(DeltaLog.id == uuid.UUID(result.delta_logs[0]["id"]))
        )
    ).scalar_one()
    assert row.old_value == '{"name": "旧城"}'
    assert row.new_value == '{"name": "新城"}'
    assert row.source == "deep_import"
    assert row.meta["auto_ingested"] is True
    assert row.meta["workflow_id"] == "wf-1"
    assert row.meta["context_snapshot_id"] == "ctx-1"
    assert row.meta["source_ref"]["scene_provenance_key"] == "wf-1:scene:3"


@pytest.mark.asyncio
async def test_rollback_deep_import_delta_logs_is_scoped_and_idempotent(
    db_session: AsyncSession,
    memory_service: MemoryService,
) -> None:
    from modules.story.continuity.models import DeltaLog

    novel_id = str(uuid.uuid4())
    other_novel_id = str(uuid.uuid4())
    rows = [
        DeltaLog(
            novel_id=uuid.UUID(novel_id),
            scene_index=1,
            category="location_changed",
            source="deep_import",
            meta={
                "workflow_id": "wf-rollback",
                "auto_ingested": True,
            },
        ),
        DeltaLog(
            novel_id=uuid.UUID(novel_id),
            scene_index=2,
            category="status_changed",
            source="deep_import",
            meta={"workflow_id": "wf-other", "auto_ingested": True},
        ),
        DeltaLog(
            novel_id=uuid.UUID(other_novel_id),
            scene_index=1,
            category="location_changed",
            source="deep_import",
            meta={
                "workflow_id": "wf-rollback",
                "auto_ingested": True,
            },
        ),
    ]
    db_session.add_all(rows)
    await db_session.flush()

    assert (
        await memory_service.count_deep_import_delta_logs_by_workflow(
            db_session, novel_id, "wf-rollback"
        )
        == 1
    )
    assert (
        await memory_service.rollback_deep_import_delta_logs_by_workflow(
            db_session, novel_id, "wf-rollback"
        )
        == 1
    )
    assert rows[0].meta["rolled_back"] is True
    assert rows[0].meta["rollback_reason"] == "workflow_abandoned"
    assert rows[1].meta.get("rolled_back") is None
    assert rows[2].meta.get("rolled_back") is None
    assert (
        await memory_service.rollback_deep_import_delta_logs_by_workflow(
            db_session, novel_id, "wf-rollback"
        )
        == 0
    )


@pytest.mark.asyncio
async def test_delta_count_and_rollback_use_repository_filters_and_keyset_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.story.continuity.models import DeltaLog

    novel_id = str(uuid.uuid4())
    rows = [
        DeltaLog(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(novel_id),
            category="location_changed",
            source="deep_import",
            meta={"workflow_id": "wf-1", "auto_ingested": True},
        )
        for _ in range(2)
    ]
    delta_repo = MagicMock()
    delta_repo.count_active_by_workflow = AsyncMock(return_value=2)
    delta_repo.get_active_by_workflow_page_after = AsyncMock(
        side_effect=[[rows[0]], [rows[1]], []]
    )
    monkeypatch.setattr("modules.story.continuity.services.DELTA_ROLLBACK_BATCH_SIZE", 1)
    service = MemoryService(delta_log_repo=delta_repo)
    db = MagicMock()
    db.flush = AsyncMock()

    count = await service.count_deep_import_delta_logs_by_workflow(db, novel_id, "wf-1")
    rolled_back = await service.rollback_deep_import_delta_logs_by_workflow(
        db, novel_id, "wf-1"
    )

    assert count == 2
    assert rolled_back == 2
    delta_repo.count_active_by_workflow.assert_awaited_once_with(
        db, uuid.UUID(novel_id), "wf-1"
    )
    assert delta_repo.get_active_by_workflow_page_after.await_count == 3
    assert all(row.meta["rolled_back"] is True for row in rows)


@pytest.mark.asyncio
async def test_delta_rollback_uuid_keyset_covers_multiple_real_pages_once(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.story.continuity.models import DeltaLog

    novel_id = uuid.uuid4()
    matching = [
        DeltaLog(
            id=uuid.UUID(int=value),
            novel_id=novel_id,
            category="location_changed",
            source="deep_import",
            meta={"workflow_id": "wf-keyset", "auto_ingested": True},
        )
        for value in (5, 1, 4, 2, 3)
    ]
    unrelated = DeltaLog(
        id=uuid.UUID(int=6),
        novel_id=novel_id,
        category="location_changed",
        source="deep_import",
        meta={"workflow_id": "wf-other", "auto_ingested": True},
    )
    db_session.add_all([*matching, unrelated])
    await db_session.flush()
    monkeypatch.setattr("modules.story.continuity.services.DELTA_ROLLBACK_BATCH_SIZE", 2)
    service = MemoryService()

    assert (
        await service.rollback_deep_import_delta_logs_by_workflow(
            db_session,
            str(novel_id),
            "wf-keyset",
        )
        == 5
    )
    assert (
        await service.rollback_deep_import_delta_logs_by_workflow(
            db_session,
            str(novel_id),
            "wf-keyset",
        )
        == 0
    )

    refreshed = list(
        (await db_session.execute(select(DeltaLog).where(DeltaLog.novel_id == novel_id)))
        .scalars()
        .all()
    )
    refreshed_by_id = {item.id: item for item in refreshed}
    assert all(refreshed_by_id[item.id].meta["rolled_back"] is True for item in matching)
    assert refreshed_by_id[unrelated.id].meta.get("rolled_back") is None


@pytest.mark.asyncio
async def test_full_rebuild_stales_replaced_snapshots_without_deleting_history(
    db_with_project: AsyncSession,
    sample_novel_id: uuid.UUID,
    memory_service: MemoryService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.project.models import Project
    from modules.story.continuity.models import MemoryEvent, MemorySnapshot
    from modules.story.continuity.repositories import SnapshotRepository

    empty_state = {
        "entities": [],
        "relations": [],
        "character_locations": {},
        "character_knowledge": [],
    }
    snapshot_repo = SnapshotRepository()
    for chapter in (5, 6, 10, 12):
        await snapshot_repo.create(
            db_with_project,
            novel_id=sample_novel_id,
            chapter_index=chapter,
            full_state=empty_state,
        )
    historical_stale = MemorySnapshot(
        novel_id=sample_novel_id,
        chapter_index=10,
        status="stale",
        full_state=empty_state,
    )
    other_novel_id = uuid.uuid4()
    db_with_project.add(Project(id=other_novel_id, title="另一项目", genre="奇幻"))
    await db_with_project.flush()
    other_snapshot = await snapshot_repo.create(
        db_with_project,
        novel_id=other_novel_id,
        chapter_index=12,
        full_state=empty_state,
    )
    db_with_project.add(historical_stale)
    db_with_project.add(
        MemoryEvent(
            novel_id=sample_novel_id,
            chapter_index=12,
            sequence=1,
            event_type="manual_correction",
            snapshot_after={},
            source="manual_edit",
        )
    )
    await db_with_project.flush()
    monkeypatch.setattr(
        "modules.world.facade.get_full_state",
        AsyncMock(return_value=empty_state),
    )

    result = await memory_service.full_rebuild(
        db_with_project,
        str(sample_novel_id),
        6,
    )

    snapshots = list(
        (
            await db_with_project.execute(
                select(MemorySnapshot)
                .where(MemorySnapshot.novel_id == sample_novel_id)
                .order_by(MemorySnapshot.chapter_index, MemorySnapshot.created_at)
            )
        )
        .scalars()
        .all()
    )
    statuses_by_chapter: dict[int, list[str]] = {}
    for snapshot in snapshots:
        statuses_by_chapter.setdefault(snapshot.chapter_index, []).append(snapshot.status)

    assert result["final_chapter"] == 12
    assert result["rebuilt_snapshots"] == 2
    assert statuses_by_chapter[5] == ["current"]
    assert statuses_by_chapter[6] == ["stale"]
    assert statuses_by_chapter[10].count("current") == 1
    assert statuses_by_chapter[10].count("stale") == 2
    assert sorted(statuses_by_chapter[12]) == ["current", "stale"]
    assert historical_stale in snapshots
    await db_with_project.refresh(other_snapshot)
    assert other_snapshot.status == "current"


@pytest.mark.asyncio
async def test_record_events_replaces_chapter_events_without_stale_tail(
    db_with_project: AsyncSession,
    memory_service: MemoryService,
    sample_novel_id: uuid.UUID,
) -> None:
    await memory_service.record_events(
        db_with_project,
        str(sample_novel_id),
        3,
        [
            {"event_type": "entity_created", "snapshot_after": {"name": "A"}},
            {"event_type": "entity_updated", "snapshot_after": {"name": "B"}},
        ],
    )

    await memory_service.record_events(
        db_with_project,
        str(sample_novel_id),
        3,
        [{"event_type": "entity_moved", "snapshot_after": {"name": "C"}}],
    )

    from modules.story.continuity.models import MemoryEvent

    rows = (
        (
            await db_with_project.execute(
                select(MemoryEvent).where(
                    MemoryEvent.novel_id == sample_novel_id,
                    MemoryEvent.chapter_index == 3,
                )
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 1
    assert rows[0].sequence == 1
    assert rows[0].event_type == "entity_moved"


@pytest.mark.asyncio
async def test_record_events_concurrent_calls_keep_unique_sequences() -> None:
    from core.base import Base
    from modules.project.models import Project
    from modules.story.continuity.models import MemoryEvent

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    async with factory() as session:
        session.add(Project(id=novel_id, title="并发记忆测试", genre="test"))
        await session.commit()

    async def write_events(label: str) -> None:
        async with factory() as session:
            await MemoryService().record_events(
                session,
                str(novel_id),
                5,
                [
                    {"event_type": "entity_created", "snapshot_after": {"label": label}},
                    {"event_type": "entity_updated", "snapshot_after": {"label": label}},
                ],
            )
            await session.commit()

    try:
        await asyncio.gather(write_events("a"), write_events("b"))
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(MemoryEvent).where(
                            MemoryEvent.novel_id == novel_id,
                            MemoryEvent.chapter_index == 5,
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert sorted(row.sequence for row in rows) == [1, 2]
    finally:
        await engine.dispose()


class TestApplyEvents:
    """_apply_events 纯逻辑测试（不依赖 DB）"""

    def test_entity_created(self, memory_service: MemoryService) -> None:
        """空状态 + entity_created → entities 新增一条"""
        state = {
            "entities": {},
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        eid = uuid.uuid4()
        event = _event(
            event_type=EventType.entity_created,
            entity_id=eid,
            snapshot_after={"id": str(eid), "name": "张三", "entity_type": "character"},
        )
        result = memory_service._apply_events(state, [event])
        assert len(result["entities"]) == 1
        assert result["entities"][0]["name"] == "张三"

    def test_entity_updated(self, memory_service: MemoryService) -> None:
        """有一实体 + entity_updated → 字段更新"""
        eid = uuid.uuid4()
        state = {
            "entities": [{"id": str(eid), "name": "张三", "summary": "旧摘要"}],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        event = _event(
            event_type=EventType.entity_updated,
            entity_id=eid,
            snapshot_after={"summary": "新摘要"},
        )
        result = memory_service._apply_events(state, [event])
        assert result["entities"][0]["summary"] == "新摘要"
        assert state["entities"][0]["summary"] == "旧摘要"

    def test_event_snapshots_are_not_mutated_by_later_events(
        self,
        memory_service: MemoryService,
    ) -> None:
        eid = uuid.uuid4()
        created = _event(
            event_type=EventType.entity_created,
            entity_id=eid,
            snapshot_after={"id": str(eid), "summary": "旧摘要"},
        )
        updated = _event(
            event_type=EventType.entity_updated,
            entity_id=eid,
            snapshot_after={"summary": "新摘要"},
        )

        result = memory_service._apply_events(
            {
                "entities": {},
                "relations": [],
                "character_locations": {},
                "character_knowledge": [],
            },
            [created, updated],
        )

        assert result["entities"][0]["summary"] == "新摘要"
        assert created.snapshot_after["summary"] == "旧摘要"

    def test_entity_removed(self, memory_service: MemoryService) -> None:
        """有一实体 + entity_removed → entities 为空"""
        eid = uuid.uuid4()
        state = {
            "entities": [{"id": str(eid), "name": "待删除"}],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        event = _event(
            event_type=EventType.entity_removed, entity_id=eid, snapshot_after={}
        )
        result = memory_service._apply_events(state, [event])
        assert len(result["entities"]) == 0

    def test_entity_moved(self, memory_service: MemoryService) -> None:
        """空位置 + entity_moved → character_locations 新增"""
        state = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        eid = uuid.uuid4()
        event = _event(
            event_type=EventType.entity_moved,
            entity_id=eid,
            snapshot_after={"location_id": "loc-1", "text_state": "到了长安"},
        )
        result = memory_service._apply_events(state, [event])
        assert str(eid) in result["character_locations"]

    def test_relation_established(self, memory_service: MemoryService) -> None:
        """空关系 + relation_established → relations 新增一条"""
        state = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        rid = uuid.uuid4()
        event = _event(
            event_type=EventType.relation_established,
            snapshot_after={
                "id": str(rid),
                "source_id": "a",
                "target_id": "b",
                "relation_type": "father_of",
            },
        )
        result = memory_service._apply_events(state, [event])
        assert len(result["relations"]) == 1

    def test_relation_ended(self, memory_service: MemoryService) -> None:
        """有一关系 + relation_ended → relations 为空"""
        rid = "rel-1"
        state = {
            "entities": [],
            "relations": [
                {
                    "id": rid,
                    "source_id": "a",
                    "target_id": "b",
                    "relation_type": "friend_of",
                }
            ],
            "character_locations": {},
            "character_knowledge": [],
        }
        event = _event(
            event_type=EventType.relation_ended,
            snapshot_after={"relation_id": rid},
        )
        result = memory_service._apply_events(state, [event])
        assert len(result["relations"]) == 0

    def test_knowledge_changed(self, memory_service: MemoryService) -> None:
        """空知识 + knowledge_changed → character_knowledge 新增一条"""
        state = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        event = _event(
            event_type=EventType.knowledge_changed,
            snapshot_after={
                "id": "k1",
                "character_id": "c1",
                "target_type": "entity",
                "knowledge_level": "full",
            },
        )
        result = memory_service._apply_events(state, [event])
        assert len(result["character_knowledge"]) == 1

    def test_multiple_events_sequential(self, memory_service: MemoryService) -> None:
        """连续 3 个不同类型事件，验证最终状态"""
        eid = uuid.uuid4()
        state = {
            "entities": {},
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }

        events = [
            _event(
                event_type=EventType.entity_created,
                entity_id=eid,
                snapshot_after={"id": str(eid), "name": "王五"},
            ),
            _event(
                event_type=EventType.entity_updated,
                entity_id=eid,
                snapshot_after={"summary": "已更新"},
            ),
            _event(
                event_type=EventType.entity_moved,
                entity_id=eid,
                snapshot_after={"location_id": "loc-2"},
            ),
        ]
        result = memory_service._apply_events(state, events)
        assert len(result["entities"]) == 1
        assert result["entities"][0]["summary"] == "已更新"
        assert str(eid) in result["character_locations"]


class TestDiffStates:
    """_diff_states 纯逻辑测试"""

    def test_entity_created_diff(self, memory_service: MemoryService) -> None:
        """新增实体 → 生成 entity_created 事件"""
        before = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        after = {
            "entities": [{"id": "e1", "entity_type": "character", "name": "新角色"}],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        events = memory_service._diff_states(before, after)
        assert len(events) >= 1
        assert events[0]["event_type"] == EventType.entity_created

    def test_entity_updated_diff(self, memory_service: MemoryService) -> None:
        """实体字段变更 → 生成 entity_updated 事件"""
        before = {
            "entities": [
                {"id": "e1", "name": "旧名", "summary": "", "entity_type": "character"}
            ],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        after = {
            "entities": [
                {"id": "e1", "name": "新名", "summary": "", "entity_type": "character"}
            ],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        events = memory_service._diff_states(before, after)
        updated = [e for e in events if e["event_type"] == EventType.entity_updated]
        assert len(updated) == 1

    def test_entity_removed_diff(self, memory_service: MemoryService) -> None:
        """实体消失 → 生成 entity_removed 事件"""
        before = {
            "entities": [{"id": "e1", "entity_type": "character", "name": "待移除"}],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        after = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        events = memory_service._diff_states(before, after)
        removed = [e for e in events if e["event_type"] == EventType.entity_removed]
        assert len(removed) == 1

    def test_relation_established_diff(self, memory_service: MemoryService) -> None:
        """关系新增 → 生成 relation_established 事件"""
        before = {
            "entities": [],
            "relations": [],
            "character_locations": {},
            "character_knowledge": [],
        }
        after = {
            "entities": [],
            "relations": [
                {
                    "id": "r1",
                    "source_id": "a",
                    "target_id": "b",
                    "relation_type": "friend_of",
                }
            ],
            "character_locations": {},
            "character_knowledge": [],
        }
        events = memory_service._diff_states(before, after)
        est = [e for e in events if e["event_type"] == EventType.relation_established]
        assert len(est) == 1

    def test_character_location_changed_diff(self, memory_service: MemoryService) -> None:
        """角色位置变化 → 生成 entity_moved 事件"""
        before = {
            "entities": [],
            "relations": [],
            "character_locations": {"c1": {"location_id": "loc-a", "text_state": "在A"}},
            "character_knowledge": [],
        }
        after = {
            "entities": [],
            "relations": [],
            "character_locations": {
                "c1": {"location_id": "loc-b", "text_state": "到了B"}
            },
            "character_knowledge": [],
        }
        events = memory_service._diff_states(before, after)
        moved = [e for e in events if e["event_type"] == EventType.entity_moved]
        assert len(moved) == 1


class TestRecordEvents:
    """record_events 方法测试 — repo 用 AsyncMock 替换"""

    @pytest.mark.asyncio
    async def test_record_rejects_too_many_events_before_writes(self) -> None:
        novel_id = str(uuid.uuid4())
        event_repo = MagicMock()
        event_repo.replace_chapter_events = AsyncMock()
        snapshot_repo = MagicMock()
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = AsyncMock()

        with pytest.raises(ValidationError) as exc_info:
            await service.record_events(
                db,
                novel_id,
                3,
                [
                    {"event_type": "entity_created", "snapshot_after": {"name": "A"}}
                    for _ in range(MAX_MEMORY_EVENTS_PER_CHAPTER + 1)
                ],
            )

        assert str(MAX_MEMORY_EVENTS_PER_CHAPTER) in exc_info.value.message
        event_repo.replace_chapter_events.assert_not_awaited()
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_record_rejects_oversized_event_payload_before_writes(self) -> None:
        novel_id = str(uuid.uuid4())
        event_repo = MagicMock()
        event_repo.replace_chapter_events = AsyncMock()
        snapshot_repo = MagicMock()
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = AsyncMock()
        sentinel = "PAYLOAD_SENTINEL"

        with pytest.raises(ValidationError) as exc_info:
            await service.record_events(
                db,
                novel_id,
                3,
                [
                    {
                        "event_type": "entity_created",
                        "snapshot_after": {
                            "name": "A",
                            "content": sentinel + ("x" * MAX_MEMORY_EVENT_PAYLOAD_CHARS),
                        },
                    }
                ],
            )

        assert "event_index=1" in exc_info.value.message
        assert str(MAX_MEMORY_EVENT_PAYLOAD_CHARS) in exc_info.value.message
        assert sentinel not in exc_info.value.message
        event_repo.replace_chapter_events.assert_not_awaited()
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_record_batch(self) -> None:
        """记录 3 条事件，验证数量和 sequence"""
        novel_id = str(uuid.uuid4())
        events_data = [
            {
                "event_type": "entity_created",
                "entity_id": str(uuid.uuid4()),
                "entity_type": "character",
                "snapshot_after": {"name": "A"},
            },
            {
                "event_type": "entity_created",
                "entity_id": str(uuid.uuid4()),
                "entity_type": "character",
                "snapshot_after": {"name": "B"},
            },
            {
                "event_type": "entity_moved",
                "entity_id": str(uuid.uuid4()),
                "entity_type": "character",
                "snapshot_after": {"location_id": "loc-1"},
            },
        ]
        created = [_make_memory_event(sequence=i + 1) for i in range(3)]
        event_repo = MagicMock()
        event_repo.delete_by_chapter = AsyncMock()
        event_repo.create_many = AsyncMock(return_value=created)
        event_repo.replace_chapter_events = AsyncMock(return_value=created)
        event_repo.create = AsyncMock(
            side_effect=AssertionError("record_events should batch event inserts")
        )
        snapshot_repo = MagicMock()
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = AsyncMock()

        result = await service.record_events(db, novel_id, 3, events_data)

        assert len(result) == 3
        assert result[0].sequence == 1
        assert result[2].sequence == 3
        event_repo.replace_chapter_events.assert_awaited_once()
        _, kwargs = event_repo.replace_chapter_events.await_args
        assert kwargs["novel_id"] == uuid.UUID(novel_id)
        assert kwargs["chapter_index"] == 3
        rows = kwargs["rows"]
        assert [row["sequence"] for row in rows] == [1, 2, 3]
        assert [row["event_type"] for row in rows] == [
            "entity_created",
            "entity_created",
            "entity_moved",
        ]
        event_repo.delete_by_chapter.assert_not_awaited()
        event_repo.create_many.assert_not_awaited()
        event_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_record_overwrites_existing(self) -> None:
        """重新记录同一章事件，旧事件被清除"""
        novel_id = str(uuid.uuid4())
        new_events = [
            {
                "event_type": "entity_created",
                "entity_id": str(uuid.uuid4()),
                "snapshot_after": {"name": "new1"},
            },
            {
                "event_type": "entity_created",
                "entity_id": str(uuid.uuid4()),
                "snapshot_after": {"name": "new2"},
            },
        ]
        created = [_make_memory_event(sequence=i + 1) for i in range(2)]
        event_repo = MagicMock()
        event_repo.delete_by_chapter = AsyncMock()
        event_repo.create_many = AsyncMock(return_value=created)
        event_repo.replace_chapter_events = AsyncMock(return_value=created)
        event_repo.create = AsyncMock(
            side_effect=AssertionError("record_events should batch event inserts")
        )
        snapshot_repo = MagicMock()
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = AsyncMock()

        result = await service.record_events(db, novel_id, 3, new_events)

        assert len(result) == 2
        event_repo.replace_chapter_events.assert_awaited_once()
        _, kwargs = event_repo.replace_chapter_events.await_args
        assert kwargs["novel_id"] == uuid.UUID(novel_id)
        assert kwargs["chapter_index"] == 3
        assert [row["sequence"] for row in kwargs["rows"]] == [1, 2]
        event_repo.delete_by_chapter.assert_not_awaited()
        event_repo.create_many.assert_not_awaited()
        event_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_events_uses_keyset_batches_and_sql_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = str(uuid.uuid4())
    first = _make_memory_event(
        id=uuid.uuid4(), chapter_index=2, sequence=1, novel_id=uuid.UUID(novel_id)
    )
    second = _make_memory_event(
        id=uuid.uuid4(), chapter_index=3, sequence=1, novel_id=uuid.UUID(novel_id)
    )
    event_repo = MagicMock()
    event_repo.count_by_chapter_range = AsyncMock(return_value=2)
    event_repo.get_by_chapter_range = AsyncMock(
        side_effect=AssertionError("event list must not full-load a chapter range")
    )
    event_repo.get_by_chapter_range_page_after = AsyncMock(
        side_effect=[[first], [second]]
    )
    monkeypatch.setattr(
        "modules.story.continuity.services.MEMORY_EVENT_LIST_BATCH_SIZE", 1
    )
    service = MemoryService(event_repo=event_repo)

    result = await service.list_events(MagicMock(), novel_id, 2, 3)

    assert result.total == 2
    assert [(item.chapter_index, item.sequence) for item in result.items] == [
        (2, 1),
        (3, 1),
    ]
    assert event_repo.get_by_chapter_range_page_after.await_count == 2
    event_repo.get_by_chapter_range.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_events_real_keyset_keeps_order_total_shape_and_last_limit(
    db_with_project: AsyncSession,
    sample_novel_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.story.continuity.repositories import EventRepository

    event_repo = EventRepository()
    rows = [
        {
            "novel_id": sample_novel_id,
            "chapter_index": chapter,
            "sequence": sequence,
            "event_type": "entity_created",
            "snapshot_after": {"chapter": chapter, "sequence": sequence},
        }
        for chapter, sequence in ((3, 1), (1, 2), (2, 2), (1, 1), (2, 1))
    ]
    await event_repo.create_many(db_with_project, rows)
    original_page = event_repo.get_by_chapter_range_page_after
    event_repo.get_by_chapter_range_page_after = AsyncMock(wraps=original_page)  # type: ignore[method-assign]
    monkeypatch.setattr(
        "modules.story.continuity.services.MEMORY_EVENT_LIST_BATCH_SIZE", 2
    )
    service = MemoryService(event_repo=event_repo)

    result = await service.list_events(
        db_with_project,
        str(sample_novel_id),
        1,
        3,
    )

    assert result.total == 5
    assert [(item.chapter_index, item.sequence) for item in result.items] == [
        (1, 1),
        (1, 2),
        (2, 1),
        (2, 2),
        (3, 1),
    ]
    assert set(result.model_dump()) == {"items", "total"}
    limits = [
        call.kwargs["limit"]
        for call in event_repo.get_by_chapter_range_page_after.await_args_list
    ]
    assert limits == [2, 2, 1]

    calls_before_empty = event_repo.get_by_chapter_range_page_after.await_count
    empty = await service.list_events(
        db_with_project,
        str(sample_novel_id),
        4,
        4,
    )
    assert empty.total == 0
    assert empty.items == []
    assert event_repo.get_by_chapter_range_page_after.await_count == calls_before_empty


class TestReplayState:
    """replay_state 方法测试 — repo 用 AsyncMock 替换"""

    @pytest.mark.asyncio
    async def test_replay_empty(self) -> None:
        """无快照无事件 → 返回空状态"""
        novel_id = str(uuid.uuid4())
        snapshot_repo = MagicMock()
        snapshot_repo.get_nearest = AsyncMock(return_value=None)
        event_repo = MagicMock()
        event_repo.get_by_chapter_range = AsyncMock(
            side_effect=AssertionError("replay_state must page event replay")
        )
        event_repo.get_by_chapter_range_page_after = AsyncMock(return_value=[])
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.replay_state(db, novel_id, 1)

        assert result["entities"] == []
        assert result["relations"] == []
        event_repo.get_by_chapter_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_replay_events_only(self) -> None:
        """无快照，只有事件 → 重放出正确状态"""
        novel_id = str(uuid.uuid4())
        eid = uuid.uuid4()
        events = [
            _make_memory_event(
                event_type="entity_created",
                entity_id=eid,
                snapshot_after={
                    "id": str(eid),
                    "name": "张三",
                    "entity_type": "character",
                },
            ),
        ]
        snapshot_repo = MagicMock()
        snapshot_repo.get_nearest = AsyncMock(return_value=None)
        event_repo = MagicMock()
        event_repo.get_by_chapter_range = AsyncMock(
            side_effect=AssertionError("replay_state must page event replay")
        )
        event_repo.get_by_chapter_range_page_after = AsyncMock(return_value=events)
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.replay_state(db, novel_id, 1)

        assert len(result["entities"]) == 1
        assert result["entities"][0]["name"] == "张三"
        event_repo.get_by_chapter_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_replay_pages_events_without_repeated_full_load(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        novel_id = str(uuid.uuid4())
        eid = uuid.uuid4()
        create_event = _make_memory_event(
            id=uuid.uuid4(),
            event_type="entity_created",
            entity_id=eid,
            chapter_index=1,
            sequence=1,
            snapshot_after={
                "id": str(eid),
                "name": "张三",
                "entity_type": "character",
            },
        )
        update_event = _make_memory_event(
            id=uuid.uuid4(),
            event_type="entity_updated",
            entity_id=eid,
            chapter_index=2,
            sequence=1,
            snapshot_after={"name": "张三 Updated"},
        )
        snapshot_repo = MagicMock()
        snapshot_repo.get_nearest = AsyncMock(return_value=None)
        event_repo = MagicMock()
        event_repo.get_by_chapter_range = AsyncMock(
            side_effect=AssertionError("replay_state must page event replay")
        )
        event_repo.get_by_chapter_range_page_after = AsyncMock(
            side_effect=[[create_event], [update_event], []]
        )
        monkeypatch.setattr(
            "modules.story.continuity.services.MEMORY_REPLAY_EVENT_BATCH_SIZE",
            1,
        )
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.replay_state(db, novel_id, 2)
        expected = service._apply_events(
            {
                "entities": {},
                "relations": [],
                "character_locations": {},
                "character_knowledge": [],
            },
            [create_event, update_event],
        )

        assert result == expected
        assert result["entities"][0]["name"] == "张三 Updated"
        assert event_repo.get_by_chapter_range_page_after.await_count == 3
        event_repo.get_by_chapter_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_panorama_no_snapshot_no_events_returns_stage0_without_world(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        novel_id = str(uuid.uuid4())
        snapshot_repo = MagicMock()
        snapshot_repo.get_nearest = AsyncMock(return_value=None)
        event_repo = MagicMock()
        event_repo.get_by_chapter_range = AsyncMock(
            side_effect=AssertionError("get_panorama must page event replay")
        )
        event_repo.get_by_chapter_range_page_after = AsyncMock(return_value=[])

        get_full_state = AsyncMock(
            return_value={
                "entities": [],
                "relations": [],
                "character_locations": {},
                "character_knowledge": [],
            }
        )
        monkeypatch.setattr("modules.world.facade.get_full_state", get_full_state)
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.get_panorama(db, novel_id, 3)

        assert result.novel_id == novel_id
        assert result.chapter_index == 3
        assert result.entities == []
        get_full_state.assert_not_awaited()
        event_repo.get_by_chapter_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_continuity_evidence_uses_count_before_panorama(
        self,
    ) -> None:
        novel_id = str(uuid.uuid4())
        snapshot_repo = MagicMock()
        snapshot_repo.get_nearest = AsyncMock(return_value=None)
        event_repo = MagicMock()
        event_repo.count_by_chapter_range = AsyncMock(return_value=0)
        event_repo.get_by_chapter_range = AsyncMock(
            side_effect=AssertionError("continuity evidence must not full-load events")
        )
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.get_continuity_evidence_for_writing(
            db,
            novel_id,
            5,
            pov_character_id=str(uuid.uuid4()),
            current_location_id="loc-new",
        )

        assert result is None
        event_repo.count_by_chapter_range.assert_awaited_once_with(
            db, uuid.UUID(novel_id), 1, 4
        )
        event_repo.get_by_chapter_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_capture_snapshot_counts_events_without_full_load(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        novel_id = str(uuid.uuid4())
        event_repo = MagicMock()
        event_repo.count_by_chapter_range = AsyncMock(return_value=7)
        event_repo.get_by_chapter_range_page_after = AsyncMock(return_value=[])
        event_repo.get_by_chapter_range = AsyncMock(
            side_effect=AssertionError("capture_snapshot must not full-load events")
        )
        snapshot_repo = MagicMock()
        snapshot_repo.get_nearest = AsyncMock(return_value=None)
        snapshot_repo.create = AsyncMock(
            return_value=_make_snapshot(
                novel_id=uuid.UUID(novel_id),
                chapter_index=10,
                events_until=7,
            )
        )
        monkeypatch.setattr(
            "modules.world.facade.get_full_state",
            AsyncMock(
                return_value={
                    "entities": [],
                    "relations": [],
                    "character_locations": {},
                    "character_knowledge": [],
                }
            ),
        )
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.capture_snapshot(db, novel_id, 10)

        assert result.events_until == 7
        event_repo.count_by_chapter_range.assert_awaited_once_with(
            db, uuid.UUID(novel_id), 1, 10
        )
        event_repo.get_by_chapter_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_full_rebuild_uses_max_chapter_without_full_load(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        novel_id = str(uuid.uuid4())
        event_repo = MagicMock()
        event_repo.delete_from_chapter = AsyncMock(return_value=0)
        event_repo.get_max_chapter_in_range = AsyncMock(return_value=12)
        event_repo.count_by_chapter_range = AsyncMock(return_value=0)
        event_repo.get_by_chapter_range_page_after = AsyncMock(return_value=[])
        event_repo.get_by_chapter_range = AsyncMock(
            side_effect=AssertionError("full_rebuild must not full-load events")
        )
        snapshot_repo = MagicMock()
        snapshot_repo.get_nearest = AsyncMock(return_value=None)
        snapshot_repo.mark_stale_from = AsyncMock(return_value=0)
        snapshot_repo.delete_stale = AsyncMock(
            side_effect=AssertionError("rebuild must preserve stale history")
        )
        snapshot_repo.create = AsyncMock(
            side_effect=[
                _make_snapshot(novel_id=uuid.UUID(novel_id), chapter_index=10),
                _make_snapshot(novel_id=uuid.UUID(novel_id), chapter_index=12),
            ]
        )
        monkeypatch.setattr(
            "modules.world.facade.get_full_state",
            AsyncMock(
                return_value={
                    "entities": [],
                    "relations": [],
                    "character_locations": {},
                    "character_knowledge": [],
                }
            ),
        )
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.full_rebuild(db, novel_id, 1)

        assert result == {
            "rebuilt_snapshots": 2,
            "from_chapter": 1,
            "final_chapter": 12,
        }
        event_repo.get_max_chapter_in_range.assert_awaited_once_with(
            db, uuid.UUID(novel_id), 1, 999999
        )
        event_repo.delete_from_chapter.assert_not_awaited()
        event_repo.get_by_chapter_range.assert_not_awaited()
        snapshot_repo.mark_stale_from.assert_awaited_once_with(db, uuid.UUID(novel_id), 1)
        snapshot_repo.delete_stale.assert_not_awaited()


class TestMarkStale:
    """mark_stale 方法测试 — repo 用 AsyncMock 替换"""

    @pytest.mark.asyncio
    async def test_mark_single_snapshot(self) -> None:
        """单个快照被标记为 stale"""
        novel_id = str(uuid.uuid4())
        snapshot_repo = MagicMock()
        snapshot_repo.mark_stale_from = AsyncMock(return_value=1)
        service = MemoryService(snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.mark_stale(db, novel_id, 5)

        assert result["stale_count"] == 1
        assert result["from_chapter"] == 5
        snapshot_repo.mark_stale_from.assert_awaited_once_with(db, uuid.UUID(novel_id), 5)

    @pytest.mark.asyncio
    async def test_mark_partial(self) -> None:
        """只标记 >= from_chapter 的快照"""
        novel_id = str(uuid.uuid4())
        snapshot_repo = MagicMock()
        snapshot_repo.mark_stale_from = AsyncMock(return_value=2)
        service = MemoryService(snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.mark_stale(db, novel_id, 8)

        assert result["stale_count"] == 2  # Ch10, Ch15


class TestGetStatus:
    """get_status 方法测试 — repo 用 AsyncMock 替换"""

    @pytest.mark.asyncio
    async def test_empty(self) -> None:
        """无快照 → 返回空状态"""
        novel_id = str(uuid.uuid4())
        snapshot_repo = MagicMock()
        snapshot_repo.get_status_summary = AsyncMock(return_value=(0, None, None, None))
        snapshot_repo.list_for_novel = AsyncMock(
            side_effect=AssertionError("status must use SQL aggregation")
        )
        service = MemoryService(snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.get_status(db, novel_id)

        assert result.latest_chapter is None
        assert result.has_stale is False

    @pytest.mark.asyncio
    async def test_all_current(self) -> None:
        """全部 current 快照"""
        novel_id = str(uuid.uuid4())
        snapshot_repo = MagicMock()
        snapshot_repo.get_status_summary = AsyncMock(return_value=(2, 10, 10, None))
        snapshot_repo.list_for_novel = AsyncMock(
            side_effect=AssertionError("status must use SQL aggregation")
        )
        service = MemoryService(snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.get_status(db, novel_id)

        assert result.latest_chapter == 10
        assert result.latest_snapshot_chapter == 10
        assert result.has_stale is False

    @pytest.mark.asyncio
    async def test_with_stale(self) -> None:
        """有 stale 快照 → has_stale=True"""
        novel_id = str(uuid.uuid4())
        snapshot_repo = MagicMock()
        snapshot_repo.get_status_summary = AsyncMock(return_value=(2, 10, 5, 10))
        snapshot_repo.list_for_novel = AsyncMock(
            side_effect=AssertionError("status must use SQL aggregation")
        )
        service = MemoryService(snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.get_status(db, novel_id)

        assert result.has_stale is True
        assert result.stale_from_chapter == 10


@pytest.mark.asyncio
async def test_continuity_evidence_for_writing_returns_memory_chapter_target(
    db_session: AsyncSession,
    sample_novel_id: uuid.UUID,
) -> None:
    from modules.story.continuity.facade import get_continuity_evidence_for_writing
    from modules.story.continuity.models import MemoryEvent

    character_id = uuid.uuid4()
    character_id_text = str(character_id)
    db_session.add(
        MemoryEvent(
            novel_id=sample_novel_id,
            chapter_index=2,
            sequence=1,
            event_type="entity_moved",
            entity_id=character_id,
            entity_type="character",
            snapshot_before={},
            snapshot_after={
                "location_id": "loc-old",
                "text_state": "上一章在旧城门",
                "chapter_index": 2,
            },
            source="manual_edit",
        )
    )
    await db_session.flush()

    evidence = await get_continuity_evidence_for_writing(
        db_session,
        novel_id=str(sample_novel_id),
        chapter_index=3,
        pov_character_id=character_id_text,
        current_location_id="loc-new",
        current_location_name="王城内门",
    )

    assert evidence is not None
    assert evidence.source_module == "memory"
    assert evidence.source_type == "memory.character_location"
    assert evidence.source_id == character_id_text
    assert evidence.source_label == "章节记忆：第 2 章"
    assert evidence.source_field == "角色位置"
    assert "上一章在旧城门" in evidence.source_excerpt
    assert evidence.open_target == {
        "kind": "memory_chapter",
        "chapter_index": 2,
        "character_id": character_id_text,
    }


@pytest.mark.asyncio
async def test_continuity_evidence_for_writing_returns_none_for_same_location(
    db_session: AsyncSession,
    sample_novel_id: uuid.UUID,
) -> None:
    from modules.story.continuity.facade import get_continuity_evidence_for_writing
    from modules.story.continuity.models import MemoryEvent

    character_id = uuid.uuid4()
    character_id_text = str(character_id)
    db_session.add(
        MemoryEvent(
            novel_id=sample_novel_id,
            chapter_index=2,
            sequence=1,
            event_type="entity_moved",
            entity_id=character_id,
            entity_type="character",
            snapshot_before={},
            snapshot_after={
                "location_id": "loc-old",
                "text_state": "上一章在旧城门",
                "chapter_index": 2,
            },
            source="manual_edit",
        )
    )
    await db_session.flush()

    evidence = await get_continuity_evidence_for_writing(
        db_session,
        novel_id=str(sample_novel_id),
        chapter_index=3,
        pov_character_id=character_id_text,
        current_location_id="loc-old",
    )

    assert evidence is None


@pytest.mark.asyncio
async def test_continuity_evidence_for_writing_ignores_world_fallback_without_history(
    db_session: AsyncSession,
    sample_novel_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.story.continuity.facade import get_continuity_evidence_for_writing

    character_id_text = str(uuid.uuid4())

    async def fake_get_full_state(db: AsyncSession, novel_id: str) -> dict[str, object]:
        return {
            "entities": [],
            "relations": [],
            "character_locations": {
                character_id_text: {
                    "location_id": "loc-old",
                    "text_state": "世界当前状态里的旧位置",
                    "chapter_index": 1,
                }
            },
            "character_knowledge": [],
        }

    monkeypatch.setattr("modules.world.facade.get_full_state", fake_get_full_state)

    evidence = await get_continuity_evidence_for_writing(
        db_session,
        novel_id=str(sample_novel_id),
        chapter_index=2,
        pov_character_id=character_id_text,
        current_location_id="loc-new",
    )

    assert evidence is None
