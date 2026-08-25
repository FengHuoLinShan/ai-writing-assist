"""
Memory 模块单元测试 — api.py + contracts.py

覆盖所有 API 端点（7 个）和 2 个数据契约。
使用 unittest.mock 完全隔离 DB 和外部依赖。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.api import (
    get_entity_timeline,
    get_panorama,
    get_status,
    list_events,
    list_snapshots,
    trigger_capture,
    trigger_rebuild,
)
from modules.story.continuity.contracts import (
    ChapterPanoramaContract,
    MemoryEventContract,
)
from modules.story.continuity.schemas import (
    ChapterPanorama,
    EventListResponse,
    MemoryStatusResponse,
    SnapshotListResponse,
    SnapshotResponse,
)

# ============================================================
# 辅助函数 — 构造模拟数据对象
# ============================================================


def _make_event(novel_id: str, **overrides: object) -> SimpleNamespace:
    """创建模拟的 MemoryEvent ORM 对象（可被 Pydantic model_validate）"""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "novel_id": uuid.UUID(hex=novel_id),
        "chapter_index": 1,
        "sequence": 1,
        "event_type": "entity_created",
        "entity_id": uuid.uuid4(),
        "entity_type": "character",
        "snapshot_before": None,
        "snapshot_after": {"name": "Alice"},
        "source": "ai_extraction",
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_snapshot(novel_id: str, **overrides: object) -> SimpleNamespace:
    """创建模拟的 MemorySnapshot ORM 对象"""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "novel_id": uuid.UUID(hex=novel_id),
        "chapter_index": 1,
        "status": "current",
        "events_until": 5,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def _stub_memory_active_project_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    from modules.story.continuity import api as memory_api

    async def require_active_project(_db, _novel_id):
        return None

    monkeypatch.setattr(memory_api, "_require_active_project", require_active_project)


# ============================================================
# Contracts 测试
# ============================================================


class TestMemoryEventContract:
    """MemoryEventContract dataclass — 跨模块契约"""

    def test_minimal_required_fields(self):
        """仅必需字段时使用默认值"""
        contract = MemoryEventContract(
            id="evt-1",
            chapter_index=3,
            event_type="entity_created",
        )
        assert contract.id == "evt-1"
        assert contract.chapter_index == 3
        assert contract.event_type == "entity_created"
        assert contract.entity_id is None
        assert contract.entity_type is None
        assert contract.snapshot_after == {}

    def test_frozen_cannot_modify(self):
        """@dataclass(frozen=True) 禁止属性修改"""
        contract = MemoryEventContract(id="evt-1", chapter_index=1, event_type="created")
        with pytest.raises(AttributeError):
            contract.id = "new"  # type: ignore[misc]

    def test_full_fields(self):
        """所有字段全部传入"""
        contract = MemoryEventContract(
            id="evt-2",
            chapter_index=5,
            event_type="entity_updated",
            entity_id="ent-42",
            entity_type="location",
            snapshot_after={"name": "城堡"},
        )
        assert contract.entity_id == "ent-42"
        assert contract.entity_type == "location"
        assert contract.snapshot_after == {"name": "城堡"}

    def test_default_snapshot_after_is_fresh_each_instance(self):
        """每个实例的 snapshot_after 是独立 dict"""
        c1 = MemoryEventContract(id="a", chapter_index=1, event_type="created")
        c2 = MemoryEventContract(
            id="b", chapter_index=1, event_type="created", snapshot_after={"x": 1}
        )
        assert c1.snapshot_after == {}
        assert c2.snapshot_after == {"x": 1}
        # frozen 只禁止替换属性，不禁止内部 dict 修改（Python 行为）
        c1.snapshot_after["y"] = 2
        assert c1.snapshot_after == {"y": 2}
        assert c2.snapshot_after == {"x": 1}


class TestChapterPanoramaContract:
    """ChapterPanoramaContract dataclass — 跨模块契约"""

    def test_minimal_required_fields(self):
        """仅必需字段，其余为默认"""
        contract = ChapterPanoramaContract(
            novel_id="novel-1",
            chapter_index=5,
        )
        assert contract.novel_id == "novel-1"
        assert contract.chapter_index == 5
        assert contract.entities == []
        assert contract.relations == []
        assert contract.character_locations == {}
        assert contract.character_knowledge == []

    def test_frozen_cannot_modify(self):
        """@dataclass(frozen=True) 禁止属性修改"""
        contract = ChapterPanoramaContract(novel_id="nid", chapter_index=1)
        with pytest.raises(AttributeError):
            contract.novel_id = "new"  # type: ignore[misc]

    def test_full_fields(self):
        """全部字段传入"""
        contract = ChapterPanoramaContract(
            novel_id="novel-1",
            chapter_index=10,
            entities=[{"id": "e1", "name": "Alice"}],
            relations=[{"id": "r1"}],
            character_locations={"c1": {"location_id": "loc-1"}},
            character_knowledge=[
                {"id": "k1", "character_id": "c1", "target_type": "entity"}
            ],
        )
        assert len(contract.entities) == 1
        assert contract.entities[0]["name"] == "Alice"
        assert len(contract.relations) == 1
        assert "c1" in contract.character_locations
        assert len(contract.character_knowledge) == 1


# ============================================================
# API — get_panorama
# ============================================================


@pytest.mark.usefixtures("_stub_memory_active_project_guard")
class TestGetPanorama:
    """GET /api/novels/{novel_id}/memories/panorama"""

    async def test_happy_path_returns_chapter_panorama(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "a" * 32
        chapter_index = 3
        expected = ChapterPanorama(
            novel_id=novel_id,
            chapter_index=chapter_index,
            entities=[],
            relations=[],
        )

        with patch(
            "modules.story.continuity.api._service.get_panorama",
            autospec=True,
            return_value=expected,
        ):
            result = await get_panorama(db, novel_id, chapter_index)

        assert result is expected
        assert isinstance(result, ChapterPanorama)
        assert result.novel_id == novel_id

    async def test_service_exception_propagates(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "b" * 32

        with patch(
            "modules.story.continuity.api._service.get_panorama",
            autospec=True,
            side_effect=RuntimeError("service error"),
        ):
            with pytest.raises(RuntimeError, match="service error"):
                await get_panorama(db, novel_id, 1)


# ============================================================
# API — list_events
# ============================================================


@pytest.mark.usefixtures("_stub_memory_active_project_guard")
class TestListEvents:
    """GET /api/novels/{novel_id}/memories/events"""

    async def test_happy_path_returns_event_list(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "c" * 32
        event = _make_event(novel_id)

        with (
            patch(
                "modules.story.continuity.repositories.EventRepository.count_by_chapter_range",
                autospec=True,
                return_value=1,
            ) as mock_count,
            patch(
                "modules.story.continuity.repositories.EventRepository."
                "get_by_chapter_range_page_after",
                autospec=True,
                return_value=[event],
            ) as mock_page,
        ):
            result = await list_events(
                db,
                novel_id,
                from_chapter=1,
                to_chapter=999999,
            )

        assert isinstance(result, EventListResponse)
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].event_type == "entity_created"
        assert result.items[0].entity_type == "character"
        assert result.items[0].snapshot_after == {"name": "Alice"}
        count_args = mock_count.await_args.args
        assert count_args[1:] == (db, uuid.UUID(hex=novel_id), 1, 999999)
        page_args = mock_page.await_args.args
        assert page_args[1:] == (db, uuid.UUID(hex=novel_id), 1, 999999)
        assert mock_page.await_args.kwargs == {"after": None, "limit": 1}

    @pytest.mark.parametrize(
        "events,expected_total",
        [
            ([], 0),
            ([_make_event("d" * 32)], 1),
            ([_make_event("d" * 32), _make_event("d" * 32)], 2),
        ],
    )
    async def test_various_event_counts(self, events, expected_total):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "d" * 32

        with (
            patch(
                "modules.story.continuity.repositories.EventRepository.count_by_chapter_range",
                autospec=True,
                return_value=expected_total,
            ),
            patch(
                "modules.story.continuity.repositories.EventRepository."
                "get_by_chapter_range_page_after",
                autospec=True,
                return_value=events,
            ) as mock_page,
        ):
            result = await list_events(
                db,
                novel_id,
                from_chapter=1,
                to_chapter=999999,
            )

        assert result.total == expected_total
        assert len(result.items) == expected_total
        assert mock_page.await_count == (1 if expected_total else 0)

    async def test_from_chapter_to_chapter_passed_to_repository(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "e" * 32

        with (
            patch(
                "modules.story.continuity.repositories.EventRepository.count_by_chapter_range",
                autospec=True,
                return_value=0,
            ) as mock_count,
            patch(
                "modules.story.continuity.repositories.EventRepository."
                "get_by_chapter_range_page_after",
                autospec=True,
            ) as mock_page,
        ):
            await list_events(db, novel_id, from_chapter=3, to_chapter=7)

        count_args = mock_count.await_args.args
        # autospec preserves the repository method's self argument.
        assert count_args[1:] == (db, uuid.UUID(hex=novel_id), 3, 7)
        mock_page.assert_not_awaited()

    async def test_default_chapter_range_explicit_values_are_valid(self):
        """验证明确的 from_chapter/to_chapter 值被传递到 repository"""
        db = AsyncMock(spec=AsyncSession)
        novel_id = "e" * 32

        with patch(
            "modules.story.continuity.repositories.EventRepository.count_by_chapter_range",
            autospec=True,
            return_value=0,
        ) as mock_count:
            await list_events(db, novel_id, from_chapter=1, to_chapter=999999)

        count_args = mock_count.await_args.args
        assert count_args[1:] == (db, uuid.UUID(hex=novel_id), 1, 999999)

    async def test_keyset_cursor_and_tail_page_keep_stable_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "f" * 32
        first = _make_event(
            novel_id,
            id=uuid.UUID(int=1),
            chapter_index=2,
            sequence=1,
        )
        second = _make_event(
            novel_id,
            id=uuid.UUID(int=2),
            chapter_index=2,
            sequence=1,
        )
        tail = _make_event(
            novel_id,
            id=uuid.UUID(int=3),
            chapter_index=3,
            sequence=1,
        )

        monkeypatch.setattr(
            "modules.story.continuity.services.MEMORY_EVENT_LIST_BATCH_SIZE",
            2,
        )
        with (
            patch(
                "modules.story.continuity.repositories.EventRepository.count_by_chapter_range",
                autospec=True,
                return_value=3,
            ),
            patch(
                "modules.story.continuity.repositories.EventRepository."
                "get_by_chapter_range_page_after",
                autospec=True,
                side_effect=[[first, second], [tail]],
            ) as mock_page,
        ):
            result = await list_events(
                db,
                novel_id,
                from_chapter=2,
                to_chapter=3,
            )

        assert result.total == 3
        assert [item.id for item in result.items] == [
            str(first.id),
            str(second.id),
            str(tail.id),
        ]
        first_call, tail_call = mock_page.await_args_list
        assert first_call.args[1:] == (db, uuid.UUID(hex=novel_id), 2, 3)
        assert first_call.kwargs == {"after": None, "limit": 2}
        assert tail_call.args[1:] == (db, uuid.UUID(hex=novel_id), 2, 3)
        assert tail_call.kwargs == {
            "after": (second.chapter_index, second.sequence, second.id),
            "limit": 1,
        }


# ============================================================
# API — get_entity_timeline
# ============================================================


@pytest.mark.usefixtures("_stub_memory_active_project_guard")
class TestGetEntityTimeline:
    """GET /api/novels/{novel_id}/memories/events/{entity_id}/timeline"""

    async def test_happy_path_returns_entity_events(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "a" * 32
        entity_id = "0" * 32
        event = _make_event(novel_id)

        with patch(
            "modules.story.continuity.repositories.EventRepository.get_by_entity",
            autospec=True,
            return_value=([event], 1),
        ):
            result = await get_entity_timeline(db, novel_id, entity_id)

        assert isinstance(result, EventListResponse)
        assert result.total == 1
        assert len(result.items) == 1

    async def test_empty_returns_empty_list(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "a" * 32
        entity_id = "1" * 32

        with patch(
            "modules.story.continuity.repositories.EventRepository.get_by_entity",
            autospec=True,
            return_value=([], 0),
        ):
            result = await get_entity_timeline(db, novel_id, entity_id)

        assert result.total == 0
        assert result.items == []

    async def test_pagination_parameters_passed_to_repository(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "a" * 32
        entity_id = "2" * 32

        with patch(
            "modules.story.continuity.repositories.EventRepository.get_by_entity",
            autospec=True,
            return_value=([], 0),
        ) as mock_get:
            await get_entity_timeline(db, novel_id, entity_id, skip=10, limit=20)

        mock_get.assert_awaited_once()
        _args, kwargs = mock_get.await_args
        assert kwargs["skip"] == 10
        assert kwargs["limit"] == 20

    async def test_default_pagination(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "a" * 32
        entity_id = "3" * 32

        with patch(
            "modules.story.continuity.repositories.EventRepository.get_by_entity",
            autospec=True,
            return_value=([], 0),
        ) as mock_get:
            await get_entity_timeline(db, novel_id, entity_id, skip=0, limit=50)

        _args, kwargs = mock_get.await_args
        assert kwargs["skip"] == 0
        assert kwargs["limit"] == 50


# ============================================================
# API — trigger_capture
# ============================================================


@pytest.mark.usefixtures("_stub_memory_active_project_guard")
class TestTriggerCapture:
    """POST /api/novels/{novel_id}/memories/snapshots/capture"""

    async def test_happy_path_returns_snapshot_response(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "l" * 32
        expected = SnapshotResponse(
            id=str(uuid.uuid4()),
            novel_id=novel_id,
            chapter_index=5,
            status="current",
            events_until=3,
        )

        with patch(
            "modules.story.continuity.api._service.capture_snapshot",
            autospec=True,
            return_value=expected,
        ):
            result = await trigger_capture(db, novel_id, 5)

        assert isinstance(result, SnapshotResponse)
        assert result.chapter_index == 5
        assert result.status == "current"
        assert result.events_until == 3

    async def test_service_exception_propagates(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "m" * 32

        with patch(
            "modules.story.continuity.api._service.capture_snapshot",
            autospec=True,
            side_effect=ValueError("capture failed"),
        ):
            with pytest.raises(ValueError, match="capture failed"):
                await trigger_capture(db, novel_id, 1)


# ============================================================
# API — list_snapshots
# ============================================================


@pytest.mark.usefixtures("_stub_memory_active_project_guard")
class TestListSnapshots:
    """GET /api/novels/{novel_id}/memories/snapshots"""

    async def test_happy_path_returns_snapshot_list(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "a" * 32
        snapshot = _make_snapshot(novel_id, chapter_index=3)

        with patch(
            "modules.story.continuity.repositories.SnapshotRepository.list_for_novel",
            autospec=True,
            return_value=[snapshot],
        ):
            result = await list_snapshots(db, novel_id)

        assert isinstance(result, SnapshotListResponse)
        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].chapter_index == 3
        assert result.items[0].status == "current"

    @pytest.mark.parametrize(
        "snapshots,expected_total",
        [
            ([], 0),
            ([_make_snapshot("a" * 32, chapter_index=1)], 1),
            (
                [
                    _make_snapshot("a" * 32, chapter_index=1),
                    _make_snapshot("a" * 32, chapter_index=5),
                ],
                2,
            ),
        ],
    )
    async def test_various_snapshot_counts(self, snapshots, expected_total):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "a" * 32

        with patch(
            "modules.story.continuity.repositories.SnapshotRepository.list_for_novel",
            autospec=True,
            return_value=snapshots,
        ):
            result = await list_snapshots(db, novel_id)

        assert result.total == expected_total
        assert len(result.items) == expected_total


# ============================================================
# API — trigger_rebuild
# ============================================================


@pytest.mark.usefixtures("_stub_memory_active_project_guard")
class TestTriggerRebuild:
    """POST /api/novels/{novel_id}/memories/rebuild"""

    async def test_happy_path_returns_rebuild_result(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "p" * 32
        expected = {
            "rebuilt_snapshots": 3,
            "from_chapter": 2,
            "final_chapter": 10,
        }

        with patch(
            "modules.story.continuity.api._service.full_rebuild",
            autospec=True,
            return_value=expected,
        ):
            result = await trigger_rebuild(db, novel_id, 2)

        assert result == expected
        assert result["rebuilt_snapshots"] == 3
        assert result["from_chapter"] == 2

    async def test_service_exception_propagates(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "q" * 32

        with patch(
            "modules.story.continuity.api._service.full_rebuild",
            autospec=True,
            side_effect=RuntimeError("rebuild failed"),
        ):
            with pytest.raises(RuntimeError, match="rebuild failed"):
                await trigger_rebuild(db, novel_id, 1)


# ============================================================
# API — get_status
# ============================================================


@pytest.mark.usefixtures("_stub_memory_active_project_guard")
class TestGetStatus:
    """GET /api/novels/{novel_id}/memories/status"""

    async def test_happy_path_returns_status(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "r" * 32
        expected = MemoryStatusResponse(
            novel_id=novel_id,
            latest_chapter=7,
            latest_snapshot_chapter=7,
            has_stale=False,
        )

        with patch(
            "modules.story.continuity.api._service.get_status",
            autospec=True,
            return_value=expected,
        ):
            result = await get_status(db, novel_id)

        assert isinstance(result, MemoryStatusResponse)
        assert result.latest_chapter == 7
        assert result.latest_snapshot_chapter == 7
        assert result.has_stale is False

    async def test_no_snapshots_returns_none_chapters(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "s" * 32
        expected = MemoryStatusResponse(
            novel_id=novel_id,
            latest_chapter=None,
            latest_snapshot_chapter=None,
            has_stale=False,
            stale_from_chapter=None,
        )

        with patch(
            "modules.story.continuity.api._service.get_status",
            autospec=True,
            return_value=expected,
        ):
            result = await get_status(db, novel_id)

        assert result.latest_chapter is None
        assert result.latest_snapshot_chapter is None
        assert result.has_stale is False
        assert result.stale_from_chapter is None

    async def test_service_exception_propagates(self):
        db = AsyncMock(spec=AsyncSession)
        novel_id = "t" * 32

        with patch(
            "modules.story.continuity.api._service.get_status",
            autospec=True,
            side_effect=RuntimeError("status error"),
        ):
            with pytest.raises(RuntimeError, match="status error"):
                await get_status(db, novel_id)
