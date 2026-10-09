"""滚动规划的已规划章覆盖只读缝（BR-6 流程侧补窗检查用）。

跨模块消费者（引导流程）经 facade 读取"前方已规划章数"，不接触 story ORM
模型；SQLAlchemy 查询在 ``planning_window_service`` 实现，facade 仅适配与
委托。只读，不写回、不重复判断领域门禁。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.outline_state.planning_window_service import (
    planned_chapter_coverage,
)


async def get_planned_chapter_coverage(
    db: AsyncSession,
    novel_id: str,
    *,
    start_chapter: int,
    end_chapter: int,
) -> dict[str, Any]:
    """统计 ``[start_chapter, end_chapter]`` 内已被已采用规划覆盖的章节。

    返回 ``{"chapters": 升序覆盖章号, "arc_count": 篇章数,
    "planned_scene_count": 计划 Scene 数, "thread_count": 剧情线数}``；
    窗口无效（结束早于起始）时返回空覆盖。
    """
    return await planned_chapter_coverage(
        db,
        novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )
