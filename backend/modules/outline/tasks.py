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

    result = await generator.generate(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )

    logger.info(
        "Plot structure generation complete: %d threads, %d arcs",
        result["total_threads"],
        result["total_arcs"],
    )

    return result
