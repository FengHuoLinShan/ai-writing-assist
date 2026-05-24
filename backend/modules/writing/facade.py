"""
Writing Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.contracts import WritingDraftContract
from modules.writing.services import WritingDraftService

_service = WritingDraftService()


async def get_draft(
    db: AsyncSession,
    draft_id: str,
) -> WritingDraftContract | None:
    """获取单个草稿的契约信息

    供其他模块（如 review、context）读取草稿内容。

    Args:
        db: 数据库 session
        draft_id: 草稿 ID (UUID hex string)

    Returns:
        WritingDraftContract | None — 草稿不存在时返回 None
    """
    return await _service.get_draft_contract(db, draft_id)


async def get_latest_draft_for_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> WritingDraftContract | None:
    """获取指定章节的最新草稿

    供其他模块获取当前可用的最新版本正文。

    Args:
        db: 数据库 session
        novel_id: 小说项目 ID
        chapter_index: 章节索引

    Returns:
        WritingDraftContract | None — 无草稿时返回 None
    """
    return await _service.get_latest_draft_contract(db, novel_id, chapter_index)
