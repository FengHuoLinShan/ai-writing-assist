"""
Writing 业务逻辑层

调用 repository 完成业务操作。
"""
from __future__ import annotations

import logging

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

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
        """创建新草稿版本（发布）"""
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
        """暂存草稿（原地更新最新版本，不创建新版本）"""
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )
        # 多 Tab 冲突检测
        if (
            data.expected_version is not None
            and draft.version_number != data.expected_version
        ):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    f"该章节已被其他会话更新（当前版本 v{draft.version_number}，"
                    f"期望版本 v{data.expected_version}）。请刷新后重新编辑。"
                ),
            )
        updated = await self._repo.update(db, did, data)
        if updated is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )
        return WritingDraftResponse.model_validate(updated)

    async def delete_draft(
        self,
        db: AsyncSession,
        draft_id: str,
        novel_id: str,
    ) -> None:
        """删除单个版本（至少保留 1 个版本），并自动重排后续版本号"""
        did = parse_uuid(draft_id, "draft")
        nid = parse_uuid(novel_id, "novel")
        draft = await self._repo.get(db, did)
        if draft is None or str(draft.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )

        # 业务规则：至少保留 1 个版本
        version_count = await self._repo.count_versions(
            db, draft.novel_id, draft.chapter_index,
        )
        if version_count <= 1:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last version of a chapter",
            )

        deleted = await self._repo.delete(db, did)
        if deleted is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Draft {draft_id} not found",
            )

        # 数据完整性：重排后续版本号
        await self._repo.renumber_versions_after_delete(
            db, draft.novel_id, draft.chapter_index, draft.version_number,
        )

    async def delete_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> int:
        """删除整章所有版本。返回删除的版本数。"""
        nid = parse_uuid(novel_id, "novel")
        return await self._repo.delete_all_versions(db, nid, chapter_index)

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
        return self._to_contract(draft)

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
        return self._to_contract(draft)

    @staticmethod
    def _to_contract(draft: object) -> WritingDraftContract:
        """将 ORM draft 转为契约对象"""
        return WritingDraftContract(
            novel_id=str(draft.novel_id),  # type: ignore[union-attr]
            chapter_index=draft.chapter_index,  # type: ignore[union-attr]
            title=draft.title,  # type: ignore[union-attr]
            content=draft.content,  # type: ignore[union-attr]
            version_number=draft.version_number,  # type: ignore[union-attr]
        )

    async def list_chapter_indices(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[int]:
        """列出该小说所有有草稿的章节索引"""
        nid = parse_uuid(novel_id, "novel")
        return await self._repo.list_chapter_indices(db, nid)
