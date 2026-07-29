"""
Project 对外契约

定义其他模块可以安全依赖的项目接口和数据类。
仅可导入 contracts.py 和 facade.py。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from core.errors import ValidationError
from modules.project.schemas import ProjectContext  # noqa: F401


@dataclass(frozen=True)
class ProjectSummary:
    """Lightweight active project projection for cross-module aggregations."""

    project_id: uuid.UUID
    title: str


@dataclass(frozen=True)
class InteractionProjectContract:
    """Hidden interaction project created for exactly one RP journey."""

    novel_id: str
    owner_id: uuid.UUID


class ProjectLLMConfigurationError(ValidationError):
    """The requested project has no usable business LLM profile."""

    code = "project_llm_configuration_error"
