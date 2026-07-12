"""
Context Pydantic Schema 定义

用于 API 请求/响应校验。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ContextSelectionRequest(BaseModel):
    """上下文选择参数。"""

    novel_id: str = Field(..., description="项目 ID (UUID hex string)")
    task: str = Field(..., description="创作任务描述，如「生成章节卡」、「生成剧情线」")
    scope: str = Field(
        ...,
        description="编译范围: project / world / world_character / arc / chapter / full",
    )
    retrieval_purpose: Literal[
        "writing_generation",
        "conflict_review",
        "outline_generation",
        "cross_chapter_detection",
        "world_fusion",
        "import_scene_activation",
        "reader_context",
        "character_context",
        "manual_search",
        "generic_context",
    ] = "generic_context"
    chapter_index: int | None = Field(
        None,
        ge=0,
        description="当前章节索引（scope=chapter 时必填）",
    )
    visible_until_chapter: int | None = Field(
        None,
        ge=1,
        description="读者/角色视角可见截止章",
    )
    visible_until_scene_id: str | None = Field(
        None,
        description="同章可见截止 Scene",
    )
    visible_until_offset: int | None = Field(
        None,
        ge=0,
        description="同章可见截止字符偏移",
    )
    scene_id: str | None = Field(
        None,
        description="当前 Scene ID（scene-centric 编译时使用）",
    )
    map_id: str | None = Field(None, description="当前地图焦点 ID")
    focus_entity_id: str | None = Field(None, description="显式关注的世界对象 ID")
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
    thread_ids: list[str] | None = Field(
        None,
        description="指定关注的剧情线 ID 列表",
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
    content_mode: Literal["canonical", "working"] = Field(
        default="canonical",
        description="正文来源视图：canonical / working",
    )
    include_pending_objects: bool = Field(
        default=False,
        description="是否包含待处理对象",
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
    title: str = Field(default="", description="面向作者的段标题")
    preview: str = Field(default="", description="审查用内容预览")
    status: Literal[
        "system",
        "canonical",
        "working",
        "candidate",
        "mixed",
        "unknown",
    ] = Field(default="unknown", description="段内容状态")
    activation_reason: str = Field(default="", description="段被选入的原因")
    sources: list[dict[str, Any]] = Field(
        default_factory=list,
        description="段来源摘要",
    )
    can_exclude: bool = Field(default=True, description="本次操作是否允许排除")
    excluded: bool = Field(default=False, description="是否已被排除")
    truncated_reason: str | None = Field(default=None, description="截断原因")
    retrieval_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="检索计划与命中原因摘要；不包含原始 query",
    )


class ContextRetrievalTraceResponse(BaseModel):
    id: str
    novel_id: str
    content_mode: str
    consumer_action: str
    retrieval_purpose: str
    reveal_mode: str
    plan_version: str
    plan_hash: str
    clause_summaries: list[dict] = Field(default_factory=list)
    scene_id: str | None = None
    chapter_index: int | None = None
    candidate_count: int = 0
    unique_count: int = 0
    hydrated_count: int = 0
    drop_counts: dict[str, int] = Field(default_factory=dict)
    safe_empty_reason: str | None = None
    degraded: bool = False
    warning_codes: list[str] = Field(default_factory=list)
    latency_metadata: dict[str, float] = Field(default_factory=dict)
    created_at: str


class ContextRetrievalTraceListResponse(BaseModel):
    items: list[ContextRetrievalTraceResponse] = Field(default_factory=list)
    total: int = 0


class EvidenceHealthResponse(BaseModel):
    novel_id: str
    content_mode: Literal["canonical", "working"]
    window_hours: int
    health_state: Literal["healthy", "degraded", "insufficient_data"]
    health_reasons: list[str] = Field(default_factory=list)
    scene_span_coverage: dict = Field(default_factory=dict)
    rag_mapping_coverage: dict = Field(default_factory=dict)
    retrieval_summary: dict = Field(default_factory=dict)


class ContextBudgetEventItem(BaseModel):
    """预算裁剪事件。"""

    section_key: str
    event_type: Literal["evicted", "truncated"]
    reason: str
    before_tokens: int
    after_tokens: int
    tier: int


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
    budget_events: list[ContextBudgetEventItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ContextConfirmRequest(ContextSelectionRequest):
    """AI 参考资料确认请求。"""

    action: str = Field(..., min_length=1, description="手动 AI 操作标识")


class ContextActivationPreviewRequest(BaseModel):
    """Worldbuilding activation preview request."""

    novel_id: str
    entity_ids: list[str] = Field(default_factory=list)
    map_id: str | None = None
    scene_id: str | None = None
    focus_entity_id: str | None = None
    top_k: int = Field(default=64, ge=1, le=256)
    depth: int = Field(default=2, ge=0, le=2)


class ContextActivationPreviewResponse(BaseModel):
    """Deterministic activation preview response."""

    novel_id: str
    depth: int
    top_k: int
    items: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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
    sections: list[ContextSectionItem] = Field(default_factory=list)
    budget_events: list[ContextBudgetEventItem] = Field(default_factory=list)
    result_refs: list[dict[str, str]] = Field(default_factory=list)
    result_status: str
    stale_reasons: list[str] = Field(default_factory=list)
    compiled_at: str
    created_at: str


class ContextSnapshotResponse(BaseModel):
    """自动 AI 调用上下文快照响应。"""

    id: str
    novel_id: str
    task_id: str | None = None
    workflow_id: str | None = None
    phase: str
    operation: str
    scene_id: str | None = None
    scene_index: int | None = None
    chapter_index: int | None = None
    context_mode: str
    include_pending_objects: bool
    status: str
    attempt: int
    prompt_hash: str
    prompt_name: str
    model: str
    compile_options: dict = Field(default_factory=dict)
    included_asset_ids: dict = Field(default_factory=dict)
    excluded_asset_ids: dict = Field(default_factory=dict)
    context_summary: dict = Field(default_factory=dict)
    section_metadata: dict = Field(default_factory=dict)
    token_metadata: dict = Field(default_factory=dict)
    rendered_context: str | None = None
    result_refs: list[dict] = Field(default_factory=list)
    error_kind: str | None = None
    error_message: str | None = None
    rendered_context_expires_at: str | None = None
    created_at: str
    updated_at: str | None = None


class ContextSnapshotListItemResponse(BaseModel):
    """上下文快照列表项；不返回完整 rendered_context。"""

    id: str
    novel_id: str
    task_id: str | None = None
    workflow_id: str | None = None
    phase: str
    operation: str
    scene_id: str | None = None
    scene_index: int | None = None
    chapter_index: int | None = None
    context_mode: str
    include_pending_objects: bool
    status: str
    attempt: int
    prompt_hash: str
    prompt_name: str
    model: str
    compile_options: dict = Field(default_factory=dict)
    included_asset_ids: dict = Field(default_factory=dict)
    excluded_asset_ids: dict = Field(default_factory=dict)
    context_summary: dict = Field(default_factory=dict)
    section_metadata: dict = Field(default_factory=dict)
    token_metadata: dict = Field(default_factory=dict)
    has_rendered_context: bool = False
    result_refs: list[dict] = Field(default_factory=list)
    error_kind: str | None = None
    error_message: str | None = None
    rendered_context_expires_at: str | None = None
    created_at: str
    updated_at: str | None = None


class ContextSnapshotListResponse(BaseModel):
    """上下文快照列表响应。"""

    items: list[ContextSnapshotListItemResponse] = Field(default_factory=list)
    total: int = 0


class SnapshotHealthSummaryResponse(BaseModel):
    """上下文快照健康摘要；不包含正文、prompt 或完整 result refs。"""

    novel_id: str
    workflow_id: str | None = None
    total_snapshots: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_phase: dict[str, dict[str, int]] = Field(default_factory=dict)
    stale_running_count: int = 0
    owner_terminal_orphan_count: int = 0
    owner_stale_count: int = 0
    retained_rendered_context_count: int = 0
    latest_failure: dict | None = None


class ContextSnapshotMaintenanceRequest(BaseModel):
    """上下文快照显式维护请求。"""

    novel_id: str = Field(..., description="项目 ID")
    workflow_id: str | None = Field(None, description="可选 workflow 过滤")
    running_timeout_minutes: int = Field(default=120, ge=1)
    prune_rendered_context: bool = Field(default=True)
    retain_latest_full_context_per_project: int = Field(default=200, ge=0)
    prune_retrieval_traces: bool = Field(default=True)
    retrieval_trace_retention_days: int = Field(default=30, ge=1, le=365)
    retain_latest_retrieval_traces: int = Field(default=10_000, ge=0, le=100_000)
    dry_run: bool = Field(default=True)


class ContextSnapshotMaintenanceResponse(BaseModel):
    """上下文快照维护响应。"""

    snapshot_health_summary: SnapshotHealthSummaryResponse
    stale_running_count: int = 0
    pruned_rendered_context_count: int = 0
    pruned_retrieval_trace_count: int = 0
    would_change_count: int = 0
    dry_run: bool = True


class VisibilityContextRequest(BaseModel):
    mode: Literal["author", "reader", "character"] = "author"
    cutoff_chapter: int | None = Field(None, ge=1)
    cutoff_scene_id: str | None = None
    cutoff_offset: int | None = Field(None, ge=0)
    character_id: str | None = None

    @model_validator(mode="after")
    def validate_visibility(self):
        if self.mode in {"reader", "character"} and self.cutoff_chapter is None:
            raise ValueError("reader/character visibility requires cutoff_chapter")
        if self.mode == "character" and not self.character_id:
            raise ValueError("character visibility requires character_id")
        return self


class SourceRangeRefRequest(BaseModel):
    draft_id: str
    chapter_index: int = Field(..., ge=1)
    version_number: int = Field(..., ge=1)
    content_mode: Literal["canonical", "working"]
    start_offset: int = Field(..., ge=0)
    end_offset: int = Field(..., ge=1)
    source_hash: str = Field(..., min_length=64, max_length=64)
    range_hash: str = Field(..., min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_offsets(self):
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


class EvidenceGrepRequest(BaseModel):
    novel_id: str
    pattern: str = Field(..., min_length=1, max_length=200)
    content_mode: Literal["canonical", "working"] = "canonical"
    visibility: VisibilityContextRequest = Field(default_factory=VisibilityContextRequest)
    chapter_from: int | None = Field(None, ge=1)
    chapter_to: int | None = Field(None, ge=1)
    case_sensitive: bool = False
    skip: int = Field(0, ge=0)
    limit: int = Field(20, ge=1, le=100)


class EvidenceSearchRequest(BaseModel):
    novel_id: str
    query: str = Field(..., min_length=1, max_length=1000)
    content_mode: Literal["canonical", "working"] = "canonical"
    visibility: VisibilityContextRequest = Field(default_factory=VisibilityContextRequest)
    scopes: list[Literal["manuscript", "world", "outline"]] = Field(
        default_factory=lambda: ["manuscript"]
    )
    include_pending_objects: bool = Field(
        False,
        description="是否显式纳入待处理世界对象",
    )
    chapter_from: int | None = Field(None, ge=1)
    chapter_to: int | None = Field(None, ge=1)
    top_k: int = Field(12, ge=1, le=50)


class EvidenceReadRequest(BaseModel):
    novel_id: str
    content_mode: Literal["canonical", "working"] = "canonical"
    visibility: VisibilityContextRequest = Field(default_factory=VisibilityContextRequest)
    source_ref: SourceRangeRefRequest
    before: int = Field(3, ge=0, le=20)
    after: int = Field(3, ge=0, le=20)


class EvidenceInspectRequest(BaseModel):
    novel_id: str
    content_mode: Literal["canonical", "working"] = "canonical"
    visibility: VisibilityContextRequest = Field(default_factory=VisibilityContextRequest)
    target_ref: dict


class EvidenceTraceRequest(EvidenceInspectRequest):
    claim_path: str = Field(default="", max_length=512)


class EvidenceHitResponse(BaseModel):
    kind: str
    title: str
    snippet: str
    source_ref: dict | None = None
    target_ref: dict | None = None
    chapter_index: int | None = None
    score: float | None = None
    scene_refs: list[dict] = Field(default_factory=list)
    object_refs: list[dict] = Field(default_factory=list)
    index_fresh: bool = True
    visibility_decision: dict = Field(default_factory=dict)


class EvidenceSearchResponse(BaseModel):
    hits: list[EvidenceHitResponse] = Field(default_factory=list)
    total: int = 0
    warnings: list[str] = Field(default_factory=list)
    degraded: bool = False
    missing_chapters: list[int] = Field(default_factory=list)


class EvidenceReadResponse(BaseModel):
    source_ref: dict
    title: str | None = None
    text: str
    highlight_start: int
    highlight_end: int
    scene_refs: list[dict] = Field(default_factory=list)
    object_refs: list[dict] = Field(default_factory=list)
    index_fresh: bool = True
    visibility_decision: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    degraded: bool = False


class EvidenceInspectResponse(BaseModel):
    target_ref: dict
    visible: bool
    item: dict | None = None
    evidence_count: int = 0
    index_fresh: bool = True
    warnings: list[str] = Field(default_factory=list)
    visibility_decision: dict = Field(default_factory=dict)
    degraded: bool = False


class EvidenceTraceResponse(BaseModel):
    target_ref: dict
    claim_path: str = ""
    links: list[dict] = Field(default_factory=list)
    index_fresh: bool = True
    warnings: list[str] = Field(default_factory=list)
    visibility_decision: dict = Field(default_factory=dict)
    degraded: bool = False
