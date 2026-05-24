"""
Character 对外契约

定义其他模块可以安全依赖的人物接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CharacterContract:
    """人物契约 — 其他模块通过此契约获取人物信息

    所有字段均为只读，不可变对象。
    """

    character_id: str
    """人物 ID"""
    name: str
    """人物名称"""
    role: str | None = None
    """角色定位"""
    current_goal: str | None = None
    """当前目标"""
    current_state: str | None = None
    """当前状态"""
    current_emotion: str | None = None
    """当前情绪"""
    stance: str | None = None
    """立场"""
    voice_style: str | None = None
    """语言风格"""
    behavior_rules: list[dict] = field(default_factory=list)
    """行为规则"""
    relationship_summary: str | None = None
    """关系摘要"""


@dataclass(frozen=True)
class CharacterKnowledgeContract:
    """人物知识契约 — 其他模块通过此契约获取人物知识边界

    用于 Context Compiler 和 Review 模块判断角色是否知道某信息。
    """

    target_type: str
    """目标类型"""
    target_id: str
    """目标 ID"""
    knowledge_level: str
    """了解程度（unknown/rumor/partial/full/false_belief）"""
    known_content: str | None = None
    """已知内容"""
    misconception: str | None = None
    """误解内容"""
