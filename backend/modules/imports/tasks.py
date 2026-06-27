"""Import 任务处理器

注册深度导入流水线的异步任务处理器。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import task_handler
from modules.imports.workflow import DeepImportWorkflow
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep
from shared.utils import parse_uuid as _parse_uuid

logger = logging.getLogger(__name__)


@task_handler("deep_import")
async def handle_deep_import(db, task) -> dict[str, Any]:
    """处理深度导入任务 — Step 1: 世界对象抽取

    Task meta 参数：
    - novel_id: 项目 ID
    - start_chapter: 起始章节
    - end_chapter: 结束章节
    """
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 5))

    if not novel_id:
        raise ValueError("novel_id is required for deep_import")

    workflow = DeepImportWorkflow()
    progress = DeepImportProgress()
    progress = await workflow.run_step(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        progress=progress,
    )

    logger.info(
        "Deep import step 1 complete — phase=%s, completed=%s",
        progress.phase,
        progress.completed_steps,
    )

    return {
        "phase": progress.phase,
        "current_step": progress.current_step.value if progress.current_step else None,
        "completed_steps": progress.completed_steps,
        "message": progress.message,
        "degraded": progress.degraded,
        "warnings": progress.warnings,
    }


@task_handler("deep_import_resume")
async def handle_deep_import_resume(db, task) -> dict[str, Any]:
    """继续深度导入任务 — Step 2+3

    Task meta 参数：
    - prev_task_id: 前一个 deep_import 任务的 ID
    - novel_id: 项目 ID
    - start_chapter: 起始章节
    - end_chapter: 结束章节
    """
    meta = task.meta or {}
    prev_task_id = meta.get("prev_task_id", "")
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 5))

    if not novel_id or not prev_task_id:
        raise ValueError("novel_id and prev_task_id are required for deep_import_resume")

    # 读取前一个任务的进度信息
    stmt = select(AsyncTask).where(AsyncTask.id == _parse_uuid(prev_task_id))
    result = await db.execute(stmt)
    prev_task = result.scalar_one_or_none()
    if prev_task is None:
        raise ValueError(f"Previous task not found: {prev_task_id}")

    if prev_task.task_type != "deep_import":
        raise ValueError("Previous task is not a deep_import task")
    if prev_task.status != "done":
        raise ValueError("Previous deep import task is not completed")

    prev_result = prev_task.result or {}
    completed = prev_result.get("completed_steps", [])
    if (
        prev_result.get("phase") != "awaiting_review"
        or DeepImportStep.extract_world.value not in completed
    ):
        raise ValueError("Previous deep import task is not awaiting review")

    progress = DeepImportProgress(
        phase="awaiting_review",
        completed_steps=completed,
    )

    workflow = DeepImportWorkflow()
    progress = await workflow.run_step(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        progress=progress,
    )

    logger.info(
        "Deep import resume complete — phase=%s, completed=%s",
        progress.phase,
        progress.completed_steps,
    )

    return {
        "phase": progress.phase,
        "current_step": progress.current_step.value if progress.current_step else None,
        "completed_steps": progress.completed_steps,
        "message": progress.message,
        "degraded": progress.degraded,
        "warnings": progress.warnings,
    }
