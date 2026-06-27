"""
Writing API 路由

提供正文草稿的 CRUD REST API 和章节草稿查询。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, Field

from core.dependencies import DbSession
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


router = APIRouter(prefix="/api/writing", tags=["writing"])
_service = WritingDraftService()


async def _trigger_rag_index(db: DbSession, novel_id: str, chapter_index: int) -> None:
    """提交 RAG 章节索引任务（后台异步，不阻塞响应）"""
    from infrastructure.tasks.models import AsyncTask

    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_index_chapter",
        status="pending",
        meta={"novel_id": novel_id, "chapter_index": chapter_index},
        progress=0.0,
    )
    db.add(task)


@router.post("/drafts", response_model=WritingDraftResponse, status_code=201)
async def create_draft(
    db: DbSession,
    data: WritingDraftCreate,
) -> WritingDraftResponse:
    """创建/保存草稿

    每次创建自动递增版本号。
    相同 novel_id + chapter_index 的新 POST 会创建新版本。
    保存后自动触发 RAG 章节索引。
    """
    result = await _service.create_draft(db, data)
    await _trigger_rag_index(db, data.novel_id, data.chapter_index)
    await db.flush()
    return result


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
    result = await _service.update_draft(db, draft_id, data, novel_id)
    if data.content is not None:
        await _trigger_rag_index(db, novel_id, result.chapter_index)
        await db.flush()
    return result


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


class SaveAndAnalyzeRequest(BaseModel):
    novel_id: str = Field(..., description="小说项目 ID")
    chapter_index: int = Field(..., ge=1, description="章节索引")
    content: str = Field(..., min_length=1, description="章节正文内容")


class SaveAndAnalyzeResponse(BaseModel):
    draft_id: str
    proposal_created: bool = False
    analysis_status: str = "success"


@router.post("/save-and-analyze", response_model=SaveAndAnalyzeResponse)
async def save_and_analyze(
    db: DbSession,
    data: SaveAndAnalyzeRequest,
) -> SaveAndAnalyzeResponse:
    import logging

    logger = logging.getLogger(__name__)

    draft_data = WritingDraftCreate(
        novel_id=data.novel_id,
        chapter_index=data.chapter_index,
        content=data.content,
    )
    draft = await _service.create_draft(db, draft_data)
    await _trigger_rag_index(db, data.novel_id, data.chapter_index)
    await db.flush()

    proposal_created = False
    analysis_status = "success"
    try:
        from modules.writing.services import WritingAnalysisService

        analysis_service = WritingAnalysisService()
        proposal_created, analysis_status = await analysis_service.analyze_chapter(
            db,
            data.novel_id,
            data.chapter_index,
            data.content,
        )
    except Exception as e:
        logger.error("地缘资产AI提取非致命性失败，已安全降级。详情: %s", str(e))
        proposal_created = False
        analysis_status = "failed"

    return SaveAndAnalyzeResponse(
        draft_id=str(draft.id),
        proposal_created=proposal_created,
        analysis_status=analysis_status,
    )
