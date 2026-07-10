"""
RAG ORM 模型

对应数据库 rag_chunks 表。
RagChunk 存储从小说知识库和正文中提取的文本片段、embedding 向量及关联元数据。
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin

# 尝试导入 pgvector Vector 类型；不可用时回退
try:
    from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]

    _HAS_PGVECTOR = True
except ImportError:
    _HAS_PGVECTOR = False


def _embedding_column(dim: int = 768):
    """返回 pgvector Vector 列或 LargeBinary 回退列（用于 SQLite 测试）"""
    if _HAS_PGVECTOR:
        return mapped_column(Vector(dim), nullable=True)
    return mapped_column(LargeBinary, nullable=True)


class RagChunk(Base, UUIDMixin, TimestampMixin):
    """RAG 文本片段 — 语义检索的基本单元"""

    __tablename__ = "rag_chunks"
    __table_args__ = (
        Index(
            "ix_rag_chunks_novel_source_chapter_order",
            "novel_id",
            "source_type",
            "chapter_index",
            "chunk_index",
            "id",
        ),
    )

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
        comment=(
            "来源类型（chapter_text / world_entity / character / memory / outline 等）"
        ),
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="来源对象 ID（可为空，如批量导入文本）",
    )
    content_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="canonical",
        index=True,
        comment="正文索引视图：canonical / working",
    )
    source_content_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="建立该 chunk 时的正文版本 hash",
    )
    chapter_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="关联章节索引（从 1 开始）",
    )
    chunk_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="章节内 chunk 序号（从 0 开始）",
    )
    start_offset: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="chunk 在原始章节正文中的起始字符位置",
    )
    end_offset: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="chunk 在原始章节正文中的结束字符位置",
    )
    char_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="chunk 正文字符数",
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
    scene_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="关联的 Scene ID（根据 scene_chunks 区间近似匹配）",
    )
    scene_span_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="关联的 SceneSpan ID（outline 派生读模型，无跨模块 FK）",
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
    index_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="legacy",
        comment="RAG 索引版本",
    )
    embedding_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        comment="embedding 状态：pending/pending_vectorization/succeeded/failed/skipped",
    )
    embedding_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="embedding 失败原因",
    )
    index_warnings: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="索引过程告警",
    )
    embedding = _embedding_column()
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


class RagIndexState(Base, UUIDMixin, TimestampMixin):
    """Coalesced, rebuildable chapter index state for one content mode."""

    __tablename__ = "rag_index_state"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "chapter_index",
            "content_mode",
            name="uq_rag_index_state_chapter_mode",
        ),
        {"comment": "RAG 章节索引请求与新鲜度状态"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    requested_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexed_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    indexed_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
