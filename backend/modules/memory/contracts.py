"""
Memory 对外契约

定义其他模块可以安全依赖的记忆接口和数据类。
其他模块只能导入 contracts.py 和 facade.py。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryRecordContract:
    """记忆记录契约 — 其他模块通过此契约读取记忆信息"""

    id: str
    """记忆记录 ID"""
    memory_type: str
    """记忆类型"""
    chapter_index: int | None = None
    """所属章节索引"""
    title: str | None = None
    """记忆标题"""
    summary: str = ""
    """记忆摘要"""
    visibility: str = "reader_known"
    """读者可见性"""
    known_by_character_ids: list[str] = field(default_factory=list)
    """已知该记忆的角色 ID 列表"""
    related_entity_ids: list[str] = field(default_factory=list)
    """关联世界对象 ID 列表"""
    related_character_ids: list[str] = field(default_factory=list)
    """关联角色 ID 列表"""
    related_thread_ids: list[str] = field(default_factory=list)
    """关联剧情线 ID 列表"""
    importance: float = 0.5
    """重要性"""


@dataclass(frozen=True)
class MemoryUpdateProposalContract:
    """记忆更新提案契约 — 其他模块可读取待处理的提案"""

    id: str
    """提案 ID"""
    proposal_type: str
    """提案类型"""
    payload: dict[str, Any] = field(default_factory=dict)
    """提案内容"""
    confidence: float = 0.5
    """AI 置信度"""
    reason: str | None = None
    """提案理由"""
    decision: str = "pending"
    """决策状态"""
