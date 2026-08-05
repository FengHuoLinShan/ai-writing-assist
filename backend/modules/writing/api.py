"""
Writing API 路由

提供正文草稿的 CRUD REST API 和章节草稿查询。
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, Field

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.tasks.enqueuer import enqueue_task
from modules.context.facade import (
    bind_confirmed_action_result,
    prepare_confirmed_ai_action,
)
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.writing.facade import (
    create_draft_only as _create_draft_only,
)
from modules.writing.schemas import (
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
    WritingDraftCheckpoint,
    WritingDraftResponse,
    WritingDraftUpdate,
    WritingGenerateRequest,
    WritingGenerateResponse,
    WritingPublishRequest,
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
    new_version: bool = True


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
    await require_active_project(db, data.novel_id)
    return await _conflict_service.create_check(db, data)


@router.get(
    "/conflict-checks",
    response_model=WritingConflictCheckListResponse,
)
async def list_conflict_checks(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    chapter_index: int = Query(..., ge=1, description="章节索引"),
    scene_id: str | None = Query(None, description="Scene ID"),
    limit: int = Query(10, ge=1, le=50, description="返回条数"),
) -> WritingConflictCheckListResponse:
    """获取章节/Scene 的冲突检查历史，最近记录优先。"""
    await require_active_project(db, novel_id)
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
    *,
    novel_id: NovelIdQuery,
) -> WritingConflictCheckResponse:
    """获取单次冲突检查详情。"""
    await require_active_project(db, novel_id)
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
    await require_active_project(db, data.novel_id)
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
    await require_active_project(db, data.novel_id)
    check = await _conflict_service.start_ai_review_task(
        db,
        check_id=check_id,
        data=data,
    )
    llm_execution_snapshot = await build_project_llm_execution_snapshot(
        db,
        data.novel_id,
    )
    task_id = enqueue_task(
        db,
        "writing_conflict_ai_review",
        meta={
            "novel_id": data.novel_id,
            "check_id": check_id,
            "context_confirmation_id": data.context_confirmation_id,
            "llm_execution_snapshot": llm_execution_snapshot,
        },
        novel_id=data.novel_id,
    )
    await _conflict_service.bind_ai_review_task_owner(
        db,
        novel_id=data.novel_id,
        check_id=check_id,
        task_id=task_id,
    )
    await bind_confirmed_action_result(
        db,
        novel_id=data.novel_id,
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
    *,
    novel_id: NovelIdQuery,
) -> WritingConflictItemResponse:
    """更新单条问题处理状态。"""
    await require_active_project(db, novel_id)
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
    await require_active_project(db, data.novel_id)
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
    """创建纯草稿版本；不发布，但会合并标脏 working 索引。"""
    await require_active_project(db, data.novel_id)
    draft = await _create_draft_only(
        db,
        novel_id=data.novel_id,
        chapter_index=data.chapter_index,
        title=data.title,
        content=data.content or "",
    )
    from modules.rag.facade import request_chapter_index

    await request_chapter_index(
        db,
        data.novel_id,
        data.chapter_index,
        content_mode="working",
    )
    return WritingDraftResponse.model_validate(asdict(draft))


@router.post(
    "/generate",
    response_model=WritingGenerateResponse,
    status_code=201,
)
async def generate_writing_candidate(
    db: DbSession,
    data: WritingGenerateRequest,
) -> WritingGenerateResponse:
    """提交 AI 正文建议生成任务；采用前不进入工作稿。"""
    await require_active_project(db, data.novel_id)
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

    llm_execution_snapshot = await build_project_llm_execution_snapshot(
        db,
        data.novel_id,
    )
    task_id = enqueue_task(
        db,
        "writing_generate",
        meta={
            "novel_id": data.novel_id,
            "chapter_index": data.chapter_index,
            "title": data.title,
            "instruction": data.instruction,
            "context_confirmation_id": data.context_confirmation_id,
            "generation_mode": data.generation_mode,
            "base_draft_id": data.base_draft_id,
            "llm_execution_snapshot": llm_execution_snapshot,
        },
        novel_id=data.novel_id,
    )
    await bind_confirmed_action_result(
        db,
        novel_id=data.novel_id,
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
    data: WritingPublishRequest,
) -> PublishResponse:
    """发布当前工作版本；无实质变化时复用已发布版本。"""
    await require_active_project(db, data.novel_id)
    snapshot = None
    try:
        snapshot = await _conflict_service.latest_snapshot(
            db,
            novel_id=data.novel_id,
            chapter_index=data.chapter_index,
            scene_id=data.scene_id,
        )
    except Exception as exc:
        logger.warning(
            "writing conflict snapshot lookup failed: %s",
            redact_diagnostic(exc, limit=500),
        )
    result, published_new_version = await _service.publish_draft_result(db, data)
    if published_new_version:
        result.conflict_check_snapshot_json = snapshot
    if snapshot and published_new_version:
        try:
            await _service.set_conflict_check_snapshot(
                db,
                result.id,
                data.novel_id,
                snapshot,
            )
        except Exception as exc:
            logger.warning(
                "writing conflict snapshot archive failed: %s",
                redact_diagnostic(exc, limit=500),
            )
    from modules.rag.facade import mark_chapter_index_dirty

    task_id = None
    if published_new_version:
        await mark_chapter_index_dirty(
            db,
            data.novel_id,
            data.chapter_index,
            content_mode="canonical",
        )
        task_id = enqueue_task(
            db,
            "publish_chapter",
            meta={
                "novel_id": data.novel_id,
                "chapter_index": data.chapter_index,
            },
            novel_id=data.novel_id,
        )
    await db.flush()
    return PublishResponse(
        draft=result,
        task_id=task_id,
        new_version=published_new_version,
    )


@router.get("/drafts/{draft_id}", response_model=WritingDraftResponse)
async def get_draft(
    db: DbSession,
    draft_id: str = Path(..., description="草稿 ID"),
    *,
    novel_id: NovelIdQuery,
) -> WritingDraftResponse:
    """获取指定草稿"""
    await require_active_project(db, novel_id)
    return await _service.get_draft(db, draft_id, novel_id)


@router.post("/drafts/{draft_id}/adopt", response_model=WritingDraftResponse)
async def adopt_candidate_to_working(
    db: DbSession,
    draft_id: str = Path(..., description="AI 正文建议 ID"),
    *,
    novel_id: NovelIdQuery,
) -> WritingDraftResponse:
    """将 AI 正文建议显式采用到普通工作稿。"""
    await require_active_project(db, novel_id)
    from modules.rag.facade import request_chapter_index

    result = await _service.adopt_candidate_to_working(
        db,
        draft_id,
        novel_id,
        adopted_by="author",
    )
    await request_chapter_index(
        db,
        novel_id,
        result.chapter_index,
        content_mode="working",
    )
    return result


@router.put("/drafts/{draft_id}", response_model=WritingDraftResponse)
async def update_draft(
    db: DbSession,
    draft_id: str = Path(..., description="草稿 ID"),
    data: WritingDraftUpdate = ...,
    *,
    novel_id: NovelIdQuery,
) -> WritingDraftResponse:
    """暂存草稿；published 会 copy-on-write，并合并请求 working 索引。"""
    await require_active_project(db, novel_id)
    from modules.rag.facade import request_chapter_index

    result = await _service.update_draft(db, draft_id, data, novel_id)
    await request_chapter_index(
        db,
        novel_id,
        result.chapter_index,
        content_mode="working",
    )
    return result


@router.post(
    "/drafts/{draft_id}/checkpoint",
    response_model=WritingDraftResponse,
)
async def checkpoint_draft(
    db: DbSession,
    data: WritingDraftCheckpoint,
    draft_id: str = Path(..., description="当前草稿 ID"),
    *,
    novel_id: NovelIdQuery,
) -> WritingDraftResponse:
    """显式保存一个未发布版本。"""
    await require_active_project(db, novel_id)
    from modules.rag.facade import request_chapter_index

    result = await _service.checkpoint_draft(db, draft_id, data, novel_id)
    await request_chapter_index(
        db,
        novel_id,
        result.chapter_index,
        content_mode="working",
    )
    return result


@router.post(
    "/drafts/{draft_id}/discard",
    response_model=WritingDraftResponse,
)
async def discard_draft(
    db: DbSession,
    draft_id: str = Path(..., description="当前未发布草稿 ID"),
    *,
    novel_id: NovelIdQuery,
    expected_version: int | None = Query(None, ge=1),
    expected_updated_at: datetime | None = Query(None),
) -> WritingDraftResponse:
    """放弃当前未发布版本并返回其基线。"""
    await require_active_project(db, novel_id)
    from modules.rag.facade import request_chapter_index

    result = await _service.discard_draft(
        db,
        draft_id,
        novel_id,
        expected_version=expected_version,
        expected_updated_at=expected_updated_at,
    )
    await request_chapter_index(
        db,
        novel_id,
        result.chapter_index,
        content_mode="working",
    )
    return result


@router.delete("/drafts/{draft_id}", status_code=204)
async def delete_draft(
    db: DbSession,
    draft_id: str = Path(..., description="草稿 ID"),
    *,
    novel_id: NovelIdQuery,
) -> None:
    """删除单个版本（至少保留 1 个版本）"""
    await require_active_project(db, novel_id)
    from modules.rag.facade import request_chapter_index

    draft = await _service.get_draft(db, draft_id, novel_id)
    await _service.delete_draft(db, draft_id, novel_id)
    for content_mode in ("canonical", "working"):
        await request_chapter_index(
            db,
            novel_id,
            draft.chapter_index,
            content_mode=content_mode,
        )


@router.delete("/chapters/{chapter_index}", response_model=DeleteChapterResponse)
async def delete_chapter(
    db: DbSession,
    chapter_index: int = Path(..., ge=1, description="章节索引"),
    *,
    novel_id: NovelIdQuery,
) -> DeleteChapterResponse:
    """软废弃整章所有版本。"""
    await require_active_project(db, novel_id)
    from modules.rag.facade import request_chapter_index

    count = await _service.delete_chapter(db, novel_id, chapter_index)
    for content_mode in ("canonical", "working"):
        await request_chapter_index(
            db,
            novel_id,
            chapter_index,
            content_mode=content_mode,
        )
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
    *,
    novel_id: NovelIdQuery,
) -> WritingDraftResponse:
    """获取指定章节的最新草稿"""
    await require_active_project(db, novel_id)
    return await _service.get_latest_draft(db, novel_id, chapter_index)


@router.get(
    "/chapters/{chapter_index}/versions",
    response_model=VersionHistoryResponse,
)
async def get_chapter_version_history(
    db: DbSession,
    chapter_index: int = Path(..., ge=1, description="章节索引"),
    *,
    novel_id: NovelIdQuery,
) -> VersionHistoryResponse:
    """获取指定章节的版本历史"""
    await require_active_project(db, novel_id)
    return await _service.get_version_history(db, novel_id, chapter_index)


@router.get(
    "/chapters",
    response_model=ChapterIndicesResponse,
)
async def list_chapters(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> ChapterIndicesResponse:
    """列出该小说所有有草稿的章节索引（去重、升序）"""
    await require_active_project(db, novel_id)
    chapters = await _service.list_chapter_summaries(db, novel_id)
    return ChapterIndicesResponse(
        chapter_indices=[item.chapter_index for item in chapters],
        chapters=chapters,
    )
