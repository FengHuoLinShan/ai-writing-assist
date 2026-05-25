"""Deep Import Workflow Schema

定义深度导入流水线的进度状态数据结构。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DeepImportStep(str, Enum):
    """深度导入步骤标识"""

    extract_world = "extract_world"
    sync_characters = "sync_characters"
    generate_plot = "generate_plot"


class DeepImportProgress(BaseModel):
    """深度导入进度状态"""

    phase: str = Field(
        default="pending",
        description="阶段: pending / running / awaiting_review / done / failed",
    )
    current_step: DeepImportStep | None = Field(
        default=None,
        description="当前正在执行的步骤",
    )
    total_steps: int = Field(default=3, description="总步骤数")
    completed_steps: list[str] = Field(
        default_factory=list,
        description="已完成的步骤列表",
    )
    message: str = Field(
        default="",
        description="当前步骤的描述/提示消息",
    )
