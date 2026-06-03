"""
Writing Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.enqueuer import enqueue_task
from modules.writing.contracts import WritingDraftContract
from modules.writing.schemas import WritingDraftCreate, WritingDraftResponse
from modules.writing.services import WritingDraftService

_service = WritingDraftService()


async def create_draft(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    title: str | None = None,
    content: str = "",
) -> tuple[WritingDraftResponse, str]:
    """创建正文草稿并触发发布流程

    供其他模块（如 imports）写入导入的章节正文。

    Returns:
        (WritingDraftResponse, task_id) — 草稿信息 + 发布任务 ID
    """
    data = WritingDraftCreate(
        novel_id=novel_id,
        chapter_index=chapter_index,
        title=title or f"第{chapter_index}章",
        content=content,
    )
    draft = await _service.create_draft(db, data)
    task_id = enqueue_task(
        db,
        "publish_chapter",
        meta={"novel_id": novel_id, "chapter_index": chapter_index},
    )
    return draft, task_id


async def get_draft(
    db: AsyncSession,
    draft_id: str,
) -> WritingDraftContract | None:
    """获取单个草稿的契约信息"""
    return await _service.get_draft_contract(db, draft_id)


async def get_latest_draft_for_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> WritingDraftContract | None:
    """获取指定章节的最新草稿"""
    return await _service.get_latest_draft_contract(db, novel_id, chapter_index)


async def list_chapter_indices(
    db: AsyncSession,
    novel_id: str,
) -> list[int]:
    """列出该小说所有有草稿的章节索引（去重、升序）"""
    return await _service.list_chapter_indices(db, novel_id)
