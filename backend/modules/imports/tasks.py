"""Import 任务处理器

注册深度导入流水线的异步任务处理器。
"""

from __future__ import annotations

import logging
from typing import Any

from infrastructure.tasks.registry import task_handler
from modules.imports.workflow import DeepImportWorkflow
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

logger = logging.getLogger(__name__)


@task_handler("deep_import")
async def handle_deep_import(db, task) -> dict[str, Any]:
    """处理深度导入任务 — 全自动三阶段（Scene 切分 + 实体提取 + 结构分析）

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

    async def _record_progress(
        updated: DeepImportProgress,
        progress_value: float,
    ) -> None:
        task.result = updated.model_dump(mode="json")
        task.update_progress(progress_value)
        await db.commit()

    progress = await workflow.run_step(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        progress=progress,
        on_progress=_record_progress,
    )

    logger.info(
        "Deep import complete — phase=%s, completed=%s",
        progress.phase,
        progress.completed_steps,
    )

    return {
        "phase": progress.phase,
        "current_step": progress.current_step.value if progress.current_step else None,
        "completed_steps": progress.completed_steps,
        "message": progress.message,
        "degraded": progress.degraded,
        "degraded_batches": progress.degraded_batches,
    }


@task_handler("deep_import_resume")
async def handle_deep_import_resume(db, task) -> dict[str, Any]:
    """（已废弃）候选管理已移除，深度导入全自动执行。

    保留 handler 注册以兼容已有队列任务。
    """
    logger.warning("deep_import_resume 已废弃 — 深度导入已改为全自动。忽略 resume 请求。")
    return {
        "phase": "done",
        "current_step": None,
        "completed_steps": [
            DeepImportStep.scene_segmentation.value,
            DeepImportStep.entity_extraction.value,
            DeepImportStep.structure_analysis.value,
        ],
        "message": "候选管理已移除，深度导入全自动执行。",
        "degraded": False,
        "degraded_batches": [],
    }
