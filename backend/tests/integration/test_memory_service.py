"""
Memory Facade 集成测试

使用真实 SQLite 内存数据库，通过 facade 层直接调用。
World 状态接口通过 unittest.mock.patch 隔离，避免耦合 world 模块内部表结构。
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

# 确保 memory ORM 模型注册到 Base.metadata（conftest 已导入，此处做双重保险）
import modules.memory.models  # noqa: F401
from modules.memory.repositories import EventRepository, SnapshotRepository
from modules.memory.schemas import (
    ChapterPanorama,
    MemoryStatusResponse,
    SnapshotResponse,
)
from modules.memory.services import MemoryService

_memory = MemoryService()

# ============================================================
# 辅助工厂函数
# ============================================================


def _make_entity(eid: str, name: str = "Test", **kwargs: object) -> dict:
    return {
        "id": eid,
        "entity_type": kwargs.get("entity_type", "character"),
        "name": name,
        "summary": kwargs.get("summary"),
        "public_info": kwargs.get("public_info"),
        "hidden_truth": kwargs.get("hidden_truth"),
        "importance": kwargs.get("importance", 0.5),
        "importance_level": kwargs.get("importance_level", "normal"),
        "reveal_level": kwargs.get("reveal_level", "author_only"),
        "status": kwargs.get("status", "canonical"),
    }


def _make_relation(rid: str, source_id: str, target_id: str, **kwargs: object) -> dict:
    return {
        "id": rid,
        "source_id": source_id,
        "target_id": target_id,
        "relation_type": kwargs.get("relation_type", "friend"),
        "description": kwargs.get("description"),
        "strength": kwargs.get("strength", 0.5),
        "status": kwargs.get("status", "canonical"),
    }


def _make_knowledge(kid: str, character_id: str, **kwargs: object) -> dict:
    return {
        "id": kid,
        "character_id": character_id,
        "target_type": kwargs.get("target_type", "entity"),
        "target_id": kwargs.get("target_id"),
        "knowledge_level": kwargs.get("knowledge_level", "known"),
        "known_content": kwargs.get("known_content"),
        "source_chapter_index": kwargs.get("source_chapter_index"),
        "status": kwargs.get("status", "canonical"),
    }


def _make_world_state(
    entities: list[dict] | None = None,
    relations: list[dict] | None = None,
    character_locations: dict[str, dict] | None = None,
    character_knowledge: list[dict] | None = None,
) -> dict:
    return {
        "entities": list(entities) if entities is not None else [],
        "relations": list(relations) if relations is not None else [],
        "character_locations": dict(character_locations)
        if character_locations is not None
        else {},
        "character_knowledge": list(character_knowledge)
        if character_knowledge is not None
        else [],
    }


# ============================================================
# record_events
# ============================================================


@pytest.mark.asyncio
async def test_record_events_single_event_creates_record(db_session, test_project_id):
    # Arrange
    eid = str(uuid.uuid4())
    events = [
        {
            "event_type": "entity_created",
            "entity_id": eid,
            "entity_type": "character",
            "snapshot_after": _make_entity(eid, name="Alice"),
        }
    ]

    # Act
    result = await _memory.record_events(db_session, test_project_id, 1, events)

    # Assert
    assert len(result) == 1
    assert result[0].event_type == "entity_created"
    assert result[0].entity_id == eid
    assert result[0].chapter_index == 1
    assert result[0].sequence == 1
    assert result[0].snapshot_after["name"] == "Alice"


@pytest.mark.asyncio
async def test_record_events_multiple_events_preserves_sequence(
    db_session, test_project_id
):
    # Arrange
    eid1, eid2 = str(uuid.uuid4()), str(uuid.uuid4())
    events = [
        {
            "event_type": "entity_created",
            "entity_id": eid1,
            "snapshot_after": _make_entity(eid1, name="Alice"),
        },
        {
            "event_type": "entity_created",
            "entity_id": eid2,
            "snapshot_after": _make_entity(eid2, name="Bob"),
        },
    ]

    # Act
    result = await _memory.record_events(db_session, test_project_id, 2, events)

    # Assert
    assert len(result) == 2
    assert result[0].sequence == 1
    assert result[0].entity_id == eid1
    assert result[1].sequence == 2
    assert result[1].entity_id == eid2


@pytest.mark.asyncio
async def test_record_events_overwrite_previous_events(db_session, test_project_id):
    # Arrange
    eid = str(uuid.uuid4())
    await _memory.record_events(
        db_session,
        test_project_id,
        1,
        [
            {
                "event_type": "entity_created",
                "entity_id": eid,
                "snapshot_after": _make_entity(eid, name="Old"),
            }
        ],
    )

    # Act
    result = await _memory.record_events(
        db_session,
        test_project_id,
        1,
        [
            {
                "event_type": "entity_updated",
                "entity_id": eid,
                "snapshot_after": _make_entity(eid, name="New"),
            }
        ],
    )

    # Assert
    assert len(result) == 1
    assert result[0].event_type == "entity_updated"
    repo = EventRepository()
    rows = await repo.get_by_chapter(db_session, uuid.UUID(hex=test_project_id), 1)
    assert len(rows) == 1
    assert rows[0].event_type == "entity_updated"


@pytest.mark.asyncio
async def test_record_events_empty_list_deletes_existing(db_session, test_project_id):
    # Arrange
    eid = str(uuid.uuid4())
    await _memory.record_events(
        db_session,
        test_project_id,
        1,
        [
            {
                "event_type": "entity_created",
                "entity_id": eid,
                "snapshot_after": _make_entity(eid),
            }
        ],
    )

    # Act
    result = await _memory.record_events(db_session, test_project_id, 1, [])

    # Assert
    assert len(result) == 0
    repo = EventRepository()
    rows = await repo.get_by_chapter(db_session, uuid.UUID(hex=test_project_id), 1)
    assert len(rows) == 0


# ============================================================
# get_chapter_panorama
# ============================================================


@pytest.mark.asyncio
async def test_get_chapter_panorama_only_snapshot_no_events(db_session, test_project_id):
    # Arrange
    eid = str(uuid.uuid4())
    snap_repo = SnapshotRepository()
    await snap_repo.create(
        db_session,
        novel_id=uuid.UUID(hex=test_project_id),
        chapter_index=5,
        full_state=_make_world_state(entities=[_make_entity(eid, name="Alice")]),
    )

    # Act
    result = await _memory.get_panorama(db_session, test_project_id, 5)

    # Assert
    assert isinstance(result, ChapterPanorama)
    assert result.novel_id == test_project_id
    assert result.chapter_index == 5
    assert len(result.entities) == 1
    assert result.entities[0].name == "Alice"


@pytest.mark.asyncio
async def test_get_chapter_panorama_with_snapshot_and_events_replays_correctly(
    db_session, test_project_id
):
    # Arrange
    eid = str(uuid.uuid4())
    snap_repo = SnapshotRepository()
    await snap_repo.create(
        db_session,
        novel_id=uuid.UUID(hex=test_project_id),
        chapter_index=5,
        full_state=_make_world_state(entities=[_make_entity(eid, name="Alice")]),
    )
    await _memory.record_events(
        db_session,
        test_project_id,
        6,
        [
            {
                "event_type": "entity_updated",
                "entity_id": eid,
                "snapshot_after": {"name": "Alice Updated"},
            }
        ],
    )

    # Act
    result = await _memory.get_panorama(db_session, test_project_id, 6)

    # Assert
    assert result.chapter_index == 6
    assert len(result.entities) == 1
    assert result.entities[0].name == "Alice Updated"


@pytest.mark.asyncio
async def test_get_chapter_panorama_no_snapshot_but_events_builds_from_empty(
    db_session, test_project_id
):
    # Arrange
    eid = str(uuid.uuid4())
    await _memory.record_events(
        db_session,
        test_project_id,
        1,
        [
            {
                "event_type": "entity_created",
                "entity_id": eid,
                "entity_type": "character",
                "snapshot_after": _make_entity(eid, name="Bob"),
            }
        ],
    )

    # Act
    result = await _memory.get_panorama(db_session, test_project_id, 1)

    # Assert
    assert len(result.entities) == 1
    assert result.entities[0].name == "Bob"
    assert len(result.relations) == 0


@mock.patch("modules.world.facade.get_full_state", autospec=True)
@pytest.mark.asyncio
async def test_get_chapter_panorama_no_data_falls_back_to_world_state(
    mock_get_full_state, db_session, test_project_id
):
    # Arrange
    eid = str(uuid.uuid4())
    mock_get_full_state.return_value = _make_world_state(
        entities=[_make_entity(eid, name="Castle", entity_type="location")]
    )

    # Act
    result = await _memory.get_panorama(db_session, test_project_id, 1)

    # Assert
    assert len(result.entities) == 1
    assert result.entities[0].name == "Castle"
    mock_get_full_state.assert_awaited_once_with(db_session, test_project_id)


# ============================================================
# capture_snapshot
# ============================================================


@mock.patch("modules.world.facade.get_full_state", autospec=True)
@pytest.mark.asyncio
async def test_capture_snapshot_creates_current_snapshot(
    mock_get_full_state, db_session, test_project_id
):
    # Arrange
    mock_get_full_state.return_value = _make_world_state()

    # Act
    result = await _memory.capture_snapshot(db_session, test_project_id, 10)

    # Assert
    assert isinstance(result, SnapshotResponse)
    assert result.chapter_index == 10
    assert result.status == "current"
    assert result.events_until == 0


@mock.patch("modules.world.facade.get_full_state", autospec=True)
@pytest.mark.asyncio
async def test_capture_snapshot_counts_events_correctly(
    mock_get_full_state, db_session, test_project_id
):
    # Arrange
    mock_get_full_state.return_value = _make_world_state()
    eid1, eid2 = str(uuid.uuid4()), str(uuid.uuid4())
    await _memory.record_events(
        db_session,
        test_project_id,
        1,
        [
            {
                "event_type": "entity_created",
                "entity_id": eid1,
                "snapshot_after": _make_entity(eid1),
            }
        ],
    )
    await _memory.record_events(
        db_session,
        test_project_id,
        2,
        [
            {
                "event_type": "entity_created",
                "entity_id": eid2,
                "snapshot_after": _make_entity(eid2),
            },
            {
                "event_type": "entity_created",
                "entity_id": str(uuid.uuid4()),
                "snapshot_after": _make_entity(str(uuid.uuid4())),
            },
        ],
    )

    # Act
    result = await _memory.capture_snapshot(db_session, test_project_id, 2)

    # Assert
    assert result.events_until == 3


# ============================================================
# mark_stale
# ============================================================


@pytest.mark.asyncio
async def test_mark_stale_updates_matching_snapshots(db_session, test_project_id):
    # Arrange
    nid = uuid.UUID(hex=test_project_id)
    snap_repo = SnapshotRepository()
    await snap_repo.create(
        db_session, novel_id=nid, chapter_index=5, full_state=_make_world_state()
    )
    await snap_repo.create(
        db_session, novel_id=nid, chapter_index=10, full_state=_make_world_state()
    )
    await snap_repo.create(
        db_session, novel_id=nid, chapter_index=15, full_state=_make_world_state()
    )

    # Act
    result = await _memory.mark_stale(db_session, test_project_id, 10)

    # Assert
    assert result["stale_count"] == 2
    assert result["from_chapter"] == 10
    snaps = await snap_repo.list_for_novel(db_session, nid)
    statuses = {s.chapter_index: s.status for s in snaps}
    assert statuses[5] == "current"
    assert statuses[10] == "stale"
    assert statuses[15] == "stale"


@pytest.mark.asyncio
async def test_mark_stale_no_snapshots_returns_zero(db_session, test_project_id):
    # Act
    result = await _memory.mark_stale(db_session, test_project_id, 1)

    # Assert
    assert result["stale_count"] == 0
    assert result["from_chapter"] == 1


# ============================================================
# full_rebuild
# ============================================================


@mock.patch("modules.world.facade.get_full_state", autospec=True)
@pytest.mark.asyncio
async def test_full_rebuild_from_chapter_one_clears_all_and_rebuilds(
    mock_get_full_state, db_session, test_project_id
):
    # Arrange
    nid = uuid.UUID(hex=test_project_id)
    eid = str(uuid.uuid4())
    # 旧数据
    await _memory.record_events(
        db_session,
        test_project_id,
        1,
        [
            {
                "event_type": "entity_created",
                "entity_id": eid,
                "snapshot_after": _make_entity(eid, name="Old"),
            }
        ],
    )
    snap_repo = SnapshotRepository()
    await snap_repo.create(
        db_session, novel_id=nid, chapter_index=1, full_state=_make_world_state()
    )
    await snap_repo.create(
        db_session, novel_id=nid, chapter_index=2, full_state=_make_world_state()
    )
    await snap_repo.mark_stale_from(db_session, nid, 2)

    # mock 当前世界状态与基准不同
    mock_get_full_state.return_value = _make_world_state(
        entities=[_make_entity(eid, name="New")]
    )

    # Act
    result = await _memory.full_rebuild(db_session, test_project_id, 1)

    # Assert
    assert result["from_chapter"] == 1
    assert result["final_chapter"] == 1
    assert result["rebuilt_snapshots"] == 1

    # 旧事件应被替换为 diff 事件
    evt_repo = EventRepository()
    events = await evt_repo.get_by_chapter_range(db_session, nid, 1, 999999)
    assert len(events) >= 1
    # 重建保留历史快照；被取代的 current 转为 stale，同章仅有一个 current。
    snaps = await snap_repo.list_for_novel(db_session, nid)
    statuses_by_chapter: dict[int, list[str]] = {}
    for snapshot in snaps:
        assert snapshot.novel_id == nid
        statuses_by_chapter.setdefault(snapshot.chapter_index, []).append(
            snapshot.status
        )

    assert len(snaps) == 3
    assert sorted(statuses_by_chapter[1]) == ["current", "stale"]
    assert statuses_by_chapter[2] == ["stale"]
    current_snapshots = [snapshot for snapshot in snaps if snapshot.status == "current"]
    current_keys = [
        (snapshot.novel_id, snapshot.chapter_index)
        for snapshot in current_snapshots
    ]
    assert current_keys == [(nid, 1)]


@mock.patch("modules.world.facade.get_full_state", autospec=True)
@pytest.mark.asyncio
async def test_full_rebuild_from_middle_preserves_base_and_rebuilds(
    mock_get_full_state, db_session, test_project_id
):
    # Arrange
    nid = uuid.UUID(hex=test_project_id)
    eid = str(uuid.uuid4())
    # chapter 1 事件 + chapter 5 快照
    await _memory.record_events(
        db_session,
        test_project_id,
        1,
        [
            {
                "event_type": "entity_created",
                "entity_id": eid,
                "snapshot_after": _make_entity(eid, name="Alice"),
            }
        ],
    )
    snap_repo = SnapshotRepository()
    await snap_repo.create(
        db_session,
        novel_id=nid,
        chapter_index=5,
        full_state=_make_world_state(entities=[_make_entity(eid, name="Alice")]),
    )

    # 当前世界状态已变更
    mock_get_full_state.return_value = _make_world_state(
        entities=[_make_entity(eid, name="Alice Updated")]
    )

    # Act
    result = await _memory.full_rebuild(db_session, test_project_id, 6)

    # Assert
    assert result["from_chapter"] == 6
    assert result["rebuilt_snapshots"] == 1

    # chapter 1 事件应保留
    evt_repo = EventRepository()
    ch1_events = await evt_repo.get_by_chapter(db_session, nid, 1)
    assert len(ch1_events) == 1

    # chapter 5 快照应保留
    snaps = await snap_repo.list_for_novel(db_session, nid)
    assert any(s.chapter_index == 5 for s in snaps)


@mock.patch("modules.world.facade.get_full_state", autospec=True)
@pytest.mark.asyncio
async def test_full_rebuild_no_changes_still_creates_snapshot(
    mock_get_full_state, db_session, test_project_id
):
    # Arrange
    state = _make_world_state()
    mock_get_full_state.return_value = state

    # Act
    result = await _memory.full_rebuild(db_session, test_project_id, 1)

    # Assert
    assert result["from_chapter"] == 1
    assert result["final_chapter"] == 1
    assert result["rebuilt_snapshots"] == 1
    snap_repo = SnapshotRepository()
    snaps = await snap_repo.list_for_novel(db_session, uuid.UUID(hex=test_project_id))
    assert len(snaps) == 1
    assert snaps[0].chapter_index == 1


# ============================================================
# get_status
# ============================================================


@pytest.mark.asyncio
async def test_get_status_no_snapshots_returns_empty(db_session, test_project_id):
    # Act
    result = await _memory.get_status(db_session, test_project_id)

    # Assert
    assert isinstance(result, MemoryStatusResponse)
    assert result.latest_chapter is None
    assert result.latest_snapshot_chapter is None
    assert result.has_stale is False
    assert result.stale_from_chapter is None


@pytest.mark.asyncio
async def test_get_status_current_only_returns_latest(db_session, test_project_id):
    # Arrange
    nid = uuid.UUID(hex=test_project_id)
    snap_repo = SnapshotRepository()
    await snap_repo.create(
        db_session, novel_id=nid, chapter_index=3, full_state=_make_world_state()
    )
    await snap_repo.create(
        db_session, novel_id=nid, chapter_index=7, full_state=_make_world_state()
    )

    # Act
    result = await _memory.get_status(db_session, test_project_id)

    # Assert
    assert result.latest_chapter == 7
    assert result.latest_snapshot_chapter == 7
    assert result.has_stale is False


@pytest.mark.asyncio
async def test_get_status_with_stale_returns_stale_info(db_session, test_project_id):
    # Arrange
    nid = uuid.UUID(hex=test_project_id)
    snap_repo = SnapshotRepository()
    await snap_repo.create(
        db_session, novel_id=nid, chapter_index=3, full_state=_make_world_state()
    )
    await snap_repo.create(
        db_session, novel_id=nid, chapter_index=7, full_state=_make_world_state()
    )
    await snap_repo.mark_stale_from(db_session, nid, 5)

    # Act
    result = await _memory.get_status(db_session, test_project_id)

    # Assert
    assert result.latest_chapter == 7
    assert result.latest_snapshot_chapter == 3
    assert result.has_stale is True
    assert result.stale_from_chapter == 7
