"""
Writing API 路由

提供正文草稿的 CRUD REST API 和章节草稿查询。
"""

from __future__ import annotations

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel

from core.dependencies import DbSession
from modules.writing.facade import create_draft as facade_create_draft
from modules.writing.schemas import (
    VersionHistoryResponse,
    WritingDraftCreate,
    WritingDraftResponse,
    WritingDraftUpdate,
)
from modules.writing.services import WritingDraftService


class ChapterIndicesResponse(BaseModel):
    """章节索引列表响应"""
    chapter_indices: list[int]


class PublishResponse(BaseModel):
    """发布响应 — draft + 异步 task_id"""
    draft: WritingDraftResponse
    task_id: str | None = None


class DeleteChapterResponse(BaseModel):
    """整章删除响应"""
    chapter_index: int
    deleted_versions: int


router = APIRouter(prefix="/api/writing", tags=["writing"])
_service = WritingDraftService()


@router.post("/drafts", response_model=PublishResponse, status_code=201)
async def create_draft(
    db: DbSession,
    data: WritingDraftCreate,
) -> PublishResponse:
    """发布草稿 — 创建新版本 + 入队 RAG 索引 + memory 快照"""
    result, task_id = await facade_create_draft(
        db,
        novel_id=data.novel_id,
        chapter_index=data.chapter_index,
        title=data.title,
        content=data.content or "",
    )
    await db.flush()
    return PublishResponse(draft=result, task_id=task_id)


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
    """暂存草稿 — 原地更新最新版本内容，不创建新版本，无副作用"""
    return await _service.update_draft(db, draft_id, data, novel_id)


@router.delete("/drafts/{draft_id}", status_code=204)
async def delete_draft(
    db: DbSession,
    draft_id: str = Path(..., description="草稿 ID"),
    novel_id: str = Query(..., description="小说项目 ID"),
) -> None:
    """删除单个版本（至少保留 1 个版本）"""
    await _service.delete_draft(db, draft_id, novel_id)


@router.delete("/chapters/{chapter_index}", response_model=DeleteChapterResponse)
async def delete_chapter(
    db: DbSession,
    chapter_index: int = Path(..., ge=1, description="章节索引"),
    novel_id: str = Query(..., description="小说项目 ID"),
) -> DeleteChapterResponse:
    """删除整章所有版本"""
    count = await _service.delete_chapter(db, novel_id, chapter_index)
    return DeleteChapterResponse(
        chapter_index=chapter_index,
        deleted_versions=count,
    )


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
