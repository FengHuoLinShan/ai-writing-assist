"""
Context 对外契约

定义 Context Compiler 的数据结构契约。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 services/renderer。

Context 模块没有自己的数据表，它是组合层，从所有其他模块拉取数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
    rag_chunks: list = field(default_factory=list)
    """RAG 检索片段列表"""

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
    "rag_chunks": 8,
}


# 标记常量
AUTHOR_ONLY_WARNING = (
    "【作者视角信息】此为隐藏真相，角色和读者均不知情。"
    "不得直接让角色知道，不得在读者层提前揭示。"
)
