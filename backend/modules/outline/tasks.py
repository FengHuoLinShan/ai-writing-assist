from __future__ import annotations

import logging

from infrastructure.tasks.registry import task_handler

logger = logging.getLogger(__name__)


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
