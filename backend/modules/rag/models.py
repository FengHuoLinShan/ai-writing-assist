"""
RAG ORM 模型

对应数据库 rag_chunks 表。
RagChunk 存储从小说知识库和正文中提取的文本片段、embedding 向量及关联元数据。
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin


class RagChunk(Base, UUIDMixin, TimestampMixin):
    """RAG 文本片段 — 语义检索的基本单元"""

    __tablename__ = "rag_chunks"

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属小说项目 ID",
    )
    source_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="来源类型（chapter_text / world_entity / character / memory / outline 等）",
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="来源对象 ID（可为空，如批量导入文本）",
    )
    chapter_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="关联章节索引（从 1 开始）",
    )
    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="片段文本内容",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="片段摘要（可选，用于检索预览）",
    )
    entity_ids: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联的世界对象 ID 列表",
    )
    character_ids: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联的人物 ID 列表",
    )
    thread_ids: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联的剧情线 ID 列表",
    )
    visibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="author_only",
        comment="信息可见性（author_only / author_safe / reader_known / public）",
    )
    importance: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        comment="重要性评分（0.0-1.0），越高越关键",
    )
    embedding: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
        comment="Embedding 向量（暂存为 bytes，生产环境用 pgvector Vector 类型）",
    )
    meta: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="扩展元数据（可存储额外过滤条件、来源位置等）",
    )

    def __repr__(self) -> str:
        return (
            f"<RagChunk id={self.id} source_type={self.source_type!r}"
            f" importance={self.importance}>"
        )
