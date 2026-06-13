"""
Import Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.schemas import ImportResponse
from modules.imports.services import ImportService
from shared.utils import parse_uuid as _parse_uuid

_service = ImportService()


async def import_file(
    db: AsyncSession,
    novel_id: str,
    file_name: str,
    file_content: bytes,
) -> ImportResponse:
    return await _service.upload_and_import(db, novel_id, file_name, file_content)


def _scene_overlaps_range(scene: dict[str, Any], start: int, end: int) -> bool:
    chapter_ids = scene.get("chapter_ids") or []
    try:
        indices = [int(x) for x in chapter_ids if x is not None]
    except (ValueError, TypeError):
        return False
    if not indices:
        return False
    return any(start <= idx <= end for idx in indices)


async def _check_duplicate_import(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> str | None:
    """检查指定章节范围内是否已有派生 Scene 或实体数据。"""
    from modules.outline.facade import get_scenes_by_novel
    from modules.world.facade import list_auto_ingested_entities

    scenes = await get_scenes_by_novel(db, novel_id, status_filter=["draft", "canonical"])
    overlapping_scenes = [
        s for s in scenes if _scene_overlaps_range(s, start_chapter, end_chapter)
    ]

    overlapping_entities = await list_auto_ingested_entities(
        db,
        novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )

    if overlapping_scenes or overlapping_entities:
        return (
            f"第 {start_chapter}-{end_chapter} 章已有 "
            f"{len(overlapping_scenes)} 个 Scene、"
            f"{len(overlapping_entities)} 个实体。"
            f"重新导入将覆盖/刷新该范围数据。是否继续？"
        )
    return None


async def _deprecate_derived_data(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> dict[str, int]:
    """将指定章节范围内的旧派生 Scene 和自动实体标记为 deprecated。"""
    from modules.outline.facade import get_scenes_by_novel, update_scene
    from modules.world.facade import list_auto_ingested_entities, update_entity

    deprecated_scenes = 0
    scenes = await get_scenes_by_novel(db, novel_id, status_filter=["draft", "canonical"])
    for scene in scenes:
        if _scene_overlaps_range(scene, start_chapter, end_chapter):
            await update_scene(db, novel_id, scene["id"], {"status": "deprecated"})
            deprecated_scenes += 1

    deprecated_entities = 0
    entities = await list_auto_ingested_entities(
        db,
        novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )
    for entity in entities:
        await update_entity(db, novel_id, entity["id"], {"status": "deprecated"})
        deprecated_entities += 1

    return {
        "deprecated_scenes": deprecated_scenes,
        "deprecated_entities": deprecated_entities,
    }


async def start_deep_import(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    force: bool = False,
) -> dict[str, Any]:
    """提交深度导入任务（异步）

    自动执行三阶段流水线：Scene 切分 → 实体增量提取 → 剧情结构分析。
    """
    from infrastructure.tasks.enqueuer import enqueue_task

    warning = await _check_duplicate_import(db, novel_id, start_chapter, end_chapter)
    if warning and not force:
        return {
            "workflow_id": None,
            "task_id": None,
            "status": "requires_confirmation",
            "requires_confirmation": True,
            "warning": warning,
            "message": warning,
        }

    if force:
        await _deprecate_derived_data(db, novel_id, start_chapter, end_chapter)

    task_id = enqueue_task(
        db,
        "deep_import",
        meta={
            "novel_id": novel_id,
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
        },
    )
    await db.flush()

    result: dict[str, Any] = {
        "workflow_id": str(task_id),
        "task_id": str(task_id),
        "status": "pending",
        "requires_confirmation": False,
        "message": f"深度导入任务已提交（第{start_chapter}-{end_chapter}章）",
    }
    return result


async def resume_deep_import(
    db: AsyncSession,
    prev_task_id: str,
) -> dict[str, Any]:
    """（已废弃）候选管理已移除，深度导入全自动执行。"""
    from sqlalchemy import select

    from infrastructure.tasks.enqueuer import enqueue_task
    from infrastructure.tasks.models import AsyncTask

    stmt = select(AsyncTask).where(AsyncTask.id == _parse_uuid(prev_task_id))
    result = await db.execute(stmt)
    prev_task = result.scalar_one_or_none()
    if prev_task is None:
        from modules.imports.contracts import TaskNotFoundError

        raise TaskNotFoundError(prev_task_id)

    prev_meta = prev_task.meta or {}
    task_meta = dict(prev_meta)
    task_meta["prev_task_id"] = prev_task_id

    task_id = enqueue_task(
        db,
        "deep_import_resume",
        meta=task_meta,
    )
    await db.flush()

    return {
        "task_id": task_id,
        "status": "pending",
        "message": "深度导入继续任务已提交",
    }
