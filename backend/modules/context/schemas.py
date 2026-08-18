"""
Context Pydantic Schema 定义

用于 API 请求/响应校验。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from shared.target_ref import normalize_target_ref


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
        "world_fusion",
        "world_generation",
        "map_atlas",
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
        ge=0,
        le=32000,
        description="总 token 预算；0 表示确认编译不驱逐任何 section",
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
    include_world_synopsis: bool = Field(
        default=False,
        description="作者模式是否加入世界观简介；reader/character 会安全排除",
    )
    selected_world_bible_draft_ids: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="本次显式加入的 World Bible 工作稿 ID",
    )
    activation_profile_id: str | None = Field(
        default=None,
        description="本次显式启用的已发布 AI 参考规则 Profile",
    )
    activation_profile_version: int | None = Field(
        default=None,
        ge=1,
        description="回放时固定的已发布 Profile revision",
    )
    excluded_asset_ids: dict[str, list[str]] = Field(
        default_factory=dict,
        description="本次排除的资产 ID",
    )
    user_note: str | None = Field(
        None,
        description="用户本次 AI 操作的额外注意事项",
    )

    @field_validator("budget_tokens")
    @classmethod
    def validate_budget_tokens(cls, value: int) -> int:
        if 0 < value < 500:
            raise ValueError("budget_tokens must be 0 or at least 500")
        return value


class ContextCompileRequest(ContextSelectionRequest):
    """上下文编译请求"""

    pass


class SceneLensRequest(BaseModel):
    novel_id: str = Field(..., description="项目 ID")
    scene_id: str = Field(..., description="当前 Scene ID")


class SceneLensResponse(BaseModel):
    role_visible_knowledge: dict[str, Any] = Field(default_factory=dict)
    scene_world_state: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


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
        "director_only",
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
    activation_trace: dict[str, Any] = Field(default_factory=dict)


class ContextConfirmRequest(ContextSelectionRequest):
    """AI 参考资料确认请求。"""

    action: str = Field(..., min_length=1, description="手动 AI 操作标识")


class ContextActivationPreviewRequest(BaseModel):
    """Worldbuilding activation preview request."""

    novel_id: str
    action: str | None = Field(default=None, min_length=1, max_length=128)
    profile_id: str | None = None
    profile_version: int | None = Field(default=None, ge=1)
    reveal_mode: Literal[
        "author_safe",
        "author_full",
        "reader",
        "character",
    ] = "author_safe"
    task_text: str = Field(default="", max_length=20000)
    current_scene_text: str = Field(default="", max_length=50000)
    previous_scene_briefs: list[str] = Field(default_factory=list, max_length=2)
    explicit_focus: str = Field(default="", max_length=10000)
    entity_ids: list[str] = Field(default_factory=list)
    map_id: str | None = None
    scene_id: str | None = None
    focus_entity_id: str | None = None
    top_k: int = Field(default=64, ge=1, le=256)
    depth: int = Field(default=2, ge=0, le=2)


class ActivationRuleScope(BaseModel):
    actions: list[str] = Field(default_factory=list, min_length=1, max_length=20)
    modes: list[
        Literal["author_safe", "author_full", "reader", "character"]
    ] = Field(default_factory=lambda: ["author_safe"], min_length=1, max_length=4)
    match_sources: list[
        Literal[
            "task_text",
            "current_scene_text",
            "previous_scene_briefs",
            "explicit_focus",
        ]
    ] = Field(
        default_factory=lambda: ["task_text"],
        min_length=1,
        max_length=4,
    )

    @field_validator("actions")
    @classmethod
    def validate_actions(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(values):
            raise ValueError("activation actions must not be blank")
        return list(dict.fromkeys(normalized))


class ActivationRuleMatch(BaseModel):
    positive_terms: list[str] = Field(default_factory=list, max_length=32)
    negative_terms: list[str] = Field(default_factory=list, max_length=32)
    positive_logic: Literal["any", "all"] = "any"
    negative_logic: Literal["any", "all"] = "any"
    mode: Literal["normalized_substring", "token_boundary"] = (
        "normalized_substring"
    )

    @field_validator("positive_terms", "negative_terms")
    @classmethod
    def validate_terms(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            term = value.strip()
            if not term:
                raise ValueError("activation terms must not be blank")
            if len(term) > 80:
                raise ValueError("activation terms must be at most 80 characters")
            if term not in normalized:
                normalized.append(term)
        return normalized

    @model_validator(mode="after")
    def require_positive_term(self) -> ActivationRuleMatch:
        if not self.positive_terms:
            raise ValueError("activation rule requires at least one positive term")
        return self


class ActivationRuleSelect(BaseModel):
    target_refs: list[dict[str, str]] = Field(
        default_factory=list,
        min_length=1,
        max_length=64,
    )
    expand_page_links: bool = False
    relation_types: list[str] = Field(default_factory=list, max_length=32)
    max_depth: int = Field(default=0, ge=0, le=2)

    @field_validator("target_refs")
    @classmethod
    def validate_target_refs(
        cls,
        values: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in values:
            target = normalize_target_ref(value)
            if target.target_type not in {"core_entity", "world_bible_page"}:
                raise ValueError("activation target type is not supported")
            target_hash = target.target_hash()
            if target_hash not in seen:
                normalized.append(target.canonical_dict())
                seen.add(target_hash)
        return normalized

    @field_validator("relation_types")
    @classmethod
    def validate_relation_types(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(values):
            raise ValueError("relation types must not be blank")
        return list(dict.fromkeys(normalized))


class ActivationRuleRank(BaseModel):
    priority: int = Field(default=500, ge=0, le=1000)
    top_k: int = Field(default=12, ge=1, le=256)
    token_cap: int = Field(default=1200, ge=64, le=32000)


class ActivationRule(BaseModel):
    rule_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    name: str = Field(..., min_length=1, max_length=120)
    enabled: bool = True
    scope: ActivationRuleScope
    match: ActivationRuleMatch
    select: ActivationRuleSelect
    rank: ActivationRuleRank = Field(default_factory=ActivationRuleRank)


def _validate_activation_rules(rules: list[ActivationRule]) -> list[ActivationRule]:
    rule_ids = [rule.rule_id for rule in rules]
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("activation rule_id must be unique within a profile")
    return sorted(rules, key=lambda rule: rule.rule_id)


class ContextActivationProfileCreate(BaseModel):
    novel_id: str
    profile_key: str = Field(
        ...,
        min_length=2,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    )
    name: str = Field(..., min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    applicable_actions_json: list[str] = Field(
        default_factory=list,
        min_length=1,
        max_length=20,
    )
    rules_json: list[ActivationRule] = Field(default_factory=list, max_length=128)
    budget_hints_json: dict[str, int] = Field(default_factory=dict)
    created_by: str | None = Field(default=None, max_length=64)

    @field_validator("rules_json")
    @classmethod
    def validate_rules(cls, rules: list[ActivationRule]) -> list[ActivationRule]:
        return _validate_activation_rules(rules)

    @model_validator(mode="after")
    def validate_actions(self) -> ContextActivationProfileCreate:
        actions = [action.strip() for action in self.applicable_actions_json]
        if not all(actions):
            raise ValueError("profile actions must not be blank")
        self.applicable_actions_json = list(dict.fromkeys(actions))
        rule_actions = {
            action
            for rule in self.rules_json
            for action in rule.scope.actions
        }
        if not rule_actions.issubset(set(self.applicable_actions_json)):
            raise ValueError("rule actions must be declared by the profile")
        return self


class ContextActivationProfileUpdate(BaseModel):
    base_version_number: int = Field(..., ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    applicable_actions_json: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
    )
    rules_json: list[ActivationRule] | None = Field(default=None, max_length=128)
    budget_hints_json: dict[str, int] | None = None
    status: Literal["draft", "archived"] | None = None
    updated_by: str | None = Field(default=None, max_length=64)

    @field_validator("rules_json")
    @classmethod
    def validate_rules(
        cls,
        rules: list[ActivationRule] | None,
    ) -> list[ActivationRule] | None:
        return None if rules is None else _validate_activation_rules(rules)

    @model_validator(mode="after")
    def reject_null_values(self) -> ContextActivationProfileUpdate:
        for field_name in {
            "name",
            "applicable_actions_json",
            "rules_json",
            "budget_hints_json",
            "status",
        }:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class ContextActivationProfilePublishRequest(BaseModel):
    base_version_number: int = Field(..., ge=1)
    revision_reason: str = Field(default="publish", min_length=1, max_length=64)
    published_by: str | None = Field(default=None, max_length=64)


class ContextActivationProfileResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    novel_id: str
    profile_key: str
    name: str
    description: str | None = None
    applicable_actions_json: list[str] = Field(default_factory=list)
    rules_json: list[ActivationRule] = Field(default_factory=list)
    budget_hints_json: dict[str, int] = Field(default_factory=dict)
    version_number: int
    status: str
    created_by: str | None = None
    updated_by: str | None = None
    created_at: Any | None = None
    updated_at: Any | None = None


class ContextActivationProfileListResponse(BaseModel):
    items: list[ContextActivationProfileResponse]
    total: int


class ContextActivationProfileRevisionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    novel_id: str
    profile_id: str
    version_number: int
    snapshot_json: dict[str, Any] = Field(default_factory=dict)
    rule_hash: str
    revision_reason: str
    created_by: str | None = None
    created_at: Any | None = None


class ContextActivationProfileRestoreRequest(BaseModel):
    restored_by: str | None = Field(default=None, max_length=64)


class ContextActivationPreviewResponse(BaseModel):
    """Deterministic activation preview response."""

    novel_id: str
    depth: int
    top_k: int
    items: list[dict] = Field(default_factory=list)
    excluded_items: list[dict] = Field(default_factory=list)
    profile: dict | None = None
    rule_evaluations: list[dict] = Field(default_factory=list)
    budget_events: list[dict] = Field(default_factory=list)
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
    group_by_chapter: bool = False
    context_scene_id: str | None = Field(
        None,
        description="当前写作 Scene；仅用于作者结果的前后文关系说明",
    )


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
    top_k: int = Field(100, ge=1, le=100)
    context_scene_id: str | None = Field(
        None,
        description="当前写作 Scene；仅用于作者结果的前后文关系说明",
    )


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
    parent_scene_contexts: list[dict] = Field(default_factory=list)
    object_refs: list[dict] = Field(default_factory=list)
    index_fresh: bool = True
    visibility_decision: dict = Field(default_factory=dict)
    match_count: int = Field(1, ge=1)
    match_basis: Literal["occurrence", "chunk"] = "chunk"
    writing_relevance: dict = Field(default_factory=dict)


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
