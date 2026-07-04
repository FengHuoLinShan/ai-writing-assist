"""
Writing Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.enqueuer import enqueue_task
from modules.writing.contracts import WritingDraftContract, WritingProjectStatsContract
from modules.writing.schemas import WritingDraftCreate, WritingDraftResponse
from modules.writing.services import WritingDraftService

_service = WritingDraftService()


async def create_draft_only(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    title: str | None = None,
    content: str = "",
) -> WritingDraftResponse:
    """创建正文草稿（纯持久化，不入队任务）"""
    data = WritingDraftCreate(
        novel_id=novel_id,
        chapter_index=chapter_index,
        title=title or f"第{chapter_index}章",
        content=content,
    )
    return await _service.create_draft(db, data)


async def create_draft(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    title: str | None = None,
    content: str = "",
) -> tuple[WritingDraftResponse, str]:
    """创建正文草稿并触发发布流程（兼容旧接口，新代码优先用 create_draft_only）

    Returns:
        (WritingDraftResponse, task_id) — 草稿信息 + 发布任务 ID
    """
    draft = await create_draft_only(db, novel_id, chapter_index, title, content)
    task_id = enqueue_task(
        db,
        "publish_chapter",
        meta={"novel_id": novel_id, "chapter_index": chapter_index},
    )
    return draft, task_id


async def get_draft(
    db: AsyncSession,
    novel_id: str,
    draft_id: str,
) -> WritingDraftContract | None:
    """获取单个草稿的契约信息"""
    return await _service.get_draft_contract(db, novel_id, draft_id)


async def get_latest_draft_for_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> WritingDraftContract | None:
    """获取指定章节的最新草稿"""
    return await _service.get_latest_draft_contract(db, novel_id, chapter_index)


async def list_latest_drafts_for_chapters(
    db: AsyncSession,
    novel_id: str,
    chapter_indices: list[int],
) -> list[WritingDraftContract]:
    """批量获取指定章节的最新草稿契约。"""
    return await _service.list_latest_draft_contracts(db, novel_id, chapter_indices)


async def list_chapter_indices(
    db: AsyncSession,
    novel_id: str,
) -> list[int]:
    """列出该小说所有有草稿的章节索引（去重、升序）"""
    return await _service.list_chapter_indices(db, novel_id)


async def get_project_writing_stats(
    db: AsyncSession,
    novel_id: str,
) -> WritingProjectStatsContract:
    """获取项目正文统计（每章只统计最新版本）。"""
    return await _service.get_project_stats(db, novel_id)


async def list_project_writing_stats(
    db: AsyncSession,
    novel_ids: list[str],
) -> dict[str, WritingProjectStatsContract]:
    """批量获取项目正文统计（每章只统计最新版本）。"""
    return await _service.list_project_stats(db, novel_ids)
