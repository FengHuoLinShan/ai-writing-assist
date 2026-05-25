"""
Writing Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.contracts import WritingDraftContract
from modules.writing.schemas import WritingDraftCreate, WritingDraftResponse
from modules.writing.services import WritingDraftService

_service = WritingDraftService()


async def create_draft(
    db: AsyncSession,
    data: WritingDraftCreate,
) -> WritingDraftResponse:
    """创建正文草稿

    供其他模块（如 imports）写入导入的章节正文。

    Args:
        db: 数据库 session
        data: 草稿创建数据

    Returns:
        WritingDraftResponse — 创建后的草稿信息
    """
    return await _service.create_draft(db, data)


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


async def list_chapter_indices(
    db: AsyncSession,
    novel_id: str,
) -> list[int]:
    """列出该小说所有有草稿的章节索引（去重、升序）

    供前端构建章节树使用。

    Args:
        db: 数据库 session
        novel_id: 小说项目 ID

    Returns:
        list[int] — 有草稿的章节索引列表
    """
    return await _service.list_chapter_indices(db, novel_id)
