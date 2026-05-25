"""
Import ORM 模型

对应 import_records 表。
记录每次文件导入的操作元信息，不存储正文内容。
"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin


class ImportRecord(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """导入记录 — 记录每次文件导入的结果"""

    __tablename__ = "import_records"
    __table_args__ = {"comment": "小说文件导入记录"}

    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="原始文件名",
    )
    file_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="文件类型：txt/epub/html/mobi",
    )
    file_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="文件大小（字节）",
    )
    total_chapters: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="解析出的章节总数",
    )
    imported_chapters: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="成功导入的章节数",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        comment="状态：pending/processing/done/failed",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息（status=failed 时填充）",
    )

    def __repr__(self) -> str:
        return (
            f"<ImportRecord id={self.id} file={self.file_name!r} "
            f"type={self.file_type} status={self.status}>"
        )
