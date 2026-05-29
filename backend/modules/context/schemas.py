"""
Context Pydantic Schema 定义

用于 API 请求/响应校验。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ContextCompileRequest(BaseModel):
    """上下文编译请求"""

    novel_id: str = Field(..., description="项目 ID (UUID hex string)")
    task: str = Field(..., description="创作任务描述，如「生成章节卡」、「生成剧情线」")
    scope: str = Field(
        ..., description="编译范围: project / world / world_character / arc / chapter / full",
    )
    chapter_index: int | None = Field(
        None, ge=0, description="当前章节索引（scope=chapter 时必填）",
    )
    arc_id: str | None = Field(
        None, description="当前篇章 ID（scope=arc 时必填）",
    )
    entity_ids: list[str] | None = Field(
        None, description="指定关注的世界对象 ID 列表",
    )
    character_ids: list[str] | None = Field(
        None, description="指定关注的人物 ID 列表",
    )
    location_ids: list[str] | None = Field(
        None, description="指定关注的地点 ID 列表",
    )
    reveal_mode: str = Field(
        default="author_safe",
        description="揭示模式: author_safe / author_full / reader / character",
    )
    viewpoint_character_id: str | None = Field(
        None, description="视角人物 ID（reveal_mode=character 时必填）",
    )
    enable_geo_filter: bool = Field(
        default=False, description="是否启用地缘可达性过滤",
    )


class BudgetUsedItem(BaseModel):
    """预算使用明细"""

    category: str = Field(..., description="分类名称")
    budget: int = Field(..., description="预算上限")
    used: int = Field(..., description="实际使用数")


class ContextCompileResponse(BaseModel):
    """上下文编译响应"""

    novel_id: str = Field(..., description="项目 ID")
    task: str = Field(..., description="创作任务")
    scope: str = Field(..., description="编译范围")
    reveal_mode: str = Field(..., description="揭示模式")
    budgets: list[BudgetUsedItem] = Field(
        default_factory=list, description="预算使用情况",
    )
    warnings: list[str] = Field(
        default_factory=list, description="编译警告",
    )
    section_count: int = Field(
        default=0, description="Markdown 非空段落数",
    )
    sections_present: list[str] = Field(
        default_factory=list, description="包含数据的段落名列表",
    )


class ContextRenderRequest(BaseModel):
    """上下文编译 + Markdown 渲染请求"""

    novel_id: str = Field(..., description="项目 ID (UUID hex string)")
    task: str = Field(..., description="创作任务描述")
    scope: str = Field(
        ..., description="编译范围: project / world / world_character / arc / chapter / full",
    )
    chapter_index: int | None = Field(
        None, ge=0, description="当前章节索引",
    )
    arc_id: str | None = Field(
        None, description="当前篇章 ID",
    )
    entity_ids: list[str] | None = Field(
        None, description="指定关注的世界对象 ID 列表",
    )
    character_ids: list[str] | None = Field(
        None, description="指定关注的人物 ID 列表",
    )
    location_ids: list[str] | None = Field(
        None, description="指定关注的地点 ID 列表",
    )
    reveal_mode: str = Field(
        default="author_safe",
        description="揭示模式: author_safe / author_full / reader / character",
    )
    viewpoint_character_id: str | None = Field(
        None, description="视角人物 ID（reveal_mode=character 时必填）",
    )
    enable_geo_filter: bool = Field(
        default=False, description="是否启用地缘可达性过滤",
    )


class ContextRenderResponse(BaseModel):
    """上下文编译 + Markdown 渲染响应"""

    markdown: str = Field(..., description="渲染后的 Markdown 文本")
    compile_info: ContextCompileResponse = Field(
        ..., description="编译元信息",
    )
