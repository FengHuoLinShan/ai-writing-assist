"""
Project 对外契约

定义其他模块可以安全依赖的项目接口和数据类。
仅可导入 contracts.py 和 facade.py。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from modules.project.schemas import ProjectContext  # noqa: F401


@dataclass(frozen=True)
class ProjectSummary:
    """Lightweight active project projection for cross-module aggregations."""

    project_id: uuid.UUID
    title: str
