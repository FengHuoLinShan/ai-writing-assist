"""
集成测试：章节卡生成

流程：
创建剧情线 → 创建篇章纲 → create_from_candidate → schema 校验 → 章节卡包含目标/冲突
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class TestChapterCardGenerationFlow:
    """AI长篇小说结构化创作引擎_REVIEW_RULES_v1.0 §19.2 流程3"""

    async def test_chapter_card_from_candidate(
        self, db_session: AsyncSession, test_project_id: str,
    ):
        nid_str = test_project_id

        # Step 1: 创建剧情线
        from modules.outline.schemas import PlotThreadCreate
        from modules.outline.services import PlotThreadService

        thread_service = PlotThreadService()
        thread = await thread_service.create(
            db_session, nid_str,
            PlotThreadCreate(
                name="旧王都真相线",
                thread_type="main",
                summary="主角寻找真相",
            ),
        )

        # Step 2: 创建篇章纲
        from modules.outline.schemas import OutlineArcCreate
        from modules.outline.services import OutlineArcService

        arc_service = OutlineArcService()
        arc = await arc_service.create(
            db_session, nid_str,
            OutlineArcCreate(
                title="档案馆篇",
                arc_index=1,
                start_chapter=1,
                end_chapter=10,
                arc_goal="找到档案",
                core_conflict="监察院阻止",
                climax="发现档案被替换",
                result="获得线索",
            ),
        )

        # Step 3: 批量创建章节卡
        from modules.outline.schemas import ChapterCardCandidateItem, ChapterCardFromCandidateRequest
        from modules.outline.services import ChapterCardService

        chapter_service = ChapterCardService()
        cards = await chapter_service.create_from_candidate(
            db_session, nid_str,
            [
                ChapterCardCandidateItem(
                    chapter_index=1,
                    title="神秘印章",
                    chapter_goal="引入主角",
                    main_conflict="主角获得异常物品",
                    emotional_point="好奇",
                    must_happen=["主角得到印章"],
                    must_not_happen=["揭示印章完整用途"],
                    ending_hook="印章发热",
                ),
                ChapterCardCandidateItem(
                    chapter_index=2,
                    title="档案迷踪",
                    chapter_goal="建立目标",
                    main_conflict="发现档案被篡改",
                    emotional_point="困惑",
                    must_not_happen=["女主知道真相"],
                    ending_hook="缺页的档案",
                ),
            ],
        )

        # Step 4: 验证返回结果
        assert len(cards) == 2, f"期望 2 张章节卡，收到 {len(cards)}"

        # Step 5: 验证每张章节卡包含核心字段
        for i, card in enumerate(cards):
            assert card.chapter_index == i + 1
            assert card.chapter_goal, f"章节卡 {i+1} 应包含 chapter_goal"
            assert card.main_conflict, f"章节卡 {i+1} 应包含 main_conflict"
            assert card.ending_hook, f"章节卡 {i+1} 应包含 ending_hook"

    async def test_from_candidate_empty_returns_empty(
        self, db_session: AsyncSession, test_project_id: str,
    ):
        from modules.outline.services import ChapterCardService

        chapter_service = ChapterCardService()
        cards = await chapter_service.create_from_candidate(
            db_session, test_project_id, [],
        )
        assert cards == [], "空输入应返回空列表"

    async def test_from_candidate_missing_required_fields(
        self, db_session: AsyncSession, test_project_id: str,
    ):
        """缺少 chapter_goal / main_conflict 的候选应被拒绝"""
        from modules.outline.schemas import ChapterCardCandidateItem
        from modules.outline.services import ChapterCardService

        chapter_service = ChapterCardService()
        # ChapterCardCandidateItem validates required fields on construction
        # So missing fields will raise pydantic error - test expects this
        import pytest
        with pytest.raises((ValueError, Exception)):
            ChapterCardCandidateItem(
                chapter_index=1,
                title="无目标章节",
            )
