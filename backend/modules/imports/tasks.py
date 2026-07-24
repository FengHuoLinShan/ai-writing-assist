"""Import 任务处理器

注册深度导入流水线的异步任务处理器。
"""

from __future__ import annotations

import logging
from typing import Any

from infrastructure.tasks.registry import task_handler
from modules.imports.orchestrator import DeepImportOrchestrator

logger = logging.getLogger(__name__)


def _uses_domain_workflow_run(db) -> bool:
    return bool(
        getattr(db, "task_checkpoint_enabled", False) is True
        or getattr(db, "task_inline_execution_enabled", False) is True
    )


async def _claim_workflow_attempt(db, task):
    from modules.imports.workflow_runs import ImportWorkflowRunService

    service = ImportWorkflowRunService()
    # A periodic stale-task pass can requeue/claim an auto-retry between
    # startup reconciliation cycles. Converge that newer queue attempt before
    # claiming the domain token; attempt+lease still invalidate the old worker.
    await service.reconcile_scoped_task_owners(
        db,
        task_id=str(task.id),
    )
    return await service.claim_attempt(
        db,
        task_id=str(task.id),
        workflow_type=str(task.task_type),
        attempt=int(task.attempt or 0),
        lease_id=str(task.lease_id or ""),
    )


async def _project_task(task, result: dict[str, Any], progress: float) -> None:
    """Update only the detached task API projection owned by TaskWorker."""
    task.result = dict(result)
    task.update_progress(progress)


@task_handler("deep_import", recovery_policy="manual_resume")
async def handle_deep_import(db, task) -> dict[str, Any]:
    """处理深度导入任务 — 全自动三阶段（Scene 切分 + 实体提取 + 结构分析）

    Task meta 参数：
    - novel_id: 项目 ID
    - start_chapter: 起始章节
    - end_chapter: 结束章节
    """
    orchestrator = DeepImportOrchestrator()
    if _uses_domain_workflow_run(db):
        attempt = await _claim_workflow_attempt(db, task)
        result = await orchestrator.run_attempt(
            db,
            attempt,
            project=lambda payload, value: _project_task(task, payload, value),
        )
    else:
        # Compatibility for isolated unit harnesses; production always enters
        # through TaskWorker's fenced handler session.
        result = await orchestrator.run_task(db, task)

    logger.info(
        "Deep import complete — phase=%s, completed=%s",
        result["phase"],
        result["completed_steps"],
    )

    return result


@task_handler("scene_auto_extraction", recovery_policy="manual_resume")
async def handle_scene_auto_extraction(db, task) -> dict[str, Any]:
    """处理从正文提取 Scene 任务 — Phase0/1a/1b + Scene commit。"""
    orchestrator = DeepImportOrchestrator()
    if _uses_domain_workflow_run(db):
        attempt = await _claim_workflow_attempt(db, task)
        result = await orchestrator.run_attempt(
            db,
            attempt,
            project=lambda payload, value: _project_task(task, payload, value),
        )
    else:
        result = await orchestrator.run_stage_task(db, task, stage="scenes")
    logger.info(
        "Scene auto extraction complete — phase=%s, completed=%s",
        result["phase"],
        result["completed_steps"],
    )
    return result


@task_handler("world_object_auto_extraction", recovery_policy="manual_resume")
async def handle_world_object_auto_extraction(db, task) -> dict[str, Any]:
    """处理世界对象与别名/关系自动提取任务 — Phase2a/2b。"""
    orchestrator = DeepImportOrchestrator()
    if _uses_domain_workflow_run(db):
        attempt = await _claim_workflow_attempt(db, task)
        result = await orchestrator.run_attempt(
            db,
            attempt,
            project=lambda payload, value: _project_task(task, payload, value),
        )
    else:
        result = await orchestrator.run_stage_task(
            db,
            task,
            stage="world_objects",
        )
    logger.info(
        "World object auto extraction complete — phase=%s, completed=%s",
        result["phase"],
        result["completed_steps"],
    )
    return result


@task_handler("plot_structure_auto_extraction", recovery_policy="manual_resume")
async def handle_plot_structure_auto_extraction(db, task) -> dict[str, Any]:
    """处理剧情线自动提取任务 — Phase3。"""
    orchestrator = DeepImportOrchestrator()
    if _uses_domain_workflow_run(db):
        attempt = await _claim_workflow_attempt(db, task)
        result = await orchestrator.run_attempt(
            db,
            attempt,
            project=lambda payload, value: _project_task(task, payload, value),
        )
    else:
        result = await orchestrator.run_stage_task(
            db,
            task,
            stage="plot_structure",
        )
    logger.info(
        "Plot structure auto extraction complete — phase=%s, completed=%s",
        result["phase"],
        result["completed_steps"],
    )
    return result


@task_handler(
    "map_observation_enrichment",
    recovery_policy="auto_requeue",
    max_attempts=3,
)
async def handle_map_observation_enrichment(db, task) -> dict[str, Any]:
    """Delegate map-only extraction to its checkpoint-owning orchestrator."""
    from modules.imports.map_observation_enrichment_workflow import (
        MapObservationEnrichmentTaskOrchestrator,
    )

    orchestrator = MapObservationEnrichmentTaskOrchestrator()
    if _uses_domain_workflow_run(db):
        attempt = await _claim_workflow_attempt(db, task)
        return await orchestrator.run_attempt(
            db,
            attempt,
            project=lambda payload, value: _project_task(task, payload, value),
        )
    return await orchestrator.run_task(db, task)
