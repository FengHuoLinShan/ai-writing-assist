"""
Import Pydantic Schema

定义导入模块的请求/响应数据结构。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ImportChapterItem(BaseModel):
    """导入后已保存的章节信息"""

    chapter_index: int = Field(..., description="章节索引")
    title: str | None = Field(None, description="章节标题")
    word_count: int = Field(0, description="字数")
    draft_id: str = Field(..., description="关联草稿 ID")


class ImportResponse(BaseModel):
    """导入记录响应"""

    id: str = Field(..., description="导入记录 ID")
    novel_id: str = Field(..., description="小说项目 ID")
    file_name: str = Field(..., description="原始文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(0, description="文件大小")
    total_chapters: int = Field(0, description="解析章节数")
    imported_chapters: int = Field(0, description="成功导入数")
    status: str = Field(..., description="状态")
    error_message: str | None = Field(None, description="错误信息")
    created_at: datetime | None = Field(None, description="创建时间")
    chapters: list[ImportChapterItem] = Field(
        default_factory=list,
        description="本次导入后已保存为草稿的章节",
    )


class ImportListResponse(BaseModel):
    """导入记录列表响应"""

    items: list[ImportResponse]
    total: int


class ImportedChapterResponse(BaseModel):
    """已导入章节响应"""

    id: str = Field(..., description="章节 ID")
    novel_id: str = Field(..., description="小说项目 ID")
    import_record_id: str = Field(..., description="导入记录 ID")
    chapter_index: int = Field(..., description="章节序号")
    title: str = Field(..., description="章节标题")
    content: str = Field(..., description="章节正文")
    is_analyzed: bool = Field(False, description="是否已分析")
    created_at: datetime | None = Field(None, description="创建时间")


class ImportedChapterListResponse(BaseModel):
    """已导入章节列表响应"""

    items: list[ImportedChapterResponse]
    total: int
