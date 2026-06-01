"""Memory Facade 公共外观测试 — Round 4"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory import facade


class TestFacadeGetChapterPanorama:
    """get_chapter_panorama delegate 验证"""

    @pytest.mark.asyncio
    async def test_delegates_to_service(self) -> None:
        """验证参数透传"""
        with patch("modules.memory.facade._service.get_panorama", new_callable=AsyncMock) as mock_method:
            mock_method.return_value = object()
            db = AsyncMock(spec=AsyncSession)
            await facade.get_chapter_panorama(db, "novel-1", 5)
            mock_method.assert_called_once_with(db, "novel-1", 5)


class TestFacadeRecordEvents:
    """record_events delegate 验证"""

    @pytest.mark.asyncio
    async def test_delegates_to_service(self) -> None:
        """验证事件数据透传"""
        with patch("modules.memory.facade._service.record_events", new_callable=AsyncMock) as mock_method:
            mock_method.return_value = []
            db = AsyncMock(spec=AsyncSession)
            events = [{"event_type": "entity_created", "entity_id": str(uuid.uuid4())}]
            await facade.record_events(db, "novel-1", 3, events)
            mock_method.assert_called_once_with(db, "novel-1", 3, events)


class TestFacadeCaptureSnapshot:
    """capture_snapshot delegate 验证"""

    @pytest.mark.asyncio
    async def test_delegates_to_service(self) -> None:
        """验证 chapter_index 透传"""
        with patch("modules.memory.facade._service.capture_snapshot", new_callable=AsyncMock) as mock_method:
            mock_method.return_value = object()
            db = AsyncMock(spec=AsyncSession)
            await facade.capture_snapshot(db, "novel-1", 10)
            mock_method.assert_called_once_with(db, "novel-1", 10)


class TestFacadeMarkStale:
    """mark_stale delegate 验证"""

    @pytest.mark.asyncio
    async def test_delegates_to_service(self) -> None:
        """验证 from_chapter 透传"""
        with patch("modules.memory.facade._service.mark_stale", new_callable=AsyncMock) as mock_method:
            mock_method.return_value = {"stale_count": 2, "from_chapter": 5}
            db = AsyncMock(spec=AsyncSession)
            result = await facade.mark_stale(db, "novel-1", 5)
            assert result["stale_count"] == 2
            mock_method.assert_called_once_with(db, "novel-1", 5)


class TestFacadeFullRebuild:
    """full_rebuild delegate 验证"""

    @pytest.mark.asyncio
    async def test_delegates_to_service(self) -> None:
        """验证 from_chapter 透传"""
        with patch("modules.memory.facade._service.full_rebuild", new_callable=AsyncMock) as mock_method:
            mock_method.return_value = {"rebuilt_snapshots": 3, "from_chapter": 5, "final_chapter": 15}
            db = AsyncMock(spec=AsyncSession)
            result = await facade.full_rebuild(db, "novel-1", 5)
            assert result["rebuilt_snapshots"] == 3
            mock_method.assert_called_once_with(db, "novel-1", 5)


class TestFacadeGetStatus:
    """get_status delegate 验证"""

    @pytest.mark.asyncio
    async def test_delegates_to_service(self) -> None:
        """验证 novel_id 透传"""
        with patch("modules.memory.facade._service.get_status", new_callable=AsyncMock) as mock_method:
            from modules.memory.schemas import MemoryStatusResponse
            mock_method.return_value = MemoryStatusResponse(novel_id="novel-1")
            db = AsyncMock(spec=AsyncSession)
            result = await facade.get_status(db, "novel-1")
            assert result.novel_id == "novel-1"
            mock_method.assert_called_once_with(db, "novel-1")
