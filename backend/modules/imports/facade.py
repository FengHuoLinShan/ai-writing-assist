"""
Import Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.services import ImportService
from modules.imports.schemas import ImportResponse

_service = ImportService()


async def import_file(
    db: AsyncSession,
    novel_id: str,
    file_name: str,
    file_content: bytes,
) -> ImportResponse:
    """导入小说文件

    供其他模块（如生成中心、命令行工具）调用导入能力。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        file_name: 原始文件名
        file_content: 文件二进制内容

    Returns:
        ImportResponse — 导入结果
    """
    return await _service.upload_and_import(db, novel_id, file_name, file_content)


async def start_deep_import(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> dict[str, Any]:
    """提交深度导入任务（异步）

    创建一个 deep_import 后台任务，从章节正文中依次执行
    世界对象抽取、人物同步和剧情结构生成。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        start_chapter: 起始章节
        end_chapter: 结束章节

    Returns:
        包含 task_id 和 status 的字典
    """
    import uuid

    from infrastructure.tasks.models import AsyncTask
    from shared.enums import TaskStatus as TaskStatusEnum

    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="deep_import",
        status=TaskStatusEnum.pending.value,
        meta={
            "novel_id": novel_id,
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
        },
        progress=0.0,
    )
    db.add(task)
    await db.flush()

    return {
        "task_id": str(task.id),
        "status": str(task.status),
        "message": f"深度导入任务已提交（第{start_chapter}-{end_chapter}章）",
    }


async def resume_deep_import(
    db: AsyncSession,
    prev_task_id: str,
) -> dict[str, Any]:
    """继续深度导入任务（异步）

    在用户确认所有候选后，继续执行人物同步和剧情结构生成。

    Args:
        db: 数据库 session
        prev_task_id: 前一个 deep_import 任务的 ID

    Returns:
        包含 task_id 和 status 的字典
    """
    import uuid

    from infrastructure.tasks.models import AsyncTask
    from sqlalchemy import select
    from shared.enums import TaskStatus as TaskStatusEnum

    # 读取前一个任务的 meta 获取章节范围
    stmt = select(AsyncTask).where(AsyncTask.id == _parse_uuid(prev_task_id))
    result = await db.execute(stmt)
    prev_task = result.scalar_one_or_none()
    if prev_task is None:
        from fastapi import HTTPException
        raise HTTPException(404, detail=f"Previous task not found: {prev_task_id}")

    prev_meta = prev_task.meta or {}
    novel_id = prev_meta.get("novel_id", "")

    task_meta = dict(prev_meta)
    task_meta["prev_task_id"] = prev_task_id

    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="deep_import_resume",
        status=TaskStatusEnum.pending.value,
        meta=task_meta,
        progress=0.0,
    )
    db.add(task)
    await db.flush()

    return {
        "task_id": str(task.id),
        "status": str(task.status),
        "message": "深度导入继续任务已提交",
    }


def _parse_uuid(value: str) -> object:
    """解析 UUID 字符串"""
    import uuid
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ValueError(f"Invalid UUID: {value}")
