"""Deep Import Workflow Schema

定义深度导入流水线的进度状态数据结构。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DeepImportStep(StrEnum):
    """深度导入步骤标识"""

    scene_segmentation = "scene_segmentation"
    """Phase 1: Scene 切分（并行）"""
    entity_extraction = "entity_extraction"
    """Phase 2: 实体增量提取（串行，按 Scene）"""
    structure_analysis = "structure_analysis"
    """Phase 3: 剧情结构分析（单次）"""


class DeepImportProgress(BaseModel):
    """深度导入进度状态"""

    workflow_id: str | None = Field(
        default=None,
        description="业务层 workflow 标识（与 async task_id 一致）",
    )
    phase: str = Field(
        default="pending",
        description="阶段: pending / running / done / failed",
    )
    quality_status: str = Field(
        default="pending",
        description="质量状态: pending / complete / partial / failed",
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
    phase_errors: list[dict[str, str]] = Field(
        default_factory=list,
        description="各阶段可机器读取的失败/降级原因",
    )
    llm_health: dict | None = Field(
        default=None,
        description="启动前 LLM 健康检查摘要（不含 API key）",
    )
    audit_summary: dict = Field(
        default_factory=dict,
        description="深度导入上下文快照审计摘要",
    )
    snapshot_health_summary: dict = Field(
        default_factory=dict,
        description="深度导入上下文快照健康摘要（audit_summary 兼容 alias）",
    )
