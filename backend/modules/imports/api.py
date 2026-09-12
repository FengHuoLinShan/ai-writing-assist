"""
Import API 路由

提供小说文件上传与导入的 REST API。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Literal

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, model_validator

from core.api_params import NovelIdForm, NovelIdQuery
from core.config import get_settings
from core.dependencies import DbSession
from core.errors import ConflictError, DomainError, NotFoundError
from core.errors import ValidationError as DomainValidationError
from infrastructure.llm.redaction import redact_diagnostic
from modules.imports.contracts import TaskNotFoundError
from modules.imports.parsers import MAX_FILE_SIZE
from modules.imports.review_resolution_schemas import (
    ReviewResolutionDecisionRequest,
    ReviewResolutionOptions,
    ReviewResolutionRequest,
    SceneResolutionDecisionRequest,
)
from modules.imports.schemas import (
    ImportListResponse,
    ImportResponse,
    TargetedCompletionOptions,
    TargetedCompletionRequest,
)
from modules.imports.services import ImportService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/imports", tags=["imports"])
_service = ImportService()
UPLOAD_READ_CHUNK_SIZE = 1024 * 1024


async def _require_active_project(db: DbSession, novel_id: str) -> None:
    from modules.project.facade import require_active_project

    await require_active_project(db, novel_id)


async def _require_active_project_exclusive(db: DbSession, novel_id: str) -> None:
    from modules.project.facade import require_active_project_exclusive

    await require_active_project_exclusive(db, novel_id)


async def _require_task_owner_active_project(
    db: DbSession,
    task_id: str,
) -> None:
    from infrastructure.tasks.facade import get_task_owner
    from modules.imports.contracts import TaskNotFoundError

    owner = await get_task_owner(db, task_id=task_id)
    if owner is None:
        raise TaskNotFoundError(task_id)
    try:
        await _require_active_project(db, owner.novel_id)
    except NotFoundError as exc:
        raise HTTPException(404, detail="Not found") from exc


class DeepImportRequest(BaseModel):
    """Deep Import request shared by async, staged, and sync entrypoints."""

    novel_id: str = Field(..., min_length=1)
    start_chapter: int = Field(default=1, ge=1)
    end_chapter: int = Field(default=0, ge=0)
    force: bool = False
    high_quality: bool = False
    review_resolution: ReviewResolutionOptions = Field(
        default_factory=ReviewResolutionOptions
    )
    targeted_completion: TargetedCompletionOptions = Field(
        default_factory=TargetedCompletionOptions
    )
    adoption_policy: Literal["user_authorized_pipeline"] = "user_authorized_pipeline"
    authorization_confirmed: bool = Field(
        ...,
        description="已理解并授权流水线按 adoption_policy 写入资产",
    )

    @model_validator(mode="after")
    def validate_chapter_range(self) -> DeepImportRequest:
        if self.end_chapter and self.end_chapter < self.start_chapter:
            raise ValueError("end_chapter must be >= start_chapter")
        if self.authorization_confirmed is not True:
            raise ValueError("authorization_confirmed must be true")
        return self


class DeepImportRecoveryRequest(BaseModel):
    """Resume/abandon payload; defaults preserve the existing 400 response."""

    stage: Literal["targeted_completion"] | None = None
    authorization_confirmed: bool = False
    task_id: str = Field(
        default="",
        description="待继续或放弃的深度导入任务 ID",
    )


class DeepImportCleanupSummaryResponse(BaseModel):
    """Workflow cleanup result with legacy aliases kept for wire compatibility."""

    deprecated_scenes: int = 0
    deprecated_entities: int = 0
    deprecated_structure_assets: int = 0
    hard_deleted_assets: int = 0
    cleanup_mode: Literal["soft_deprecate"] = "soft_deprecate"
    cleanup_status: Literal["complete", "partial"] = "complete"
    unreverted_targeted_items: int = 0
    targeted_completion_rollback: dict = Field(default_factory=dict)
    review_resolution_rollback: dict = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    unreverted_resolution_items: int = Field(
        default=0, exclude_if=lambda value: value == 0
    )
    rolled_back_delta_logs: int = 0
    rolled_back_aliases: int = 0
    rolled_back_relations: int = 0
    skipped_delta_logs: int = Field(
        0,
        description="兼容旧字段；已由 rolled_back_delta_logs 取代",
    )
    cleanup_todo: str | None = Field(
        None,
        description="兼容旧字段；当前清理已在放弃时完成",
    )


class DeepImportCleanupPreviewResponse(BaseModel):
    task_id: str
    workflow_id: str
    status: Literal["cancelled"]
    cleanup_eligible: bool
    cleanup_status: Literal["pending", "partial", "complete"]
    asset_summary: dict[str, int] = Field(default_factory=dict)
    cleanup_summary: DeepImportCleanupSummaryResponse | dict = Field(
        default_factory=dict
    )
    cleanup_fingerprint: str
    message: str


class DeepImportCleanupRequest(BaseModel):
    novel_id: str
    expected_cleanup_fingerprint: str = Field(min_length=64, max_length=64)
    confirmed: Literal[True]


class DeepImportCleanupResponse(BaseModel):
    task_id: str
    workflow_id: str
    status: Literal["cancelled"]
    cleanup_eligible: bool
    cleanup_status: Literal["partial", "complete"]
    cleanup_summary: DeepImportCleanupSummaryResponse
    cleanup_fingerprint: str
    message: str


class DeepImportAbandonResponse(BaseModel):
    workflow_id: str
    task_id: str
    status: Literal["cancelled"]
    cleanup_summary: DeepImportCleanupSummaryResponse
    message: str = "深度导入恢复已放弃"


async def _resolve_end_chapter(db: DbSession, request: DeepImportRequest) -> int:
    if request.end_chapter != 0:
        return request.end_chapter

    from modules.writing.facade import list_chapter_indices

    indices = await list_chapter_indices(db, request.novel_id)
    if not indices:
        raise HTTPException(
            400,
            detail="该项目暂无可导入的章节，请先上传小说文件或创建章节",
        )
    return max(indices)


def _validate_chapter_count_limit(start_chapter: int, end_chapter: int) -> None:
    total = end_chapter - start_chapter + 1
    max_chapters = get_settings().import_max_chapters
    if total > max_chapters:
        raise DomainValidationError(
            f"导入章节范围 {start_chapter}-{end_chapter} 共 {total} 章，"
            f"超过上限 {max_chapters}",
            status_code=400,
        )


async def _read_upload_file_in_chunks(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    file_size = 0

    while chunk := await file.read(UPLOAD_READ_CHUNK_SIZE):
        file_size += len(chunk)
        if file_size > MAX_FILE_SIZE:
            raise DomainValidationError(
                (
                    f"文件过大（{file_size} bytes），"
                    f"最大允许 {MAX_FILE_SIZE} bytes（50MB）"
                ),
                status_code=413,
            )
        chunks.append(chunk)

    return b"".join(chunks)


@router.post("/upload", response_model=ImportResponse, status_code=201)
async def upload_file(
    db: DbSession,
    *,
    novel_id: NovelIdForm,
    file: UploadFile = File(..., description="小说文件（txt/epub/html/mobi）"),
) -> ImportResponse:
    """上传小说文件并自动导入"""
    await _require_active_project(db, novel_id)
    content = await _read_upload_file_in_chunks(file)
    try:
        result = await _service.upload_and_import(
            db,
            novel_id,
            os.path.basename(file.filename or "unknown"),
            content,
        )
    except (DomainError, HTTPException):
        # service 已创建/更新 import_records 状态，需要提交才能持久化失败记录。
        # 但事务可能已被底层数据库错误污染，提交失败时不应抛新的 500，
        # 回滚后仍然抛出原始业务异常。
        try:
            await db.commit()
        except Exception as commit_exc:
            logger.warning(
                "导入异常后提交记录状态失败: %s",
                redact_diagnostic(commit_exc, limit=300),
            )
            try:
                await db.rollback()
            except Exception:
                pass
        raise
    return result


@router.get("", response_model=ImportListResponse)
async def list_imports(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> ImportListResponse:
    """获取导入记录列表"""
    await _require_active_project(db, novel_id)
    return await _service.list_import_records(db, novel_id, skip=skip, limit=limit)


@router.get("/{record_id}", response_model=ImportResponse)
async def get_import(
    db: DbSession,
    record_id: str,
    *,
    novel_id: NovelIdQuery,
) -> ImportResponse:
    """获取单条导入记录详情"""
    await _require_active_project(db, novel_id)
    return await _service.get_import_record(db, novel_id, record_id)


# ====================================================================
# 深度导入
# ====================================================================


@router.post("/deep", status_code=201)
async def submit_deep_import(
    db: DbSession,
    body: DeepImportRequest = Body(..., description="深度导入参数"),
) -> dict:
    """提交深度导入任务

    自动执行三阶段流水线：Scene 切分 → 实体增量提取 → 剧情结构分析。

    请求体：
    - novel_id: 项目 ID（必填）
    - start_chapter: 起始章节（默认 1）
    - end_chapter: 结束章节（必填）

    返回 task_id，前端可通过 GET /api/tasks/{task_id}?novel_id=... 查询状态。
    """
    from modules.imports.facade import start_deep_import as _start

    await _require_active_project_exclusive(db, body.novel_id)
    end_chapter = await _resolve_end_chapter(db, body)
    _validate_chapter_count_limit(body.start_chapter, end_chapter)
    result = await _start(
        db,
        body.novel_id,
        body.start_chapter,
        end_chapter,
        force=body.force,
        high_quality=body.high_quality,
        adoption_policy=body.adoption_policy,
        authorization_confirmed=body.authorization_confirmed,
        **(
            {"review_resolution": body.review_resolution.model_dump()}
            if body.review_resolution.enabled
            else {}
        ),
        **(
            {"targeted_completion": body.targeted_completion.model_dump()}
            if body.targeted_completion.enabled or body.targeted_completion.defer
            else {}
        ),
    )
    return result


async def _submit_stage(
    db: DbSession,
    body: DeepImportRequest,
    *,
    stage: str,
) -> dict:
    from modules.imports.facade import start_deep_import_stage as _start_stage

    if body.targeted_completion.enabled and stage != "world_objects":
        raise HTTPException(422, detail="专项补全仅用于完整导入或世界对象提取")
    await _require_active_project_exclusive(db, body.novel_id)
    end_chapter = await _resolve_end_chapter(db, body)
    _validate_chapter_count_limit(body.start_chapter, end_chapter)

    return await _start_stage(
        db,
        body.novel_id,
        body.start_chapter,
        end_chapter,
        stage=stage,
        force=body.force,
        high_quality=body.high_quality,
        adoption_policy=body.adoption_policy,
        authorization_confirmed=body.authorization_confirmed,
        **(
            {"review_resolution": body.review_resolution.model_dump()}
            if body.review_resolution.enabled
            else {}
        ),
        **(
            {"targeted_completion": body.targeted_completion.model_dump()}
            if stage == "world_objects"
            and (body.targeted_completion.enabled or body.targeted_completion.defer)
            else {}
        ),
    )


@router.post("/stages/scenes", status_code=201)
async def submit_scene_auto_extraction(
    db: DbSession,
    body: DeepImportRequest = Body(..., description="场景自动提取参数"),
) -> dict:
    """提交从正文提取 Scene 任务。"""
    return await _submit_stage(db, body, stage="scenes")


@router.post("/stages/world-objects", status_code=201)
async def submit_world_object_auto_extraction(
    db: DbSession,
    body: DeepImportRequest = Body(..., description="世界对象与别名/关系自动提取参数"),
) -> dict:
    """提交世界对象与别名/关系自动提取任务。"""
    return await _submit_stage(db, body, stage="world_objects")


@router.post("/stages/plot-structure", status_code=201)
async def submit_plot_structure_auto_extraction(
    db: DbSession,
    body: DeepImportRequest = Body(..., description="剧情线自动提取参数"),
) -> dict:
    """提交剧情线自动提取任务。"""
    return await _submit_stage(db, body, stage="plot_structure")


@router.post("/deep/resume", status_code=201)
async def resume_deep_import(
    db: DbSession,
    body: DeepImportRecoveryRequest = Body(..., description="继续深度导入参数"),
) -> dict:
    """恢复被中断的深度导入流程

    请求体：
    - task_id: 被中断的 deep_import 任务 ID（必填）
    """
    from modules.imports import facade as imports_facade

    task_id = body.task_id
    if not task_id:
        raise HTTPException(400, detail="task_id is required")

    from modules.imports.contracts import TaskNotFoundError

    try:
        await _require_task_owner_active_project(db, task_id)
        if body.stage and not body.authorization_confirmed:
            raise ValueError("请确认专项查漏范围与授权")
        result = await imports_facade.resume_deep_import(
            db, task_id, **({"stage": body.stage} if body.stage else {})
        )
    except TaskNotFoundError as exc:
        raise HTTPException(404, detail="Not found") from exc
    except ValueError as exc:
        raise HTTPException(400, detail=redact_diagnostic(exc)) from exc
    return result


@router.post("/deep/abandon", response_model=DeepImportAbandonResponse)
async def abandon_deep_import(
    db: DbSession,
    body: DeepImportRecoveryRequest = Body(..., description="放弃深度导入恢复参数"),
) -> DeepImportAbandonResponse:
    """放弃被中断的深度导入流程并返回清理摘要

    请求体：
    - task_id: 被中断的 deep_import 任务 ID（必填）
    """
    from modules.imports import facade as imports_facade

    task_id = body.task_id
    if not task_id:
        raise HTTPException(400, detail="task_id is required")

    from modules.imports.contracts import TaskNotFoundError

    try:
        await _require_task_owner_active_project(db, task_id)
        result = await imports_facade.abandon_deep_import(db, task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(404, detail="Not found") from exc
    except ValueError as exc:
        raise HTTPException(400, detail=redact_diagnostic(exc)) from exc
    return DeepImportAbandonResponse.model_validate(result)


@router.post("/targeted-completions", status_code=201)
async def submit_targeted_completion(
    db: DbSession, body: TargetedCompletionRequest
) -> dict:
    """查读指定对象及直接关联对象；只自动新增与填空，冲突保留待复核。"""
    from modules.imports.facade import start_targeted_completion

    await _require_active_project_exclusive(db, body.novel_id)
    end_chapter = await _resolve_end_chapter(db, body)
    _validate_chapter_count_limit(body.start_chapter, end_chapter)
    try:
        return await start_targeted_completion(
            db,
            novel_id=body.novel_id,
            targets=[target.model_dump(exclude_none=True) for target in body.targets],
            start_chapter=body.start_chapter,
            end_chapter=end_chapter,
            authorization_confirmed=body.authorization_confirmed,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=redact_diagnostic(exc)) from exc


class TargetedCompletionRollbackRequest(BaseModel):
    confirmed: Literal[True]


@router.post("/targeted-completions/{task_id}/rollback")
async def rollback_targeted_completion(
    db: DbSession,
    task_id: str,
    body: TargetedCompletionRollbackRequest,
    *,
    novel_id: NovelIdQuery,
) -> dict:
    from modules.imports.contracts import TaskNotFoundError
    from modules.imports.facade import rollback_targeted_completion as rollback

    await _require_active_project_exclusive(db, novel_id)
    try:
        return await rollback(db, novel_id=novel_id, task_id=task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(404, detail="Not found") from exc
    except ValueError as exc:
        raise HTTPException(409, detail=redact_diagnostic(exc)) from exc


@router.post("/targeted-completions/{task_id}/defer")
async def defer_completion(task_id: uuid.UUID, db: DbSession) -> dict:
    from modules.imports.completion_control import request_completion_defer
    from modules.imports.contracts import TaskNotFoundError

    try:
        await _require_task_owner_active_project(db, str(task_id))
        return await request_completion_defer(db, task_id=str(task_id))
    except TaskNotFoundError as exc:
        raise HTTPException(404, detail="Not found") from exc
    except ValueError as exc:
        raise HTTPException(409, detail=redact_diagnostic(exc)) from exc


@router.get("/workflows/recent")
async def recent_workflows(
    novel_id: str,
    db: DbSession,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    from modules.imports.completion_control import list_recent_workflows
    from modules.project.facade import require_active_project

    await require_active_project(db, novel_id)
    return await list_recent_workflows(db, novel_id=novel_id, skip=skip, limit=limit)


@router.get(
    "/workflows/{task_id}/cleanup-preview",
    response_model=DeepImportCleanupPreviewResponse,
)
async def preview_cancelled_workflow_cleanup(
    task_id: str,
    *,
    novel_id: NovelIdQuery,
    db: DbSession,
) -> DeepImportCleanupPreviewResponse:
    from modules.imports.facade import preview_cancelled_import_cleanup
    from modules.project.facade import require_active_project

    await require_active_project(db, novel_id)
    try:
        result = await preview_cancelled_import_cleanup(
            db,
            novel_id=novel_id,
            task_id=task_id,
        )
    except TaskNotFoundError as exc:
        raise HTTPException(404, detail="Not found") from exc
    except (ConflictError, ValueError) as exc:
        raise HTTPException(409, detail=redact_diagnostic(exc)) from exc
    return DeepImportCleanupPreviewResponse.model_validate(result)


@router.post(
    "/workflows/{task_id}/cleanup",
    response_model=DeepImportCleanupResponse,
)
async def cleanup_cancelled_workflow(
    task_id: str,
    body: DeepImportCleanupRequest,
    db: DbSession,
) -> DeepImportCleanupResponse:
    from modules.imports.facade import cleanup_cancelled_import

    await _require_active_project_exclusive(db, body.novel_id)
    try:
        result = await cleanup_cancelled_import(
            db,
            novel_id=body.novel_id,
            task_id=task_id,
            expected_fingerprint=body.expected_cleanup_fingerprint,
        )
    except TaskNotFoundError as exc:
        raise HTTPException(404, detail="Not found") from exc
    except (ConflictError, ValueError) as exc:
        raise HTTPException(409, detail=redact_diagnostic(exc)) from exc
    return DeepImportCleanupResponse.model_validate(result)


@router.get("/workflows/impact")
async def workflow_asset_impact(
    novel_id: str, asset_id: uuid.UUID, db: DbSession
) -> dict:
    from modules.imports.completion_control import active_asset_impact
    from modules.project.facade import require_active_project

    await require_active_project(db, novel_id)
    return await active_asset_impact(db, novel_id=novel_id, asset_id=str(asset_id))


@router.get("/review-summary")
async def get_review_summary(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    start_chapter: int = Query(1, ge=1),
    end_chapter: int = Query(0, ge=0),
) -> dict:
    from modules.imports.facade import get_review_summary as read

    await _require_active_project(db, novel_id)
    result = await read(
        db, novel_id, start_chapter=start_chapter, end_chapter=end_chapter
    )
    from modules.imports.review_resolution import latest_resolution

    public = {
        key: value for key, value in result.items() if key not in {"candidates", "scenes"}
    }
    from modules.imports.facade import get_review_dispositions

    dispositions = await get_review_dispositions(db, novel_id)
    public["unclassified"] = sum(
        key not in dispositions["outcomes"] for key in result["candidate_keys"]
    )
    public["total_candidates"] = len(result["candidate_keys"])
    public["latest"] = await latest_resolution(db, novel_id)
    return public


@router.post("/review-resolutions", status_code=201)
async def submit_review_resolution(db: DbSession, body: ReviewResolutionRequest) -> dict:
    from modules.imports.facade import start_review_resolution

    await _require_active_project_exclusive(db, body.novel_id)
    end = await _resolve_end_chapter(db, body)
    _validate_chapter_count_limit(body.start_chapter, end)
    return await start_review_resolution(db, body.model_copy(update={"end_chapter": end}))


@router.post("/review-resolutions/{task_id}/rollback")
async def rollback_review_resolution(
    db: DbSession,
    task_id: str,
    body: TargetedCompletionRollbackRequest,
    *,
    novel_id: NovelIdQuery,
) -> dict:
    from modules.imports.review_resolution import rollback_resolution

    await _require_active_project_exclusive(db, novel_id)
    try:
        return await rollback_resolution(db, novel_id=novel_id, task_id=task_id)
    except ValueError as exc:
        raise HTTPException(404, detail="Not found") from exc


@router.post("/review-resolutions/{task_id}/decisions")
async def decide_review_resolution(
    db: DbSession,
    task_id: str,
    body: ReviewResolutionDecisionRequest,
    *,
    novel_id: NovelIdQuery,
) -> dict:
    from modules.imports.review_resolution import accept_decision

    await _require_active_project_exclusive(db, novel_id)
    try:
        return await accept_decision(db, novel_id=novel_id, task_id=task_id, data=body)
    except ValueError as exc:
        raise HTTPException(404, detail="Not found") from exc


@router.post("/review-resolutions/{task_id}/scene-groups/{group_key}/apply")
async def apply_scene_resolution_group(
    db: DbSession,
    task_id: str,
    group_key: str,
    body: SceneResolutionDecisionRequest,
    *,
    novel_id: NovelIdQuery,
) -> dict:
    from modules.imports.review_resolution import accept_scene_group

    await _require_active_project_exclusive(db, novel_id)
    return await accept_scene_group(
        db, novel_id=novel_id, task_id=task_id, group_key=group_key, data=body
    )
