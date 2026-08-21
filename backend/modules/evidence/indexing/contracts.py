"""
RAG 对外契约

定义其他模块可以安全依赖的 RAG 接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RagChunkContract:
    """RAG 片段契约 — 其他模块通过此契约引用 RAG 片段信息"""

    id: str
    """片段 ID"""
    novel_id: str
    """所属小说项目 ID"""
    source_type: str
    """来源类型"""
    source_id: str | None = None
    """来源对象 ID"""
    content_mode: str = "canonical"
    """正文版本视图"""
    source_content_hash: str | None = None
    """索引建立时的正文 hash"""
    chapter_index: int | None = None
    """关联章节索引"""
    chunk_index: int | None = None
    """章节内 chunk 序号"""
    start_offset: int | None = None
    """原始正文起始字符位置"""
    end_offset: int | None = None
    """原始正文结束字符位置"""
    char_count: int | None = None
    """chunk 正文字符数"""
    text: str = ""
    """片段文本"""
    summary: str | None = None
    """片段摘要"""
    entity_ids: list[str] = field(default_factory=list)
    """关联的世界对象 ID 列表"""
    character_ids: list[str] = field(default_factory=list)
    """关联的人物 ID 列表"""
    thread_ids: list[str] = field(default_factory=list)
    """关联的剧情线 ID 列表"""
    scene_id: str | None = None
    """关联的 Scene ID"""
    scene_span_id: str | None = None
    """关联的 SceneSpan ID"""
    visibility: str = "author_only"
    """信息可见性"""
    importance: float = 0.5
    """重要性评分"""
    index_version: str = "legacy"
    """RAG 索引版本"""
    embedding_status: str = "pending"
    """embedding 状态"""
    embedding_error: str | None = None
    """embedding 失败原因"""
    index_warnings: list[str] = field(default_factory=list)
    """索引过程告警"""
    meta: dict | None = None
    """扩展元数据（arc_name、chapter_title 等）"""
    score: float | None = None
    """检索评分（检索结果中填充）"""


@dataclass(frozen=True)
class RagQueryContract:
    """RAG 检索查询契约"""

    query: str
    """检索查询文本"""
    content_mode: str = "canonical"
    """检索 canonical / working 索引"""
    entity_ids: list[str] | None = None
    """限制关联的世界对象 ID 列表"""
    character_ids: list[str] | None = None
    """限制关联的人物 ID 列表"""
    thread_ids: list[str] | None = None
    """限制关联的剧情线 ID 列表"""
    chapter_index: int | None = None
    """限制关联章节索引"""
    visible_until_chapter: int | None = None
    """读者进度上界；只召回该章节及之前的片段"""
    scene_id: str | None = None
    """限制关联 Scene ID"""
    strict_scene_filter: bool = False
    """是否严格按 Scene 过滤，排除未标注 Scene 的片段"""
    mode: str = "search"
    """检索模式：search / context / extraction"""
    retrieval_purpose: str | None = None
    """可选下游用途，帮助内部证据重排序理解调用目的"""
    top_k: int = 12
    """返回的最大结果数"""


@dataclass(frozen=True)
class RagResultBundle:
    """RAG 检索结果束

    供其他模块（context compiler）使用。
    """

    chunks: list[RagChunkContract] = field(default_factory=list)
    """检索到的片段列表（按评分降序）"""
    total: int = 0
    """匹配总数"""
    query: str = ""
    """原始查询文本"""
    warnings: list[str] = field(default_factory=list)
    """检索过程告警"""
    degraded: bool = False
    """是否发生降级"""


@dataclass(frozen=True)
class RagIndexReport:
    """RAG 索引结果报告"""

    chapter_index: int
    content_mode: str = "canonical"
    source_draft_id: str | None = None
    source_content_hash: str | None = None
    chunks_created: int = 0
    warnings: list[str] = field(default_factory=list)
    embedding_failed_count: int = 0
    chunks_created_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RagTaskIndexOutcome:
    """Task-only chapter indexing outcome after lease-fenced checkpointing."""

    report: RagIndexReport
    status: str = "indexed"
    followup_task_id: str | None = None


@dataclass(frozen=True)
class RagEntityActivityStatContract:
    """Raw, rebuildable appearance positions for one CoreEntity."""

    entity_id: str
    appearance_chapters: list[int] = field(default_factory=list)
    last_chapter_index: int | None = None


@dataclass(frozen=True)
class RagEntityActivityBundleContract:
    """Project entity activity plus index coverage metadata."""

    items: list[RagEntityActivityStatContract] = field(default_factory=list)
    as_of_chapter: int | None = None
    covered_chapters: int = 0
    total_chapters: int = 0
    status: str = "unavailable"


@dataclass(frozen=True)
class RagSceneMappingCoverageContract:
    """Scene/SceneSpan mapping health for chapter-text chunks."""

    novel_id: str
    content_mode: str
    total_chapter_chunks: int = 0
    scene_mapped_chunk_count: int = 0
    span_mapped_chunk_count: int = 0
    expected_overlap_chunk_count: int = 0
    valid_span_mapped_chunk_count: int = 0
    dangling_mapping_count: int = 0
    wrong_source_mapping_count: int = 0
    overall_scene_mapping_rate: float | None = None
    overall_span_mapping_rate: float | None = None
    eligible_mapping_rate: float | None = None
