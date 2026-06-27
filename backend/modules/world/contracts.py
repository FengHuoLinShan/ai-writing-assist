"""
World 对外契约

定义其他模块可以安全依赖的世界模块接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass

from modules.world.schemas import (  # noqa: F401
    DuplicateSuggestionResult,
    WorldContextBundle,
    WorldEntityContext,
    WorldEntityResponse,
)


@dataclass(frozen=True)
class WorldEntityContract:
    """世界对象契约 — 其他模块通过此契约获取对象信息"""

    novel_id: str
    """项目 ID"""
    entity_id: str
    """对象 ID"""
    entity_type: str
    """对象类型"""
    name: str
    """对象名称"""
    summary: str | None = None
    """概要"""
    public_info: str | None = None
    """对外公开信息"""
    hidden_truth: str | None = None
    """隐藏真相（仅作者视角）"""
    importance: float = 0.5
    """重要性"""
    importance_level: str = "normal"
    """重要性级别"""
    reveal_level: str = "author_only"
    """揭示层级"""
    status: str = "draft"
    """状态"""


@dataclass(frozen=True)
class RelationshipContract:
    """关系契约 — 其他模块通过此契约获取关系信息"""

    novel_id: str
    """项目 ID"""
    relationship_id: str
    """关系 ID"""
    source_type: str
    """源对象类型"""
    source_id: str
    """源对象 ID"""
    target_type: str
    """目标对象类型"""
    target_id: str
    """目标对象 ID"""
    relation_type: str
    """关系类型"""
    description: str | None = None
    """关系描述"""
    visibility: str = "author_only"
    """可见性"""
    strength: float = 0.5
    """关系强度"""


@dataclass(frozen=True)
class EntityAliasContract:
    """别名契约 — 其他模块通过此契约获取别名信息"""

    novel_id: str
    """项目 ID"""
    alias_id: str
    """别名 ID"""
    entity_id: str
    """所属对象 ID"""
    alias: str
    """别名文本"""
    alias_type: str = "name"
    """别名类型"""
    confidence: float = 0.8
    """置信度"""


@dataclass(frozen=True)
class EntityCandidateContract:
    """候选对象契约 — 其他模块通过此契约获取候选信息"""

    novel_id: str
    """项目 ID"""
    candidate_id: str
    """候选 ID"""
    name: str
    """候选名称"""
    entity_type: str
    """候选类型"""
    importance_score: float = 0.5
    """重要性评分"""
    confidence: float = 0.5
    """置信度"""
    suggested_action: str = "needs_user_decision"
    """建议动作"""
    status: str = "pending"
    """状态"""


@dataclass(frozen=True)
class DuplicateSuggestion:
    """去重建议 — 候选对象与已有正史对象的匹配结果"""

    candidate_id: str
    """候选对象 ID"""
    candidate_name: str
    """候选对象名称"""
    existing_entity_id: str
    """匹配到的正史对象 ID"""
    existing_entity_name: str
    """匹配到的正史对象名称"""
    similarity_score: float
    """相似度分数"""
    match_method: str
    """匹配方法（exact_name/trgm_similar/vector_similar/fuzzy_name）"""
    action: str
    """建议动作（alias_of_existing/merge_with_existing/needs_user_decision）"""
