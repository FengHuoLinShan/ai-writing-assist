"""
Project 对外契约

定义其他模块可以安全依赖的项目接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProjectContract:
    """小说项目契约 — 其他模块通过此契约获取项目元信息

    所有字段均为只读，不可变对象。
    """

    novel_id: str
    """项目 ID（其他模块用 novel_id 引用）"""
    title: str
    """项目标题"""
    genre: str | None = None
    """题材"""
    tone: str | None = None
    """风格基调"""
    language: str = "zh"
    """创作语言"""
    target_length: str | None = None
    """目标规模"""
    current_stage: str | None = None
    """当前创作阶段"""
    default_reveal_policy: str = "author_safe"
    """默认揭示策略"""


# facade 返回类型（Pydantic schema），供跨模块导入使用
from modules.project.schemas import ProjectContext  # noqa: F401 — facade.get_project_context 返回
