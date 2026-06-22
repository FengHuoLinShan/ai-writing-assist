"""Memory Service 业务逻辑测试 — Round 3"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.schemas import EventType
from modules.memory.services import MemoryService


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
        event_repo.create = AsyncMock(side_effect=created)
        snapshot_repo = MagicMock()
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = AsyncMock()

        result = await service.record_events(db, novel_id, 3, events_data)

        assert len(result) == 3
        assert result[0].sequence == 1
        assert result[2].sequence == 3
        event_repo.delete_by_chapter.assert_awaited_once_with(
            db, uuid.UUID(novel_id), 3
        )

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
        event_repo.create = AsyncMock(side_effect=created)
        snapshot_repo = MagicMock()
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = AsyncMock()

        result = await service.record_events(db, novel_id, 3, new_events)

        assert len(result) == 2
        event_repo.delete_by_chapter.assert_awaited_once_with(
            db, uuid.UUID(novel_id), 3
        )


class TestReplayState:
    """replay_state 方法测试 — repo 用 AsyncMock 替换"""

    @pytest.mark.asyncio
    async def test_replay_empty(self) -> None:
        """无快照无事件 → 返回空状态"""
        novel_id = str(uuid.uuid4())
        snapshot_repo = MagicMock()
        snapshot_repo.get_nearest = AsyncMock(return_value=None)
        event_repo = MagicMock()
        event_repo.get_by_chapter_range = AsyncMock(return_value=[])
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.replay_state(db, novel_id, 1)

        assert result["entities"] == []
        assert result["relations"] == []

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
        event_repo.get_by_chapter_range = AsyncMock(return_value=events)
        service = MemoryService(event_repo=event_repo, snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.replay_state(db, novel_id, 1)

        assert len(result["entities"]) == 1
        assert result["entities"][0]["name"] == "张三"


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
        snapshot_repo.mark_stale_from.assert_awaited_once_with(
            db, uuid.UUID(novel_id), 5
        )

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
        snapshot_repo.list_for_novel = AsyncMock(return_value=[])
        service = MemoryService(snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.get_status(db, novel_id)

        assert result.latest_chapter is None
        assert result.has_stale is False

    @pytest.mark.asyncio
    async def test_all_current(self) -> None:
        """全部 current 快照"""
        novel_id = str(uuid.uuid4())
        snapshots = [
            _make_snapshot(novel_id=novel_id, chapter_index=5, status="current"),
            _make_snapshot(novel_id=novel_id, chapter_index=10, status="current"),
        ]
        snapshot_repo = MagicMock()
        snapshot_repo.list_for_novel = AsyncMock(return_value=snapshots)
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
        snapshots = [
            _make_snapshot(novel_id=novel_id, chapter_index=5, status="current"),
            _make_snapshot(novel_id=novel_id, chapter_index=10, status="stale"),
        ]
        snapshot_repo = MagicMock()
        snapshot_repo.list_for_novel = AsyncMock(return_value=snapshots)
        service = MemoryService(snapshot_repo=snapshot_repo)
        db = MagicMock()

        result = await service.get_status(db, novel_id)

        assert result.has_stale is True
        assert result.stale_from_chapter == 10
