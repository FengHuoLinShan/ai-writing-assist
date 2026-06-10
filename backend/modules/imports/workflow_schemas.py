"""Deep Import Workflow Schema

定义深度导入流水线的进度状态数据结构。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DeepImportStep(str, Enum):
    """深度导入步骤标识"""

    scene_segmentation = "scene_segmentation"
    """Phase 1: Scene 切分（并行）"""
    entity_extraction = "entity_extraction"
    """Phase 2: 实体增量提取（串行，按 Scene）"""
    structure_analysis = "structure_analysis"
    """Phase 3: 剧情结构分析（单次）"""


class DeepImportProgress(BaseModel):
    """深度导入进度状态"""

    phase: str = Field(
        default="pending",
        description="阶段: pending / running / done / failed",
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
    phase1_total_batches: int = Field(default=0, description="Phase 1 总批次数")
    phase1_completed_batches: int = Field(default=0, description="Phase 1 已完成批次数")
    phase2_total_scenes: int = Field(default=0, description="Phase 2 总 Scene 数")
    phase2_completed_scenes: int = Field(default=0, description="Phase 2 已完成 Scene 数")
    degraded: bool = Field(default=False, description="是否有批次触发降级")
    degraded_batches: list[int] = Field(
        default_factory=list, description="触发降级的批次索引"
    )
