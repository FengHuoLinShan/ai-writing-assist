"""
Review 对外契约

定义其他模块可以安全依赖的复查模块接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from modules.review.schemas import ReviewReportContext  # noqa: F401


@dataclass(frozen=True)
class ReviewWarningContract:
    """复查警告契约 — 单个警告项"""

    type: str
    """警告类型：schema/entity_reference/early_reveal/character_knowledge/
    timeline_conflict/geo_conflict/duplicate"""
    message: str
    """警告描述"""
    severity: str = "medium"
    """严重程度：low/medium/high"""
    location: dict[str, Any] = field(default_factory=dict)
    """问题位置（如字段路径等）"""


@dataclass(frozen=True)
class ReviewReportContract:
    """复查报告契约 — 其他模块通过此契约获取复查结果"""

    report_id: str
    """复查报告 ID"""
    novel_id: str
    """项目 ID"""
    target_type: str
    """复查目标类型"""
    target_id: str | None = None
    """复查目标 ID"""
    decision: str = "pass"
    """复查决策：pass/minor_revision/major_revision/reject"""
    score: float | None = None
    """综合评分"""
    problems: list[ReviewWarningContract] = field(default_factory=list)
    """问题列表"""
    conflict_warnings: list[ReviewWarningContract] = field(default_factory=list)
    """冲突警告"""
    early_reveal_warnings: list[ReviewWarningContract] = field(
        default_factory=list,
    )
    """提前揭示警告"""
    character_knowledge_warnings: list[ReviewWarningContract] = field(
        default_factory=list,
    )
    """人物知识边界警告"""
    duplicate_entity_warnings: list[ReviewWarningContract] = field(
        default_factory=list,
    )
    """对象重复警告"""
    geo_warnings: list[ReviewWarningContract] = field(default_factory=list)
    """地理冲突警告"""
    revision_instructions: list[str] = field(default_factory=list)
    """修改建议列表"""
