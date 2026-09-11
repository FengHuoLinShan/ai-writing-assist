"""
全局枚举定义

所有模块公用的枚举类型，集中定义在此处，
避免跨模块的循环导入和重复定义。
"""

from __future__ import annotations

from enum import StrEnum


class CandidateAction(StrEnum):
    """候选对象建议动作"""

    create_new = "create_new"
    """创建为新正史对象"""
    merge_with_existing = "merge_with_existing"
    """合并到已有对象"""
    alias_of_existing = "alias_of_existing"
    """标记为已有对象的别名"""
    ignore = "ignore"
    """忽略该候选"""
    temporary_only = "temporary_only"
    """仅临时使用，不建议入正史"""
    needs_user_decision = "needs_user_decision"
    """需要用户决策"""

class RelationType(StrEnum):
    """实体间关系类型（通用）"""

    # 人物关系
    parent_of = "parent_of"
    child_of = "child_of"
    spouse_of = "spouse_of"
    sibling_of = "sibling_of"
    friend_of = "friend_of"
    rival_of = "rival_of"
    enemy_of = "enemy_of"
    ally_of = "ally_of"
    mentor_of = "mentor_of"
    student_of = "student_of"
    lover_of = "lover_of"
    master_of = "master_of"
    servant_of = "servant_of"
    # 势力关系
    member_of = "member_of"
    leader_of = "leader_of"
    allied_with = "allied_with"
    at_war_with = "at_war_with"
    trading_with = "trading_with"
    # 对象关系
    belongs_to = "belongs_to"
    created_by = "created_by"
    located_at = "located_at"
    contains = "contains"
    controls = "controls"
    # 通用
    related_to = "related_to"
    opposes = "opposes"
    supports = "supports"

class TaskStatus(StrEnum):
    """异步任务状态"""

    pending = "pending"
    """等待中"""
    running = "running"
    """运行中"""
    done = "done"
    """已完成"""
    failed = "failed"
    """失败"""
    cancelled = "cancelled"
    """已取消"""
