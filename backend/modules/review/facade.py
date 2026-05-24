"""
Review Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.schemas import ReviewReportContext
from modules.review.services import ReviewService

_service = ReviewService()


async def review_structure_candidate(
    db: AsyncSession,
    novel_id: str,
    target_type: str,
    candidate_payload: dict[str, Any],
) -> ReviewReportContext:
    """提交一个结构化候选进行复查

    对 AI 生成的结构化候选（世界对象、剧情结构、章节卡等）
    执行全维度复查，返回复查报告。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        target_type: 复查目标类型
            world_structure / plot_structure / chapter_cards /
            memory_update / entity_candidates / geo_structure
        candidate_payload: 候选结构数据

    Returns:
        ReviewReportContext — 复查报告，包含决策和所有警告
    """
    return await _service.run_all_checks(
        db, novel_id, target_type, candidate_payload,
    )


async def get_review_report(
    db: AsyncSession,
    review_id: str,
    novel_id: str,
) -> ReviewReportContext:
    """获取已存在的复查报告

    Args:
        db: 数据库 session
        review_id: 复查报告 ID
        novel_id: 项目 ID

    Returns:
        ReviewReportContext — 复查报告

    Raises:
        HTTPException 404: 报告不存在
    """
    return await _service.get_report(db, review_id, novel_id)
