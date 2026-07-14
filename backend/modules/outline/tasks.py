from __future__ import annotations

import logging

from infrastructure.tasks.registry import task_handler

logger = logging.getLogger(__name__)


def _require_str(meta: dict, key: str, task_type: str) -> str:
    value = str(meta.get(key) or "")
    if not value:
        raise ValueError(f"{key} is required for {task_type}")
    return value


def _int_or_default(value: object, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


async def _require_llm_execution_snapshot(db, task, meta: dict, novel_id: str) -> dict:
    from infrastructure.tasks.facade import require_task_checkpoint_session

    require_task_checkpoint_session(db)
    snapshot = meta.get("llm_execution_snapshot")
    if isinstance(snapshot, dict) and snapshot:
        return dict(snapshot)

    # Compatibility for tasks created before submission-time snapshots existed.
    # Freeze and lease-fence the profile before any provider call.
    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        require_active_project,
    )

    await require_active_project(db, novel_id)
    snapshot = await build_project_llm_execution_snapshot(db, novel_id)
    task.meta = {**meta, "llm_execution_snapshot": snapshot}
    await db.commit()
    return snapshot


@task_handler("plot_structure_generate", recovery_policy="restart_origin")
async def handle_plot_structure_generate(db, task):
    """处理 legacy 剧情结构 preview 生成任务。

    根据已有世界对象和人物生成剧情线和篇章纲 preview，
    不直接持久化，也不能绕过新的确认采用路径。

    Task meta 参数：
    - novel_id: 项目 ID
    - start_chapter: 起始章节（可选，默认 1）
    - end_chapter: 结束章节（可选，默认 10）
    """
    # 延迟导入，避免 infrastructure.tasks 初始化时形成循环依赖
    from modules.outline.ai_workflow_service import OutlineAIWorkflowService

    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 10))

    if not novel_id:
        raise ValueError("novel_id is required for plot_structure_generate")

    llm_execution_snapshot = await _require_llm_execution_snapshot(
        db,
        task,
        meta,
        novel_id,
    )

    task.update_progress(0.1)

    result = await OutlineAIWorkflowService().generate_legacy_preview_for_task(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        llm_execution_snapshot=llm_execution_snapshot,
    )
    task.update_progress(0.85)

    logger.info(
        "Plot structure preview complete: %d threads, %d arcs",
        result["total_threads"],
        result["total_arcs"],
    )
    task.update_progress(0.95)

    return result


@task_handler("chapter_card_extraction", recovery_policy="restart_origin")
async def handle_chapter_card_extraction(db, task):
    """兼容旧任务类型：章节卡生成尚未有独立 domain handler。

    当前真实生成入口是 /api/outline/generate，只产生 preview，
    经 /api/outline/generate/apply 确认后才写入。这里注册旧 task type，
    避免 worker 以“无 handler”失败，并让
    前端轮询可以看到结构化 unsupported 结果。
    """
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 10))

    if not novel_id:
        raise ValueError("novel_id is required for chapter_card_extraction")

    task.update_progress(0.1)
    task.update_progress(1.0)

    logger.warning(
        "chapter_card_extraction is unsupported; use plot_structure_generate "
        "or /api/outline/generate instead (novel_id=%s, chapters=%d-%d)",
        novel_id,
        start_chapter,
        end_chapter,
    )

    return {
        "status": "unsupported",
        "task_type": "chapter_card_extraction",
        "novel_id": novel_id,
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
        "message": (
            "chapter_card_extraction is not implemented as an async task. "
            "Use /api/outline/generate to create a preview, then apply it."
        ),
    }


@task_handler("chapter_scene_generate", recovery_policy="restart_origin")
async def handle_chapter_scene_generate(db, task):
    """兼容任务枚举中的章节/场景生成类型。

    当前还没有独立异步章节卡生成器。复用 chapter_card_extraction 的结构化
    unsupported 响应，确保前端轮询能得到可展示结果，而不是 worker 无 handler。
    """
    result = await handle_chapter_card_extraction(db, task)
    return {
        **result,
        "task_type": "chapter_scene_generate",
        "message": (
            "chapter_scene_generate is not implemented as an async task. "
            "Use /api/outline/generate to create a preview, then apply it."
        ),
    }


@task_handler("outline_analyze", recovery_policy="restart_origin")
async def handle_outline_analyze(db, task):
    """处理确认后的剧情分析任务。"""
    from modules.outline.ai_workflow_service import OutlineAIWorkflowService

    meta = task.meta or {}
    novel_id = _require_str(meta, "novel_id", "outline_analyze")
    confirmation_id = _require_str(
        meta,
        "context_confirmation_id",
        "outline_analyze",
    )
    llm_execution_snapshot = await _require_llm_execution_snapshot(
        db,
        task,
        meta,
        novel_id,
    )
    return await OutlineAIWorkflowService().analyze_for_task(
        db,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        task_id=str(task.id),
        instruction=meta.get("instruction"),
        llm_execution_snapshot=llm_execution_snapshot,
        progress_callback=task.update_progress,
    )


@task_handler("outline_generate", recovery_policy="restart_origin")
async def handle_outline_generate(db, task):
    """处理确认上下文后的剧情结构 preview 生成任务。"""
    from modules.outline.ai_workflow_service import OutlineAIWorkflowService

    meta = task.meta or {}
    novel_id = _require_str(meta, "novel_id", "outline_generate")
    confirmation_id = _require_str(
        meta,
        "context_confirmation_id",
        "outline_generate",
    )
    start_chapter = _int_or_default(meta.get("start_chapter"), 1)
    end_chapter = _int_or_default(meta.get("end_chapter"), 10)
    llm_execution_snapshot = await _require_llm_execution_snapshot(
        db,
        task,
        meta,
        novel_id,
    )

    result = await OutlineAIWorkflowService().generate_for_task(
        db,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        task_id=str(task.id),
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        llm_execution_snapshot=llm_execution_snapshot,
        progress_callback=task.update_progress,
    )
    logger.info(
        "Outline preview generation complete: %d threads, %d arcs",
        result["total_threads"],
        result["total_arcs"],
    )
    return result


@task_handler("outline_chapter_scenes_extract", recovery_policy="restart_origin")
async def handle_outline_chapter_scenes_extract(db, task):
    """处理确认后的章节/Scene 卡提取任务。"""
    from modules.outline.ai_workflow_service import OutlineAIWorkflowService

    meta = task.meta or {}
    novel_id = _require_str(meta, "novel_id", "outline_chapter_scenes_extract")
    confirmation_id = _require_str(
        meta,
        "context_confirmation_id",
        "outline_chapter_scenes_extract",
    )
    chapter_index = _int_or_default(meta.get("chapter_index"), 1)
    llm_execution_snapshot = await _require_llm_execution_snapshot(
        db,
        task,
        meta,
        novel_id,
    )

    return await OutlineAIWorkflowService().extract_chapter_scenes_for_task(
        db,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        task_id=str(task.id),
        chapter_index=chapter_index,
        instruction=meta.get("instruction"),
        llm_execution_snapshot=llm_execution_snapshot,
        progress_callback=task.update_progress,
    )
