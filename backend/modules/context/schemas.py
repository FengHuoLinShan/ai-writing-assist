"""
Context Pydantic Schema 定义

用于 API 请求/响应校验。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ContextSelectionRequest(BaseModel):
    """上下文选择参数。"""

    novel_id: str = Field(..., description="项目 ID (UUID hex string)")
    task: str = Field(..., description="创作任务描述，如「生成章节卡」、「生成剧情线」")
    scope: str = Field(
        ...,
        description="编译范围: project / world / world_character / arc / chapter / full",
    )
    chapter_index: int | None = Field(
        None,
        ge=0,
        description="当前章节索引（scope=chapter 时必填）",
    )
    scene_id: str | None = Field(
        None,
        description="当前 Scene ID（scene-centric 编译时使用）",
    )
    arc_id: str | None = Field(
        None,
        description="当前篇章 ID（scope=arc 时必填）",
    )
    entity_ids: list[str] | None = Field(
        None,
        description="指定关注的世界对象 ID 列表",
    )
    character_ids: list[str] | None = Field(
        None,
        description="指定关注的人物 ID 列表",
    )
    location_ids: list[str] | None = Field(
        None,
        description="指定关注的地点 ID 列表",
    )
    reveal_mode: str = Field(
        default="author_safe",
        description="揭示模式: author_safe / author_full / reader / character",
    )
    viewpoint_character_id: str | None = Field(
        None,
        description="视角人物 ID（reveal_mode=character 时必填）",
    )
    enable_geo_filter: bool = Field(
        default=False,
        description="是否启用地缘可达性过滤",
    )
    budget_tokens: int = Field(
        default=4000,
        ge=500,
        le=32000,
        description="总 token 预算",
    )
    context_mode: Literal["canonical", "working"] = Field(
        default="canonical",
        description="上下文模式：canonical / working",
    )
    include_pending_objects: bool = Field(
        default=False,
        description="是否包含待确认对象",
    )
    excluded_asset_ids: dict[str, list[str]] = Field(
        default_factory=dict,
        description="本次排除的资产 ID",
    )
    user_note: str | None = Field(
        None,
        description="用户本次 AI 操作的额外注意事项",
    )


class ContextCompileRequest(ContextSelectionRequest):
    """上下文编译请求"""

    pass


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
        default_factory=list,
        description="预算使用情况",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="编译警告",
    )
    section_count: int = Field(
        default=0,
        description="Markdown 非空段落数",
    )
    sections_present: list[str] = Field(
        default_factory=list,
        description="包含数据的段落名列表",
    )


class ContextRenderRequest(ContextSelectionRequest):
    """上下文编译 + Markdown 渲染请求"""

    pass


class ContextRenderResponse(BaseModel):
    """上下文编译 + Markdown 渲染响应"""

    markdown: str = Field(..., description="渲染后的 Markdown 文本")
    compile_info: ContextTierCompileResponse = Field(
        ...,
        description="编译元信息",
    )


class ContextSectionItem(BaseModel):
    """单个 Tier 段"""

    key: str = Field(..., description="段标识")
    tier: int = Field(..., description="优先级 Tier 0-4")
    content: str = Field(..., description="段内容")
    token_count: int = Field(..., description="估算 token 数")
    truncated: bool = Field(default=False, description="是否被截断")


class ContextTierCompileResponse(BaseModel):
    """Scene-Centric 编译响应"""

    novel_id: str
    task: str
    scope: str
    reveal_mode: str
    scene_id: str | None = None
    viewpoint_character_id: str | None = None
    total_tokens: int = Field(default=0)
    budget_tokens: int = Field(default=4000)
    sections: list[ContextSectionItem] = Field(default_factory=list)
    evicted: list[str] = Field(default_factory=list, description="被驱逐的段 key 列表")
    truncated: list[str] = Field(default_factory=list, description="被截断的段 key 列表")
    warnings: list[str] = Field(default_factory=list)


class ContextConfirmRequest(ContextSelectionRequest):
    """AI 参考资料确认请求。"""

    action: str = Field(..., min_length=1, description="手动 AI 操作标识")


class ContextConfirmationResponse(BaseModel):
    """AI 参考资料确认响应。"""

    id: str
    novel_id: str
    action: str
    task: str
    scope: str
    context_mode: str
    include_pending_objects: bool
    excluded_asset_ids: dict[str, list[str]] = Field(default_factory=dict)
    selected_asset_ids: dict[str, list[str]] = Field(default_factory=dict)
    user_note: str | None = None
    warnings: list[str] = Field(default_factory=list)
    result_refs: list[dict[str, str]] = Field(default_factory=list)
    result_status: str
    stale_reasons: list[str] = Field(default_factory=list)
    compiled_at: str
    created_at: str
