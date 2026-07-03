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


@task_handler("plot_structure_generate")
async def handle_plot_structure_generate(db, task):
    """处理剧情结构生成任务

    根据已有世界对象和人物，AI 生成剧情线和篇章纲。

    Task meta 参数：
    - novel_id: 项目 ID
    - start_chapter: 起始章节（可选，默认 1）
    - end_chapter: 结束章节（可选，默认 10）
    """
    # 延迟导入，避免 infrastructure.tasks 初始化时形成循环依赖
    from modules.outline.generator import PlotStructureGenerator

    generator = PlotStructureGenerator()

    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 10))

    if not novel_id:
        raise ValueError("novel_id is required for plot_structure_generate")

    task.update_progress(0.1)

    result = await generator.generate(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )
    task.update_progress(0.85)

    logger.info(
        "Plot structure generation complete: %d threads, %d arcs",
        result["total_threads"],
        result["total_arcs"],
    )
    task.update_progress(0.95)

    return result


@task_handler("chapter_card_extraction")
async def handle_chapter_card_extraction(db, task):
    """兼容旧任务类型：章节卡生成尚未有独立 domain handler。

    当前真实生成入口是 outline 的 plot_structure_generate / /api/outline/generate，
    会生成 scenes。这里注册旧 task type，避免 worker 以“无 handler”失败，并让
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
            "Use plot_structure_generate or /api/outline/generate to create scenes."
        ),
    }


@task_handler("chapter_scene_generate")
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
            "Use plot_structure_generate or /api/outline/generate to create scenes."
        ),
    }


@task_handler("scene_cross_chapter_detection")
async def handle_scene_cross_chapter_detection(db, task):
    """识别已提交 Scene 中可能跨多章的相邻 Scene 融合建议。"""
    from modules.outline.cross_chapter_detection import (
        CrossChapterDetectionService,
    )

    meta = task.meta or {}
    novel_id = _require_str(meta, "novel_id", "scene_cross_chapter_detection")
    task.update_progress(0.05)

    def _progress(value: float) -> None:
        task.update_progress(max(0.05, min(0.95, value)))

    result = await CrossChapterDetectionService().detect(
        db,
        novel_id=novel_id,
        start_chapter=meta.get("start_chapter"),
        end_chapter=meta.get("end_chapter"),
        max_chapter_span=int(meta.get("max_chapter_span", 6)),
        max_suggestions=int(meta.get("max_suggestions", 30)),
        max_chain_calls=int(meta.get("max_chain_calls", 6)),
        progress_callback=_progress,
    )
    task.update_progress(1.0)
    return result


@task_handler("outline_analyze")
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
    return await OutlineAIWorkflowService().analyze(
        db,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        task_id=str(task.id),
        instruction=meta.get("instruction"),
        progress_callback=task.update_progress,
    )


@task_handler("outline_generate")
async def handle_outline_generate(db, task):
    """处理确认后的剧情结构生成任务。"""
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

    result = await OutlineAIWorkflowService().generate(
        db,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        task_id=str(task.id),
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        progress_callback=task.update_progress,
    )
    logger.info(
        "Outline generation complete: %d threads, %d arcs",
        result["total_threads"],
        result["total_arcs"],
    )
    return result


@task_handler("outline_chapter_scenes_extract")
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

    return await OutlineAIWorkflowService().extract_chapter_scenes(
        db,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        task_id=str(task.id),
        chapter_index=chapter_index,
        instruction=meta.get("instruction"),
        progress_callback=task.update_progress,
    )
