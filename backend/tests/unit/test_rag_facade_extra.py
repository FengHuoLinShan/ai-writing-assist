"""RAG facade index_chapter_with_report unit tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.contracts import RagIndexReport
from modules.evidence.facade import index_chapter_with_report


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

        with patch(
            "modules.evidence.indexing.facade._indexing", autospec=True
        ) as mock_indexing:
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

        with patch(
            "modules.evidence.indexing.facade._indexing", autospec=True
        ) as mock_indexing:
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

        with patch(
            "modules.evidence.indexing.facade._indexing", autospec=True
        ) as mock_indexing:
            mock_indexing.index_chapter_with_report = AsyncMock(return_value=report)

            # Act
            await index_chapter_with_report(db, novel_id, 1)

            # Assert
            args = mock_indexing.index_chapter_with_report.await_args
            assert args[0][1] == expected_uuid
