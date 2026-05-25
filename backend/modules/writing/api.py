"""
Writing API 路由

提供正文草稿的 CRUD REST API 和章节草稿查询。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from fastapi import APIRouter, Path, Query

from core.dependencies import DbSession
from pydantic import BaseModel

from modules.writing.schemas import (
    VersionHistoryResponse,
    WritingDraftCreate,
    WritingDraftResponse,
    WritingDraftUpdate,
)


class ChapterIndicesResponse(BaseModel):
    """章节索引列表响应"""
    chapter_indices: list[int]
from modules.writing.services import WritingDraftService

router = APIRouter(prefix="/api/writing", tags=["writing"])
_service = WritingDraftService()


@router.post("/drafts", response_model=WritingDraftResponse, status_code=201)
async def create_draft(
    db: DbSession,
    data: WritingDraftCreate,
) -> WritingDraftResponse:
    """创建/保存草稿

    每次创建自动递增版本号。
    相同 novel_id + chapter_index 的新 POST 会创建新版本。
    """
    return await _service.create_draft(db, data)


@router.get("/drafts/{draft_id}", response_model=WritingDraftResponse)
async def get_draft(
    db: DbSession,
    draft_id: str = Path(..., description="草稿 ID"),
    novel_id: str = Query(..., description="小说项目 ID"),
) -> WritingDraftResponse:
    """获取指定草稿"""
    return await _service.get_draft(db, draft_id, novel_id)


@router.put("/drafts/{draft_id}", response_model=WritingDraftResponse)
async def update_draft(
    db: DbSession,
    draft_id: str = Path(..., description="草稿 ID"),
    data: WritingDraftUpdate = ...,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> WritingDraftResponse:
    """更新草稿内容或状态"""
    return await _service.update_draft(db, draft_id, data, novel_id)


@router.delete("/drafts/{draft_id}", status_code=204)
async def delete_draft(
    db: DbSession,
    draft_id: str = Path(..., description="草稿 ID"),
    novel_id: str = Query(..., description="小说项目 ID"),
) -> None:
    """删除草稿"""
    await _service.delete_draft(db, draft_id, novel_id)


@router.get(
    "/chapters/{chapter_index}/draft",
    response_model=WritingDraftResponse,
)
async def get_latest_chapter_draft(
    db: DbSession,
    chapter_index: int = Path(..., ge=1, description="章节索引"),
    novel_id: str = Query(..., description="小说项目 ID"),
) -> WritingDraftResponse:
    """获取指定章节的最新草稿"""
    return await _service.get_latest_draft(db, novel_id, chapter_index)


@router.get(
    "/chapters/{chapter_index}/versions",
    response_model=VersionHistoryResponse,
)
async def get_chapter_version_history(
    db: DbSession,
    chapter_index: int = Path(..., ge=1, description="章节索引"),
    novel_id: str = Query(..., description="小说项目 ID"),
) -> VersionHistoryResponse:
    """获取指定章节的版本历史"""
    return await _service.get_version_history(db, novel_id, chapter_index)


@router.get(
    "/chapters",
    response_model=ChapterIndicesResponse,
)
async def list_chapters(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> ChapterIndicesResponse:
    """列出该小说所有有草稿的章节索引（去重、升序）"""
    indices = await _service.list_chapter_indices(db, novel_id)
    return ChapterIndicesResponse(chapter_indices=indices)
