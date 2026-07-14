"""
RAG Facade 单元测试 — index_chapter_with_report / index_chapter_incremental

使用 mock 隔离 IndexingService，不依赖真实数据库。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.contracts import RagIndexReport
from modules.rag.facade import (
    index_chapter_incremental,
    index_chapter_with_report,
)


class TestIndexChapterWithReport:
    """index_chapter_with_report 单元测试"""

    @pytest.mark.asyncio
    async def test_index_chapter_with_report_happy_path_returns_report(self):
        # Arrange
        expected = RagIndexReport(
            chapter_index=3,
            chunks_created=7,
            warnings=[],
            embedding_failed_count=0,
            chunks_created_ids=["id-1", "id-2"],
        )
        db = AsyncMock(spec=AsyncSession)
        novel_id = "a" * 32

        with patch("modules.rag.facade._indexing", autospec=True) as mock_indexing:
            mock_indexing.index_chapter_with_report = AsyncMock(return_value=expected)

            # Act
            result = await index_chapter_with_report(db, novel_id, 3)

            # Assert
            assert result is expected
            mock_indexing.index_chapter_with_report.assert_awaited_once_with(
                db, uuid.UUID(hex=novel_id), 3, content_mode="canonical"
            )

    @pytest.mark.asyncio
    async def test_index_chapter_with_report_service_exception_propagates(self):
        # Arrange
        db = AsyncMock(spec=AsyncSession)
        novel_id = "b" * 32

        with patch("modules.rag.facade._indexing", autospec=True) as mock_indexing:
            mock_indexing.index_chapter_with_report = AsyncMock(
                side_effect=RuntimeError("indexing failed")
            )

            # Act / Assert
            with pytest.raises(RuntimeError, match="indexing failed"):
                await index_chapter_with_report(db, novel_id, 1)

    @pytest.mark.asyncio
    async def test_index_chapter_with_report_converts_novel_id_to_uuid(self):
        # Arrange
        db = AsyncMock(spec=AsyncSession)
        novel_id = "deadbeef" * 4  # 32 hex chars
        expected_uuid = uuid.UUID(hex=novel_id)
        report = RagIndexReport(chapter_index=1)

        with patch("modules.rag.facade._indexing", autospec=True) as mock_indexing:
            mock_indexing.index_chapter_with_report = AsyncMock(return_value=report)

            # Act
            await index_chapter_with_report(db, novel_id, 1)

            # Assert
            args = mock_indexing.index_chapter_with_report.await_args
            assert args[0][1] == expected_uuid


class TestIndexChapterIncremental:
    """index_chapter_incremental 单元测试"""

    @pytest.mark.asyncio
    async def test_index_chapter_incremental_happy_path_returns_report(self):
        # Arrange
        expected = RagIndexReport(
            chapter_index=2,
            chunks_created=5,
            warnings=[],
            embedding_failed_count=0,
            chunks_created_ids=["id-3"],
        )
        db = AsyncMock(spec=AsyncSession)
        novel_id = "c" * 32
        old_content = "旧内容"
        new_content = "新内容"

        with patch("modules.rag.facade._indexing", autospec=True) as mock_indexing:
            mock_indexing.index_chapter_incremental = AsyncMock(return_value=expected)

            # Act
            result = await index_chapter_incremental(
                db, novel_id, 2, old_content, new_content
            )

            # Assert
            assert result is expected
            mock_indexing.index_chapter_incremental.assert_awaited_once_with(
                db, uuid.UUID(hex=novel_id), 2, old_content, new_content
            )

    @pytest.mark.asyncio
    async def test_index_chapter_incremental_service_exception_propagates(self):
        # Arrange
        db = AsyncMock(spec=AsyncSession)
        novel_id = "d" * 32

        with patch("modules.rag.facade._indexing", autospec=True) as mock_indexing:
            mock_indexing.index_chapter_incremental = AsyncMock(
                side_effect=ValueError("content mismatch")
            )

            # Act / Assert
            with pytest.raises(ValueError, match="content mismatch"):
                await index_chapter_incremental(db, novel_id, 1, "old", "new")

    @pytest.mark.asyncio
    async def test_index_chapter_incremental_converts_novel_id_to_uuid(self):
        # Arrange
        db = AsyncMock(spec=AsyncSession)
        novel_id = "cafebabe" * 4
        expected_uuid = uuid.UUID(hex=novel_id)
        report = RagIndexReport(chapter_index=5)

        with patch("modules.rag.facade._indexing", autospec=True) as mock_indexing:
            mock_indexing.index_chapter_incremental = AsyncMock(return_value=report)

            # Act
            await index_chapter_incremental(db, novel_id, 5, "old", "new")

            # Assert
            args = mock_indexing.index_chapter_incremental.await_args
            assert args[0][1] == expected_uuid
