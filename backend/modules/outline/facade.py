"""
Outline Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.schemas import (
    ChapterCardCandidateItem,
    ChapterCardContext,
    OutlineArcContext,
    OutlineArcCreate,
    OutlineArcResponse,
    OutlineArcUpdate,
    PlotThreadContext,
    PlotThreadCreate,
    PlotThreadResponse,
    PlotThreadUpdate,
)
from modules.outline.services import (
    ChapterCardService,
    OutlineArcService,
    PlotGenerationService,
    PlotThreadService,
)

_thread_service = PlotThreadService()
_arc_service = OutlineArcService()
_chapter_service = ChapterCardService()
_plot_generation = PlotGenerationService()


async def create_thread(
    db: AsyncSession,
    novel_id: str,
    data: PlotThreadCreate,
) -> PlotThreadResponse:
    """创建剧情线"""
    return await _thread_service.create(db, novel_id, data)


async def update_thread(
    db: AsyncSession,
    thread_id: str,
    data: PlotThreadUpdate,
    novel_id: str,
) -> PlotThreadResponse:
    """更新剧情线"""
    return await _thread_service.update(db, thread_id, data, novel_id)


async def create_arc(
    db: AsyncSession,
    novel_id: str,
    data: OutlineArcCreate,
) -> OutlineArcResponse:
    """创建篇章纲"""
    return await _arc_service.create(db, novel_id, data)


async def update_arc(
    db: AsyncSession,
    arc_id: str,
    data: OutlineArcUpdate,
    novel_id: str,
) -> OutlineArcResponse:
    """更新篇章纲"""
    return await _arc_service.update(db, arc_id, data, novel_id)


async def list_thread_summaries(
    db: AsyncSession,
    novel_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """获取剧情线摘要列表（id, name, thread_type, summary 等）

    供其他模块注入 LLM 上下文，非完整 CRUD 查询。
    """
    return await _thread_service.list_summaries(db, novel_id, limit=limit)


async def list_arc_summaries(
    db: AsyncSession,
    novel_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """获取篇章纲摘要列表（id, title, start_chapter, end_chapter）"""
    return await _arc_service.list_summaries(db, novel_id, limit=limit)


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
    return await _arc_service.get_arc_context(db, arc_id, novel_id)


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


async def generate_plot_structure(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> dict:
    """生成剧情结构

    读取章节正文 → 调用 LLM → 持久化剧情线和篇章纲。
    供 imports/workflow.py 等跨模块调用。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        start_chapter: 起始章节
        end_chapter: 结束章节

    Returns:
        dict — {total_threads, total_arcs, threads, arcs}
    """
    return await _plot_generation.generate(db, novel_id, start_chapter, end_chapter)
