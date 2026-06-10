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


async def _check_duplicate_import(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> str | None:
    """检查章节范围内是否已有 Scene 或实体数据"""
    from sqlalchemy import func, select

    from modules.outline.models import Scene
    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")

    scene_stmt = select(func.count(Scene.id)).where(
        Scene.novel_id == nid,
        Scene.status.in_(["draft", "canonical"]),
    )
    scene_count = (await db.execute(scene_stmt)).scalar() or 0

    entity_stmt = select(func.count(CoreEntity.id)).where(
        CoreEntity.novel_id == nid,
        CoreEntity.status.in_(["canonical", "draft"]),
    )
    entity_count = (await db.execute(entity_stmt)).scalar() or 0

    if scene_count > 0 or entity_count > 0:
        return (
            f"第 {start_chapter}-{end_chapter} 章已有 {scene_count} 个 Scene、"
            f"{entity_count} 个实体。重新导入将覆盖现有数据。是否继续？"
        )
    return None


async def start_deep_import(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> dict[str, Any]:
    """提交深度导入任务（异步）

    自动执行三阶段流水线：Scene 切分 → 实体增量提取 → 剧情结构分析。
    """
    from infrastructure.tasks.enqueuer import enqueue_task

    warning = await _check_duplicate_import(db, novel_id, start_chapter, end_chapter)

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
        "task_id": task_id,
        "status": "pending",
        "message": f"深度导入任务已提交（第{start_chapter}-{end_chapter}章）",
    }
    if warning:
        result["warning"] = warning
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
