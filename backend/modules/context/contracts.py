"""
Context 对外契约

定义 Context Compiler、确认记录和自动快照的数据结构契约。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 services/renderer。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.context.services.compiled_context import CompiledContext


@dataclass
class CompileOptions:
    """编译选项 — facade 与 compiler 之间的契约"""

    novel_id: str
    task: str
    scope: str
    consumer_action: str | None = None
    """后端确定的消费动作，如 writing.generate；不接受前端伪造"""
    retrieval_purpose: str = "generic_context"
    """确定性检索用途；未知调用方使用 generic_context"""
    chapter_index: int | None = None
    visible_until_chapter: int | None = None
    """RAG 读者进度上界；None 表示不启用未来章节硬过滤"""
    visible_until_scene_id: str | None = None
    """可选的同章 Scene 可见截止点"""
    visible_until_offset: int | None = None
    """可选的同章字符可见截止点"""
    scene_id: str | None = None
    """当前 Scene ID（scene-centric 编译时提供）"""
    arc_id: str | None = None
    map_id: str | None = None
    """当前地图焦点（world context activation 使用）"""
    focus_entity_id: str | None = None
    """显式关注的世界对象（world context activation 使用）"""
    prior_neighbor_limit: int = 2
    """导入 Scene-local 上下文的前序邻居数，最大 4"""
    entity_ids: list[str] | None = None
    character_ids: list[str] | None = None
    thread_ids: list[str] | None = None
    location_ids: list[str] | None = None
    reveal_mode: str = "author_safe"
    """揭示模式：author_safe / author_full / reader / character"""
    viewpoint_character_id: str | None = None
    """视角人物 ID（reveal_mode="character" 时必填）"""
    enable_geo_filter: bool = False
    mode: str = "writing"  # CompileMode value: "writing" or "debug"
    budget_tokens: int = 4000
    """总 token 预算，默认 4000"""
    top_k: int = 8
    """RAG 检索上限"""
    context_mode: str = "canonical"
    """上下文模式：canonical / working"""
    content_mode: str = "canonical"
    """正文来源视图：canonical / working"""
    include_pending_objects: bool = False
    """是否包含待处理对象"""
    excluded_asset_ids: dict[str, list[str]] = field(default_factory=dict)
    """本次编译显式排除的资产 ID"""
    user_note: str | None = None
    """用户本次 AI 操作的额外注意事项"""


@dataclass
class ContextConfirmationContract:
    """AI 参考资料确认记录对外契约。"""

    id: str
    novel_id: str
    action: str
    task: str
    scope: str
    context_mode: str
    include_pending_objects: bool
    excluded_asset_ids: dict[str, list[str]]
    selected_asset_ids: dict[str, list[str]]
    user_note: str | None
    compile_options: dict
    warnings: list[str]
    sections: list[dict]
    budget_events: list[dict]
    result_refs: list[dict[str, str]]
    result_status: str
    stale_reasons: list[str]
    compiled_at: str
    created_at: str


@dataclass
class ConfirmedAIActionContext:
    """Validated context materialized for an AI action."""

    confirmation: ContextConfirmationContract
    compiled: CompiledContext
    rendered_markdown: str
    compile_options: dict
    result_refs: list[dict[str, str]]


@dataclass
class ContextSnapshotContract:
    """Automated AI-call context snapshot contract."""

    id: str
    novel_id: str
    task_id: str | None
    workflow_id: str | None
    phase: str
    operation: str
    scene_id: str | None
    scene_index: int | None
    chapter_index: int | None
    context_mode: str
    include_pending_objects: bool
    status: str
    attempt: int
    prompt_hash: str
    prompt_name: str
    model: str
    compile_options: dict
    included_asset_ids: dict
    excluded_asset_ids: dict
    context_summary: dict
    section_metadata: dict
    token_metadata: dict
    rendered_context: str | None
    result_refs: list[dict]
    error_kind: str | None
    error_message: str | None
    rendered_context_expires_at: str | None
    created_at: str
    updated_at: str | None


@dataclass
class ContextSnapshotRequest:
    """Request to open an automated AI-call context snapshot."""

    novel_id: str
    phase: str
    operation: str
    prompt_name: str
    model: str
    compile_options: dict
    included_asset_ids: dict | list
    context_summary: dict
    section_metadata: dict | list
    token_metadata: dict
    task_id: str | None = None
    workflow_id: str | None = None
    scene_id: str | None = None
    scene_index: int | None = None
    chapter_index: int | None = None
    context_mode: str = "working"
    include_pending_objects: bool = True
    attempt: int = 1
    excluded_asset_ids: dict | list | None = None
    rendered_context: str | None = None
    retain_rendered_context: bool = False


@dataclass(frozen=True)
class ContextRetrievalTraceContract:
    """Privacy-safe diagnostics for one context retrieval execution."""

    id: str
    novel_id: str
    content_mode: str
    consumer_action: str
    retrieval_purpose: str
    reveal_mode: str
    plan_version: str
    plan_hash: str
    clause_summaries: list[dict] = field(default_factory=list)
    scene_id: str | None = None
    chapter_index: int | None = None
    candidate_count: int = 0
    unique_count: int = 0
    hydrated_count: int = 0
    drop_counts: dict[str, int] = field(default_factory=dict)
    safe_empty_reason: str | None = None
    degraded: bool = False
    warning_codes: list[str] = field(default_factory=list)
    latency_metadata: dict[str, float] = field(default_factory=dict)
    created_at: str = ""


@dataclass(frozen=True)
class EvidenceHealthContract:
    """Combined Scene, RAG mapping, and context retrieval health."""

    novel_id: str
    content_mode: str
    window_hours: int
    health_state: str
    health_reasons: list[str] = field(default_factory=list)
    scene_span_coverage: dict = field(default_factory=dict)
    rag_mapping_coverage: dict = field(default_factory=dict)
    retrieval_summary: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalClause:
    clause_id: str
    query_text: str
    mode: str
    top_k: int
    reason_code: str
    entity_ids: list[str] | None = None
    character_ids: list[str] | None = None
    thread_ids: list[str] | None = None
    chapter_index: int | None = None
    scene_id: str | None = None
    strict_scene_filter: bool = False
    priority: float = 1.0


@dataclass(frozen=True)
class RetrievalQueryPlan:
    version: str
    purpose: str
    clauses: list[RetrievalClause]
    visible_until_chapter: int | None
    visible_until_scene_id: str | None
    visible_until_offset: int | None
    final_top_k: int
    plan_hash: str


@dataclass(frozen=True)
class ImportContextActivationContract:
    """Frozen, read-only preflight material for one deep-import Scene call."""

    novel_id: str
    scene_id: str
    scene_index: int
    chapter_index: int | None
    activation_version: str
    current_scene_text: str
    current_scene_sources: list[dict]
    previous_briefs: list[dict]
    previous_evidence: list[dict]
    world_entries: list[dict]
    world_context_text: str
    neighbor_context_text: str
    sources: list[dict]
    budget_events: list[dict]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisibilityContextContract:
    mode: str = "author"
    cutoff_chapter: int | None = None
    cutoff_scene_id: str | None = None
    cutoff_offset: int | None = None
    character_id: str | None = None


@dataclass(frozen=True)
class EvidenceHitContract:
    kind: str
    title: str
    snippet: str
    source_ref: dict | None = None
    target_ref: dict | None = None
    chapter_index: int | None = None
    score: float | None = None
    scene_refs: list[dict] = field(default_factory=list)
    object_refs: list[dict] = field(default_factory=list)
    index_fresh: bool = True
    visibility_decision: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceReadContract:
    source_ref: dict
    title: str | None
    text: str
    highlight_start: int
    highlight_end: int
    scene_refs: list[dict] = field(default_factory=list)
    object_refs: list[dict] = field(default_factory=list)
    index_fresh: bool = True
    visibility_decision: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False


@dataclass(frozen=True)
class EvidenceTraceContract:
    target_ref: dict
    claim_path: str
    links: list[dict] = field(default_factory=list)
    index_fresh: bool = True
    warnings: list[str] = field(default_factory=list)
    visibility_decision: dict = field(default_factory=dict)
    degraded: bool = False


@dataclass
class StructureContextBundle:
    """结构化创作上下文包

    Context Compiler 的核心产出。
    聚合 project / world / geo / character / memory / timeline / outline / rag 数据，
    供给 LLM Prompt 使用。
    """

    novel_id: str
    """项目 ID"""
    task: str
    """创作任务描述"""
    scope: str
    """编译范围（project/world/world_character/arc/chapter/full）"""
    chapter_index: int | None = None
    """当前章节索引"""
    arc_id: str | None = None
    """当前篇章 ID"""

    # --- 各模块数据（按 scope 按需加载） ---
    project: dict | None = None
    """项目元信息"""
    world_entities: list = field(default_factory=list)
    """世界对象列表"""
    characters: list = field(default_factory=list)
    """人物列表"""
    geo_locations: list = field(default_factory=list)
    """地理地点列表"""
    memory_records: list = field(default_factory=list)
    """长期记忆记录列表"""
    timeline_events: list = field(default_factory=list)
    """时间线事件列表"""
    plot_threads: list = field(default_factory=list)
    """剧情线列表"""
    outline_arc: dict | None = None
    """当前篇章纲"""
    chapter_card: dict | None = None
    """当前章节卡"""
    scene: dict | None = None
    """当前 Scene 卡"""
    rag_chunks: list = field(default_factory=list)
    """RAG 检索片段列表"""
    retrieval_trace: dict = field(default_factory=dict)
    """本次 RAG 加载的结构化诊断；不进入 prompt 正文"""

    geo_filtered: bool = False
    """是否执行了地缘可达性过滤"""

    # --- 元信息 ---
    reveal_mode: str = "author_safe"
    """揭示模式（author_safe / author_full / reader / character）"""
    viewpoint_character_id: str | None = None
    """视角人物 ID（reveal_mode="character" 时使用）"""
    budget_used: dict = field(default_factory=dict)
    """各分类已使用的预算"""
    warnings: list = field(default_factory=list)
    """编译过程中的警告/提示列表"""


# 默认 Context Budget
CONTEXT_BUDGET: dict[str, int] = {
    "core_entities": 8,
    "normal_entities": 8,
    "characters": 6,
    "memory": 10,
    "foreshadowing": 5,
    "timeline": 8,
    "geo_relations": 10,
    "relationship_edges": 12,
    "plot_threads": 8,
    "rag_chunks": 8,
}


# 标记常量
AUTHOR_ONLY_WARNING = (
    "【作者视角信息】此为隐藏真相，角色和读者均不知情。"
    "不得直接让角色知道，不得在读者层提前揭示。"
)
