"""
Review ORM 模型

对应 1 张数据库表：
- review_reports: 结构复查报告
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, String
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin


class ReviewReport(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """结构复查报告

    记录对某个结构化创作候选的复查结果。
    包含多个检查维度的警告列表和最终的决策。
    Review 不修改正史，只输出问题与修改建议。
    """

    __tablename__ = "review_reports"
    __table_args__ = {"comment": "结构复查报告"}

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="canonical",
        comment="报告状态：draft/canonical/deprecated",
    )

    target_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="复查目标类型：world_structure/plot_structure/chapter_cards/memory_update/entity_candidates",
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="复查目标 ID",
    )
    decision: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="复查决策：pass/minor_revision/major_revision/reject",
    )
    score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="综合评分（0.0 - 1.0，可选）",
    )
    problems: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="问题列表（JSONB）",
    )
    conflict_warnings: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="冲突警告列表（JSONB）",
    )
    early_reveal_warnings: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="提前揭示警告列表（JSONB）",
    )
    character_knowledge_warnings: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="人物知识边界警告列表（JSONB）",
    )
    duplicate_entity_warnings: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="对象重复警告列表（JSONB）",
    )
    geo_warnings: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="地理冲突警告列表（JSONB）",
    )
    revision_instructions: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="修改建议列表（JSONB）",
    )

    def __repr__(self) -> str:
        return (
            f"<ReviewReport id={self.id} "
            f"target={self.target_type} "
            f"decision={self.decision}>"
        )
