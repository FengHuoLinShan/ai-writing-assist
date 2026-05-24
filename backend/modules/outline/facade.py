"""
Outline Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.schemas import (
    ChapterCardCandidateItem,
    ChapterCardContext,
    OutlineArcContext,
    PlotThreadContext,
)
from modules.outline.services import (
    ChapterCardService,
    OutlineArcService,
    PlotThreadService,
)

_thread_service = PlotThreadService()
_arc_service = OutlineArcService()
_chapter_service = ChapterCardService()


async def get_chapter_card(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> ChapterCardContext | None:
    """按章节索引获取章节卡上下文

    供其他模块（context、review 等）获取指定章节的章节卡信息。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        chapter_index: 章节序号

    Returns:
        ChapterCardContext | None — 章节卡上下文，不存在返回 None
    """
    return await _chapter_service.get_chapter_card_context(
        db, novel_id, chapter_index,
    )


async def get_active_threads(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int | None = None,
    limit: int = 20,
) -> list[PlotThreadContext]:
    """获取指定章节的活跃剧情线

    返回在指定章节仍活跃的剧情线（已开始且计划收束章节未到）。
    如未指定章节索引，返回所有 canonical/draft 状态的剧情线。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        chapter_index: 可选，当前章节索引
        limit: 最大返回数量

    Returns:
        list[PlotThreadContext] — 活跃剧情线列表
    """
    return await _thread_service.get_active_threads(
        db, novel_id,
        chapter_index=chapter_index,
        limit=limit,
    )


async def get_arc_context(
    db: AsyncSession,
    novel_id: str,
    arc_id: str,
) -> OutlineArcContext:
    """获取篇章纲上下文

    供其他模块获取指定篇章的详细信息。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        arc_id: 篇章 ID

    Returns:
        OutlineArcContext — 篇章纲上下文

    Raises:
        HTTPException 404: 篇章不存在
    """
    return await _arc_service.get_arc_context(db, arc_id)


async def create_chapter_cards_from_candidate(
    db: AsyncSession,
    novel_id: str,
    candidate_payload: dict,
) -> list[ChapterCardContext]:
    """从候选数据批量创建章节卡

    将 AI 生成的候选章节卡批量入库。
    如果同章节已存在章节卡则跳过。
    所有创建的章节卡状态为 'candidate'，等待结构复查和用户确认。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        candidate_payload: 候选载荷，包含 {"cards": [...]}
            每个 card 包含 chapter_index, chapter_goal, main_conflict 等字段

    Returns:
        list[ChapterCardContext] — 成功创建的章节卡上下文列表
    """
    raw_cards = candidate_payload.get("cards", [])
    items = [ChapterCardCandidateItem(**card) for card in raw_cards]
    return await _chapter_service.create_from_candidate(
        db, novel_id, items,
    )
