"""Outline 任务处理器测试

测试章节卡提取、剧情结构生成等后台任务的行为。
使用 mock 隔离 LLM 调用，只验证编排逻辑。
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.outline.schemas import ChapterCardCreate
from modules.outline.services import ChapterCardService
from modules.outline.tasks import handle_chapter_card_extraction
from modules.writing.facade import create_draft as _create_writing_draft
from modules.writing.schemas import WritingDraftCreate


@pytest.fixture
def card_service() -> ChapterCardService:
    return ChapterCardService()


class _MockExtractedCard:
    """模拟 _ExtractedChapterCard 返回值"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestChapterCardExtraction:
    """章节卡提取任务测试"""

    @pytest.mark.asyncio
    async def test_skip_existing_and_no_draft(
        self,
        db_session: AsyncSession,
        card_service: ChapterCardService,
    ) -> None:
        """测试已有章节卡和无正文的章节被跳过"""
        novel_id = str(uuid.uuid4())

        # 创建正文草稿：第1-3章
        for ch in (1, 2, 3):
            data = WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=ch,
                title=f"第{ch}章",
                content=f"第{ch}章正文内容。",
            )
            await _create_writing_draft(db_session, data)

        # 为第1章创建章节卡（应被跳过）
        card_data = ChapterCardCreate(
            chapter_index=1,
            title="第1章",
            chapter_goal="已有目标",
            main_conflict="已有冲突",
        )
        await card_service.create(db_session, novel_id, card_data)

        # 创建 mock task（第4章无正文 → 应跳过）
        task = AsyncTask(
            task_type="chapter_card_extraction",
            meta={"novel_id": novel_id, "start_chapter": 1, "end_chapter": 4},
        )
        task.mark_running()
        db_session.add(task)
        await db_session.flush()

        mock_card = _MockExtractedCard(
            chapter_goal="提取目标",
            main_conflict="提取冲突",
            emotional_point=None,
            ending_hook=None,
            scene_cards=[],
            must_happen=["事件A"],
            must_not_happen=[],
            visible_progress=[],
            hidden_progress=[],
        )

        with patch(
            "modules.outline.tasks._extract_single_chapter_card", return_value=mock_card
        ):
            result = await handle_chapter_card_extraction(db_session, task)

        assert result["total"] == 4
        assert result["skipped_no_draft"] == 1  # 第4章
        assert result["skipped_has_card"] == 1  # 第1章
        assert result["created"] == 2  # 第2-3章
        assert len(result["errors"]) == 0

        # 验证卡数量
        cards = await card_service.list(db_session, novel_id)
        assert cards.total == 3  # 1(原有) + 2(新建)

    @pytest.mark.asyncio
    async def test_empty_range(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试空章节范围"""
        novel_id = str(uuid.uuid4())

        task = AsyncTask(
            task_type="chapter_card_extraction",
            meta={"novel_id": novel_id, "start_chapter": 5, "end_chapter": 3},
        )
        task.mark_running()
        db_session.add(task)
        await db_session.flush()

        result = await handle_chapter_card_extraction(db_session, task)
        assert result["total"] == -1  # end < start
        assert result["created"] == 0

    @pytest.mark.asyncio
    async def test_progress_tracking(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试进度更新"""
        novel_id = str(uuid.uuid4())

        for ch in (1, 2):
            data = WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=ch,
                title=f"第{ch}章",
                content=f"第{ch}章正文。",
            )
            await _create_writing_draft(db_session, data)

        task = AsyncTask(
            task_type="chapter_card_extraction",
            meta={"novel_id": novel_id, "start_chapter": 1, "end_chapter": 2},
        )
        task.mark_running()
        db_session.add(task)
        await db_session.flush()

        mock_card = _MockExtractedCard(
            chapter_goal="目标",
            main_conflict="冲突",
            emotional_point=None,
            ending_hook=None,
            scene_cards=[],
            must_happen=[],
            must_not_happen=[],
            visible_progress=[],
            hidden_progress=[],
        )

        with patch(
            "modules.outline.tasks._extract_single_chapter_card", return_value=mock_card
        ):
            result = await handle_chapter_card_extraction(db_session, task)

        assert result["created"] == 2
        assert task.progress == 1.0
