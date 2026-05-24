"""
RAG 对外契约

定义其他模块可以安全依赖的 RAG 接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    chapter_index: int | None = None
    """关联章节索引"""
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
    visibility: str = "author_only"
    """信息可见性"""
    importance: float = 0.5
    """重要性评分"""
    score: float | None = None
    """检索评分（检索结果中填充）"""


@dataclass(frozen=True)
class RagQueryContract:
    """RAG 检索查询契约"""

    query: str
    """检索查询文本"""
    entity_ids: list[str] | None = None
    """限制关联的世界对象 ID 列表"""
    character_ids: list[str] | None = None
    """限制关联的人物 ID 列表"""
    thread_ids: list[str] | None = None
    """限制关联的剧情线 ID 列表"""
    chapter_index: int | None = None
    """限制关联章节索引"""
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
