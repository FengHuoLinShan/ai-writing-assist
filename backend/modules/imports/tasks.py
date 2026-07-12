"""Import 任务处理器

注册深度导入流水线的异步任务处理器。
"""

from __future__ import annotations

import logging
from typing import Any

from infrastructure.tasks.registry import task_handler
from modules.imports.orchestrator import DeepImportOrchestrator

logger = logging.getLogger(__name__)


@task_handler("deep_import", recovery_policy="manual_resume")
async def handle_deep_import(db, task) -> dict[str, Any]:
    """处理深度导入任务 — 全自动三阶段（Scene 切分 + 实体提取 + 结构分析）

    Task meta 参数：
    - novel_id: 项目 ID
    - start_chapter: 起始章节
    - end_chapter: 结束章节
    """
    result = await DeepImportOrchestrator().run_task(db, task)

    logger.info(
        "Deep import complete — phase=%s, completed=%s",
        result["phase"],
        result["completed_steps"],
    )

    return result


@task_handler("scene_auto_extraction", recovery_policy="manual_resume")
async def handle_scene_auto_extraction(db, task) -> dict[str, Any]:
    """处理场景（scene）自动提取任务 — Phase0/1a/1b + Scene commit。"""
    result = await DeepImportOrchestrator().run_stage_task(db, task, stage="scenes")
    logger.info(
        "Scene auto extraction complete — phase=%s, completed=%s",
        result["phase"],
        result["completed_steps"],
    )
    return result


@task_handler("world_object_auto_extraction", recovery_policy="manual_resume")
async def handle_world_object_auto_extraction(db, task) -> dict[str, Any]:
    """处理世界对象与别名/关系自动提取任务 — Phase2a/2b。"""
    result = await DeepImportOrchestrator().run_stage_task(
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
    result = await DeepImportOrchestrator().run_stage_task(
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
