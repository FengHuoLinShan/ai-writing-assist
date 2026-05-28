"""
Memory ORM 模型

包含：
- MemoryRecord: memory_records 表 — 正史长期记忆
- MemoryUpdateProposal: memory_update_proposals 表 — AI 生成的候选记忆
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin


class MemoryRecord(Base, UUIDMixin, NovelMixin, TimestampMixin):
    """长期记忆记录 — 正史状态变化历史"""

    __tablename__ = "memory_records"

    memory_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="记忆类型（chapter_state / event / character_state / knowledge / foreshadowing / resource / outline_drift / geo_history）",
    )
    target_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="关联目标类型（entity / character / thread / location）",
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="关联目标 ID",
    )
    chapter_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="所属章节索引（从 1 开始）",
    )
    title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="记忆标题",
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="记忆摘要（必填）",
    )
    content_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="详细内容（结构化 JSON）",
    )
    visibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="reader_known",
        comment="读者可见性（author_only / author_safe / reader_known / public）",
    )
    known_by_character_ids: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="已知该记忆的角色 ID 列表",
    )
    related_entity_ids: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联世界对象 ID 列表",
    )
    related_character_ids: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联角色 ID 列表",
    )
    related_thread_ids: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联剧情线 ID 列表",
    )
    importance: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        comment="重要性（0.0 ~ 1.0）",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="canonical",
        index=True,
        comment="状态（canonical / deprecated）",
    )
    source_text_excerpt: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="来源文本摘录",
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryRecord id={self.id} type={self.memory_type!r} "
            f"chapter={self.chapter_index}>"
        )


class MemoryUpdateProposal(Base, UUIDMixin, NovelMixin, TimestampMixin):
    """记忆更新候选 — AI 生成的 proposal，待用户确认"""

    __tablename__ = "memory_update_proposals"

    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="关联章节卡 ID",
    )
    chapter_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="关联章节索引",
    )
    proposal_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="提案类型（create_memory / update_memory / update_character_state / update_knowledge / add_timeline_event / update_foreshadowing）",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        comment="提案内容（结构化 JSON，确认后据此写入正史）",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        comment="AI 置信度（0.0 ~ 1.0）",
    )
    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="AI 提案理由",
    )
    source_text_excerpt: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="来源文本摘录",
    )
    decision: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        comment="用户决策（pending / approved / rejected）",
    )
    decided_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="决策者标识",
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="决策时间",
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryUpdateProposal id={self.id} type={self.proposal_type!r} "
            f"decision={self.decision!r}>"
        )
