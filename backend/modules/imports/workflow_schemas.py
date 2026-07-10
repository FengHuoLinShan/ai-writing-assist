"""Deep Import Workflow Schema

定义深度导入流水线的进度状态数据结构。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

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
    workflow_type: str = Field(
        default="deep_import",
        description=(
            "工作流类型: deep_import / scene_auto_extraction / "
            "world_object_auto_extraction / plot_structure_auto_extraction"
        ),
    )
    stage: str | None = Field(
        default=None,
        description="分阶段自动提取标识: scenes / world_objects / plot_structure",
    )
    adoption_policy: str = Field(
        default="user_authorized_pipeline",
        description="用户启动流水线时确认的资产采用策略",
    )
    authorization_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="流水线启动时的授权范围与时间快照",
    )
    asset_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="按已采用/待处理/未采用聚合的资产结果",
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
    current_phase: str | None = Field(
        default=None,
        description="当前细分阶段，用于恢复刷新后的深度导入进度展示",
    )
    current_round: str | None = Field(
        default=None,
        description="当前处理轮次",
    )
    current_chapter_range: str | None = Field(
        default=None,
        description="当前处理章节范围",
    )
    current_chapter: int | None = Field(
        default=None,
        description="当前处理章节",
    )
    current_scene_candidate_id: str | None = Field(
        default=None,
        description="最近完成处理的 Scene candidate 标识（并发下为最近完成项）",
    )
    current_window: str | None = Field(
        default=None,
        description="当前处理窗口",
    )
    current_operation: str | None = Field(
        default=None,
        description="当前具体操作",
    )
    current_item: dict[str, Any] = Field(
        default_factory=dict,
        description="当前处理对象摘要（batch/window/chapter/scene 等，不含正文）",
    )
    phase1_total_batches: int = Field(default=0, description="Phase 1 总批次数")
    phase1_completed_batches: int = Field(default=0, description="Phase 1 已完成批次数")
    phase2_total_scenes: int = Field(default=0, description="Phase 2 总 Scene 数")
    phase2_completed_scenes: int = Field(default=0, description="Phase 2 已完成 Scene 数")
    phase_timeline: list[dict[str, Any]] = Field(
        default_factory=list,
        description="阶段开始/结束/耗时/状态诊断时间线",
    )
    progress_events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="服务级 compact 事件流（不含正文、API key 或 raw prompt）",
    )
    acceptance_checks: list[dict[str, Any]] = Field(
        default_factory=list,
        description="服务级结构化门禁检查摘要",
    )
    diagnostic_counts: dict[str, Any] = Field(
        default_factory=dict,
        description="当前累计输出和诊断计数摘要",
    )
    last_error: dict[str, str] | None = Field(
        default=None,
        description="最近一次机器可读错误摘要",
    )
    quality_stats: dict[str, Any] = Field(
        default_factory=dict,
        description="各阶段质量统计",
    )
    phase_artifacts: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "服务级分阶段 compact artifact 摘要（不含正文、API key 或 raw prompt）"
        ),
    )
    checkpoints: dict[str, Any] = Field(
        default_factory=dict,
        description="可恢复执行的检查点摘要",
    )
    recovery_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="中断恢复提示摘要",
    )
    interrupted: bool = Field(default=False, description="任务是否被检测为中断")
    recoverable: bool = Field(default=False, description="任务是否可恢复")
    recovery_required: bool = Field(
        default=False,
        description="前端是否应进入恢复确认流程",
    )
    interrupted_at: str | None = Field(default=None, description="中断检测时间")
    last_heartbeat_at: str | None = Field(
        default=None,
        description="最后一次任务心跳时间",
    )
    degraded: bool = Field(default=False, description="是否有批次触发降级")
    degraded_reason: str | None = Field(default=None, description="降级原因")
    phase1a_fallback: bool = Field(
        default=False,
        description="是否使用 Phase 1a fallback 结果",
    )
    degraded_batches: list[int] = Field(
        default_factory=list, description="触发降级的批次索引"
    )
    phase_errors: list[dict[str, Any]] = Field(
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
