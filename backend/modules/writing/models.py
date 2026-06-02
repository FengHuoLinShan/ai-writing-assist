"""
Writing ORM 模型

对应数据库 writing_drafts 表。
存储人工正文草稿，支持版本管理。
"""

from __future__ import annotations

from sqlalchemy import Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin


class WritingDraft(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """正文草稿 — 手工写作的正文承载"""

    __tablename__ = "writing_drafts"
    __table_args__ = (
        UniqueConstraint(
            "novel_id", "chapter_index", "version_number",
            name="uq_writing_draft_version",
        ),
        {"comment": "正文草稿"},
    )

    chapter_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="章节索引",
    )
    title: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="草稿标题",
    )
    content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="草稿正文",
    )
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="版本号（从 1 递增）",
    )

    def __repr__(self) -> str:
        return (
            f"<WritingDraft id={self.id} novel={self.novel_id} "
            f"ch={self.chapter_index} v{self.version_number}>"
        )
