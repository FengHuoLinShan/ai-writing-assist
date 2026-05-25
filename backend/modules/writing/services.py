"""
Writing 业务逻辑层

调用 repository 完成业务操作。
服务层可包含业务规则，但不直接操作数据库。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.contracts import WritingDraftContract
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import (
    DraftListItem,
    VersionHistoryResponse,
    WritingDraftCreate,
    WritingDraftResponse,
    WritingDraftUpdate,
)
from shared.utils import parse_uuid


class WritingDraftService:
    """正文草稿业务服务"""

    def __init__(self) -> None:
        self._repo = WritingDraftRepository()

    async def create_draft(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
    ) -> WritingDraftResponse:
        """创建新草稿（自动创建新版本）"""
        draft = await self._repo.create(db, data)
        return WritingDraftResponse.model_validate(draft)

    async def get_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
    ) -> WritingDraftResponse:
        """获取草稿详情"""
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )
        return WritingDraftResponse.model_validate(draft)

    async def update_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        data: WritingDraftUpdate,
        novel_id: str,
    ) -> WritingDraftResponse:
        """更新草稿"""
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )
        draft = await self._repo.update(db, did, data)
        return WritingDraftResponse.model_validate(draft)

    async def delete_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
    ) -> None:
        """删除草稿"""
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )
        await self._repo.delete(db, did)

    async def get_latest_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> WritingDraftResponse:
        """获取章节最新草稿"""
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get_latest_by_chapter(db, nid, chapter_index)
        if draft is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"No draft found for chapter {chapter_index} in novel {novel_id}",
            )
        return WritingDraftResponse.model_validate(draft)

    async def get_version_history(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> VersionHistoryResponse:
        """获取章节版本历史"""
        nid = parse_uuid(novel_id, "novel")
        versions = await self._repo.get_version_history(db, nid, chapter_index)
        items = [DraftListItem.model_validate(v) for v in versions]
        return VersionHistoryResponse(
            novel_id=novel_id,
            chapter_index=chapter_index,
            versions=items,
            total=len(items),
        )

    async def get_draft_contract(
        self,
        db: AsyncSession,
        draft_id: str,
    ) -> WritingDraftContract | None:
        """获取草稿契约（供其他模块使用，不存在返回 None）"""
        did = parse_uuid(draft_id, "draft")
        draft = await self._repo.get(db, did)
        if draft is None:
            return None
        return WritingDraftContract(
            novel_id=str(draft.novel_id),
            chapter_index=draft.chapter_index,
            chapter_card_id=str(draft.chapter_card_id) if draft.chapter_card_id else None,
            title=draft.title,
            content=draft.content,
            version_number=draft.version_number,
            status=draft.status,
        )

    async def get_latest_draft_contract(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> WritingDraftContract | None:
        """获取章节最新草稿契约（供其他模块使用，不存在返回 None）"""
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get_latest_by_chapter(db, nid, chapter_index)
        if draft is None:
            return None
        return WritingDraftContract(
            novel_id=str(draft.novel_id),
            chapter_index=draft.chapter_index,
            chapter_card_id=str(draft.chapter_card_id) if draft.chapter_card_id else None,
            title=draft.title,
            content=draft.content,
            version_number=draft.version_number,
            status=draft.status,
        )

    # ============================================================
    # 内部工具
    # ============================================================

