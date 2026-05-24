"""
Review 数据访问层

封装 review_reports 表的所有数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.models import ReviewReport
from shared.constants import DEFAULT_PAGE_SIZE


class ReviewReportRepository:
    """复查报告数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        target_type: str,
        decision: str,
        *,
        target_id: str | None = None,
        score: float | None = None,
        problems: list[dict] | None = None,
        conflict_warnings: list[dict] | None = None,
        early_reveal_warnings: list[dict] | None = None,
        character_knowledge_warnings: list[dict] | None = None,
        duplicate_entity_warnings: list[dict] | None = None,
        geo_warnings: list[dict] | None = None,
        revision_instructions: list[str] | None = None,
    ) -> ReviewReport:
        """创建复查报告"""
        entity = ReviewReport(
            novel_id=novel_id,
            target_type=target_type,
            target_id=target_id,
            decision=decision,
            score=score,
            problems=problems or [],
            conflict_warnings=conflict_warnings or [],
            early_reveal_warnings=early_reveal_warnings or [],
            character_knowledge_warnings=character_knowledge_warnings or [],
            duplicate_entity_warnings=duplicate_entity_warnings or [],
            geo_warnings=geo_warnings or [],
            revision_instructions=revision_instructions or [],
        )
        db.add(entity)
        await db.flush()
        return entity

    async def get(
        self,
        db: AsyncSession,
        report_id: uuid.UUID,
    ) -> ReviewReport | None:
        """根据 ID 获取复查报告"""
        stmt = select(ReviewReport).where(ReviewReport.id == report_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        target_type: str | None = None,
        decision: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[ReviewReport], int]:
        """获取小说的复查报告列表（分页），返回 (items, total)"""
        conditions = [ReviewReport.novel_id == novel_id]
        if target_type:
            conditions.append(ReviewReport.target_type == target_type)
        if decision:
            conditions.append(ReviewReport.decision == decision)

        # 计数
        count_stmt = select(ReviewReport.id).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = len(count_result.all())

        # 分页查询
        stmt = (
            select(ReviewReport)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(desc(ReviewReport.created_at))
        )
        result = await db.execute(stmt)
        items: Sequence[ReviewReport] = result.scalars().all()
        return list(items), total

    async def delete_old(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        target_type: str,
        *,
        keep_last: int = 10,
    ) -> int:
        """保留最近的 N 条报告，删除更旧的（释放空间）

        Args:
            db: 数据库 session
            novel_id: 项目 ID
            target_type: 复查目标类型
            keep_last: 保留最近多少条

        Returns:
            int: 删除的记录数
        """
        stmt = (
            select(ReviewReport.id)
            .where(
                ReviewReport.novel_id == novel_id,
                ReviewReport.target_type == target_type,
            )
            .order_by(desc(ReviewReport.created_at))
            .offset(keep_last)
        )
        result = await db.execute(stmt)
        old_ids = [row[0] for row in result.all()]

        if not old_ids:
            return 0

        from sqlalchemy import delete as delete_stmt
        del_stmt = delete_stmt(ReviewReport).where(
            ReviewReport.id.in_(old_ids),
        )
        del_result = await db.execute(del_stmt)
        await db.flush()
        return del_result.rowcount
