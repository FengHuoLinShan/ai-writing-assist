"""
World 任务处理器

注册 AI 生成/抽取相关的异步任务处理器。
"""

from __future__ import annotations

import inspect
import logging

from core.container import get as _container_get
from infrastructure.tasks.registry import task_handler
from modules.context import facade as context_facade
from modules.world.services.core.extraction_service import EntityExtractionService

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
    context_confirmation_id = str(meta.get("context_confirmation_id") or "")

    if not novel_id:
        raise ValueError("novel_id is required for world_entity_extraction")
    if context_confirmation_id:
        await context_facade.compile_from_confirmation(
            db,
            novel_id=novel_id,
            action="world.entities.extract",
            confirmation_id=context_confirmation_id,
        )

    task.update_progress(0.1)

    service = EntityExtractionService()
    result = await service.extract_entities_from_chapters(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        batch_size=batch_size,
    )
    task.update_progress(0.85)

    logger.info(
        "Entity extraction complete: %d created, %d skipped",
        result.total_created,
        result.total_skipped,
    )
    task.update_progress(0.95)

    if context_confirmation_id:
        result_refs = [
            {"type": "world_entity", "id": entity_id}
            for item in result.items
            if (entity_id := str(item.get("id") or ""))
        ]
        if result_refs:
            await context_facade.attach_result_refs(
                db,
                confirmation_id=context_confirmation_id,
                result_refs=result_refs,
                status="done",
            )
        else:
            await context_facade.attach_result_ref(
                db,
                confirmation_id=context_confirmation_id,
                result_type="world_entity_extraction",
                result_id=str(task.id),
                status="done",
            )

    task.update_progress(1.0)
    flush = getattr(db, "flush", None)
    if flush is not None:
        result_flush = flush()
        if inspect.isawaitable(result_flush):
            await result_flush
    return {
        "total_chapters": result.total_chapters,
        "total_created": result.total_created,
        "total_skipped": result.total_skipped,
        "failed_chapters": result.failed_chapters,
        "items": result.items,
    }


@task_handler("world_alias_relation_extraction")
async def handle_world_alias_relation_extraction(db, task):
    """处理别名/关系补抽任务。"""
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 10))
    scene_ids = meta.get("scene_ids")

    if not novel_id:
        raise ValueError("novel_id is required for world_alias_relation_extraction")

    task.update_progress(0.1)
    handler = _container_get("world.run_alias_relation_extraction")
    result = await handler(
        db,
        novel_id,
        workflow_id=str(task.id),
        scene_ids=scene_ids,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )
    task.update_progress(0.95)
    flush = getattr(db, "flush", None)
    if flush is not None:
        result_flush = flush()
        if inspect.isawaitable(result_flush):
            await result_flush
    task.update_progress(1.0)
    return result


@task_handler("world_entity_fusion_suggestions")
async def handle_world_entity_fusion_suggestions(db, task):
    """生成世界对象 LLM 融合/合并建议，不直接改实体。"""
    from modules.world.entity_fusion import WorldEntityFusionService

    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    if not novel_id:
        raise ValueError("novel_id is required for world_entity_fusion_suggestions")

    task.update_progress(0.05)

    def _progress(value: float) -> None:
        task.update_progress(max(0.05, min(0.95, value)))

    result = await WorldEntityFusionService().suggest(
        db,
        novel_id=novel_id,
        entity_type=meta.get("entity_type"),
        status=meta.get("status"),
        limit=int(meta.get("limit", 200)),
        max_suggestions=int(meta.get("max_suggestions", 50)),
        progress_callback=_progress,
    )
    task.update_progress(1.0)
    flush = getattr(db, "flush", None)
    if flush is not None:
        result_flush = flush()
        if inspect.isawaitable(result_flush):
            await result_flush
    return result


@task_handler("world_bible_projection_refresh")
async def handle_world_bible_projection_refresh(db, task):
    """Refresh a World Bible page projection."""
    from modules.world.services.worldbuilding.worldbuilding_service import (
        WorldBibleService,
    )

    meta = task.meta or {}
    novel_id = str(meta.get("novel_id") or "")
    page_id = str(meta.get("page_id") or "")
    projection_type = str(meta.get("projection_type") or "context_brief")
    if not novel_id or not page_id:
        raise ValueError("novel_id and page_id are required")

    task.update_progress(0.15)
    projection = await WorldBibleService().refresh_projection_now(
        db,
        novel_id=novel_id,
        page_id=page_id,
        projection_type=projection_type,
    )
    task.update_progress(1.0)
    flush = getattr(db, "flush", None)
    if flush is not None:
        result_flush = flush()
        if inspect.isawaitable(result_flush):
            await result_flush
    return {
        "projection_id": projection.id,
        "projection_type": projection.projection_type,
        "status": projection.status,
        "token_estimate": projection.token_estimate,
        "error_kind": projection.error_kind,
        "error_summary": projection.error_summary,
        "stale": projection.stale,
    }
