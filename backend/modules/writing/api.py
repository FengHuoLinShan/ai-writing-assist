"""
Writing API 路由

提供正文草稿的 CRUD REST API 和章节草稿查询。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, Field

from core.dependencies import DbSession
from infrastructure.tasks.enqueuer import enqueue_task
from modules.context.facade import (
    bind_confirmed_action_result,
    prepare_confirmed_ai_action,
)
from modules.writing.facade import (
    create_draft_only as _create_draft_only,
)
from modules.writing.schemas import (
    ChapterSplitRequest,
    ChapterSplitResponse,
    ChapterSummaryItem,
    VersionHistoryResponse,
    WritingConflictAiReviewRequest,
    WritingConflictAiReviewTaskResponse,
    WritingConflictAiSuggestionRequest,
    WritingConflictCheckCreate,
    WritingConflictCheckListResponse,
    WritingConflictCheckResponse,
    WritingConflictItemResponse,
    WritingConflictItemUpdate,
    WritingDraftAutosaveCreate,
    WritingDraftCreate,
    WritingDraftResponse,
    WritingDraftUpdate,
    WritingGenerateRequest,
    WritingGenerateResponse,
)
from modules.writing.services import WritingConflictCheckService, WritingDraftService


class ChapterIndicesResponse(BaseModel):
    """章节索引列表响应"""

    chapter_indices: list[int]
    chapters: list[ChapterSummaryItem] = Field(default_factory=list)


class PublishResponse(BaseModel):
    """发布响应 — draft + 异步 task_id"""

    draft: WritingDraftResponse
    task_id: str | None = None


class DeleteChapterResponse(BaseModel):
    """整章删除响应"""

    chapter_index: int
    deleted_versions: int


router = APIRouter(prefix="/api/writing", tags=["writing"])
logger = logging.getLogger(__name__)
_service = WritingDraftService()
_conflict_service = WritingConflictCheckService()


@router.post(
    "/conflict-checks",
    response_model=WritingConflictCheckResponse,
    status_code=201,
)
async def create_conflict_check(
    db: DbSession,
    data: WritingConflictCheckCreate,
) -> WritingConflictCheckResponse:
    """创建一次 Scene 写作冲突检查。"""
    return await _conflict_service.create_check(db, data)


@router.get(
    "/conflict-checks",
    response_model=WritingConflictCheckListResponse,
)
async def list_conflict_checks(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
    chapter_index: int = Query(..., ge=1, description="章节索引"),
    scene_id: str | None = Query(None, description="Scene ID"),
    limit: int = Query(10, ge=1, le=50, description="返回条数"),
) -> WritingConflictCheckListResponse:
    """获取章节/Scene 的冲突检查历史，最近记录优先。"""
    return await _conflict_service.list_checks(
        db,
        novel_id=novel_id,
        chapter_index=chapter_index,
        scene_id=scene_id,
        limit=limit,
    )


@router.get(
    "/conflict-checks/{check_id}",
    response_model=WritingConflictCheckResponse,
)
async def get_conflict_check(
    db: DbSession,
    check_id: str = Path(..., description="检查记录 ID"),
    novel_id: str = Query(..., description="小说项目 ID"),
) -> WritingConflictCheckResponse:
    """获取单次冲突检查详情。"""
    return await _conflict_service.get_check(
        db,
        novel_id=novel_id,
        check_id=check_id,
    )


@router.post(
    "/conflict-checks/{check_id}/ai-review",
    response_model=WritingConflictCheckResponse,
)
async def run_conflict_check_ai_review(
    db: DbSession,
    data: WritingConflictAiReviewRequest,
    check_id: str = Path(..., description="检查记录 ID"),
) -> WritingConflictCheckResponse:
    """为一次冲突检查追加 AI 软冲突判断。"""
    return await _conflict_service.run_ai_review(
        db,
        check_id=check_id,
        data=data,
    )


@router.post(
    "/conflict-checks/{check_id}/ai-review-task",
    response_model=WritingConflictAiReviewTaskResponse,
    status_code=202,
)
async def enqueue_conflict_check_ai_review(
    db: DbSession,
    data: WritingConflictAiReviewRequest,
    check_id: str = Path(..., description="检查记录 ID"),
) -> WritingConflictAiReviewTaskResponse:
    """提交 AI 软冲突判断任务，避免前端等待真实 LLM 调用超时。"""
    check = await _conflict_service.start_ai_review_task(
        db,
        check_id=check_id,
        data=data,
    )
    task_id = enqueue_task(
        db,
        "writing_conflict_ai_review",
        meta={
            "novel_id": data.novel_id,
            "check_id": check_id,
            "context_confirmation_id": data.context_confirmation_id,
        },
    )
    await bind_confirmed_action_result(
        db,
        confirmation_id=data.context_confirmation_id,
        result_type="task",
        result_id=task_id,
        status="running",
    )
    await db.flush()
    return WritingConflictAiReviewTaskResponse(
        task_id=task_id,
        status="pending",
        check=check,
    )


@router.patch(
    "/conflict-check-items/{item_id}",
    response_model=WritingConflictItemResponse,
)
async def update_conflict_item(
    db: DbSession,
    data: WritingConflictItemUpdate,
    item_id: str = Path(..., description="问题项 ID"),
    novel_id: str = Query(..., description="小说项目 ID"),
) -> WritingConflictItemResponse:
    """更新单条问题处理状态。"""
    return await _conflict_service.update_item(
        db,
        novel_id=novel_id,
        item_id=item_id,
        data=data,
    )


@router.post(
    "/conflict-check-items/{item_id}/ai-suggestion",
    response_model=WritingConflictItemResponse,
)
async def create_conflict_item_ai_suggestion(
    db: DbSession,
    data: WritingConflictAiSuggestionRequest,
    item_id: str = Path(..., description="问题项 ID"),
) -> WritingConflictItemResponse:
    """为单条冲突问题生成 AI 修复建议。"""
    return await _conflict_service.generate_ai_suggestion(
        db,
        item_id=item_id,
        data=data,
    )


@router.post(
    "/drafts/autosave",
    response_model=WritingDraftResponse,
    status_code=201,
)
async def create_autosaved_draft(
    db: DbSession,
    data: WritingDraftAutosaveCreate,
) -> WritingDraftResponse:
    """创建纯草稿版本，不触发发布/RAG 任务。"""
    return await _create_draft_only(
        db,
        novel_id=data.novel_id,
        chapter_index=data.chapter_index,
        title=data.title,
        content=data.content or "",
    )


@router.post(
    "/generate",
    response_model=WritingGenerateResponse,
    status_code=201,
)
async def generate_writing_candidate(
    db: DbSession,
    data: WritingGenerateRequest,
) -> WritingGenerateResponse:
    """提交 AI 正文候选草稿生成任务。"""
    try:
        await prepare_confirmed_ai_action(
            db,
            novel_id=data.novel_id,
            action="writing.generate",
            confirmation_id=data.context_confirmation_id,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc

    task_id = enqueue_task(
        db,
        "writing_generate",
        meta={
            "novel_id": data.novel_id,
            "chapter_index": data.chapter_index,
            "title": data.title,
            "instruction": data.instruction,
            "context_confirmation_id": data.context_confirmation_id,
        },
    )
    await bind_confirmed_action_result(
        db,
        confirmation_id=data.context_confirmation_id,
        result_type="task",
        result_id=task_id,
        status="running",
    )
    await db.flush()
    return WritingGenerateResponse(task_id=task_id, status="pending")


@router.post("/drafts", response_model=PublishResponse, status_code=201)
async def create_draft(
    db: DbSession,
    data: WritingDraftCreate,
) -> PublishResponse:
    """发布草稿 — 创建新版本 + 入队发布任务"""
    snapshot = None
    try:
        snapshot = await _conflict_service.latest_snapshot(
            db,
            novel_id=data.novel_id,
            chapter_index=data.chapter_index,
            scene_id=data.scene_id,
        )
    except Exception as exc:
        logger.warning("writing conflict snapshot lookup failed: %s", exc)
    result = await _service.publish_draft(db, data)
    result.conflict_check_snapshot_json = snapshot
    if snapshot:
        try:
            await _service.set_conflict_check_snapshot(
                db,
                result.id,
                data.novel_id,
                snapshot,
            )
        except Exception as exc:
            logger.warning("writing conflict snapshot archive failed: %s", exc)
    task_id = enqueue_task(
        db,
        "publish_chapter",
        meta={
            "novel_id": data.novel_id,
            "chapter_index": data.chapter_index,
        },
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
    chapters = await _service.list_chapter_summaries(db, novel_id)
    return ChapterIndicesResponse(
        chapter_indices=[item.chapter_index for item in chapters],
        chapters=chapters,
    )


@router.post(
    "/chapters/{chapter_index}/split",
    response_model=ChapterSplitResponse,
)
async def split_chapter(
    db: DbSession,
    data: ChapterSplitRequest,
    chapter_index: int = Path(..., ge=1, description="章节索引"),
    novel_id: str = Query(..., description="小说项目 ID"),
) -> ChapterSplitResponse:
    return await _service.split_chapter_at_offset(
        db,
        novel_id=novel_id,
        chapter_index=chapter_index,
        split_pos=data.split_pos,
        source_scene_id=data.source_scene_id,
    )
