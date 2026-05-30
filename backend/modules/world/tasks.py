"""
World 任务处理器

注册 AI 生成/抽取相关的异步任务处理器。
"""

from __future__ import annotations

import logging

from infrastructure.tasks.registry import task_handler
from modules.world.services.extraction_service import EntityExtractionService

logger = logging.getLogger(__name__)


@task_handler("world_entity_extraction")
async def handle_world_entity_extraction(db, task):
    """处理世界对象抽取任务

    从指定章节范围抽取世界对象候选。

    Task meta 参数：
    - novel_id: 项目 ID
    - start_chapter: 起始章节
    - end_chapter: 结束章节
    - batch_size: 每批章节数（可选，默认 5）
    """
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 10))
    batch_size = int(meta.get("batch_size", 5))

    if not novel_id:
        raise ValueError("novel_id is required for world_entity_extraction")

    service = EntityExtractionService()
    result = await service.extract_entities_from_chapters(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        batch_size=batch_size,
    )

    logger.info(
        "Entity extraction complete: %d created, %d skipped",
        result.total_created,
        result.total_skipped,
    )

    return {
        "total_chapters": result.total_chapters,
        "total_created": result.total_created,
        "total_skipped": result.total_skipped,
        "items": result.items,
    }
