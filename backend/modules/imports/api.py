"""
Import API 路由

提供小说文件上传与导入的 REST API。
"""

from __future__ import annotations

import logging
import os
from typing import Literal

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, model_validator

from core.api_params import NovelIdForm, NovelIdQuery
from core.config import get_settings
from core.dependencies import DbSession
from core.errors import DomainError, NotFoundError
from core.errors import ValidationError as DomainValidationError
from infrastructure.llm.redaction import redact_diagnostic
from modules.imports.parsers import MAX_FILE_SIZE
from modules.imports.schemas import ImportListResponse, ImportResponse
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

    task_id: str = Field(
        default="",
        description="待继续或放弃的深度导入任务 ID",
    )


class MapObservationEnrichmentRequest(BaseModel):
    """Map-only enrichment request; it never invokes a deep-import stage."""

    novel_id: str = Field(..., min_length=1)
    start_chapter: int = Field(default=1, ge=1)
    end_chapter: int = Field(default=0, ge=0)
    high_quality: bool = True
    adoption_policy: Literal["user_authorized_pipeline"] = "user_authorized_pipeline"
    authorization_confirmed: bool = Field(
        ...,
        description="已理解并授权流水线写入地图待复核候选",
    )

    @model_validator(mode="after")
    def validate_chapter_range(self) -> MapObservationEnrichmentRequest:
        if self.end_chapter and self.end_chapter < self.start_chapter:
            raise ValueError("end_chapter must be >= start_chapter")
        if self.authorization_confirmed is not True:
            raise ValueError("authorization_confirmed must be true")
        return self


class DeepImportCleanupSummaryResponse(BaseModel):
    """Workflow cleanup result with legacy aliases kept for wire compatibility."""

    deprecated_scenes: int = 0
    deprecated_entities: int = 0
    deprecated_structure_assets: int = 0
    hard_deleted_assets: int = 0
    cleanup_mode: Literal["soft_deprecate"] = "soft_deprecate"
    rolled_back_delta_logs: int = 0
    rolled_back_map_observations: int = 0
    rolled_back_aliases: int = 0
    rolled_back_relations: int = 0
    skipped_delta_logs: int = Field(
        0,
        description="兼容旧字段；已由 rolled_back_delta_logs 取代",
    )
    skipped_map_observations: int = Field(
        0,
        description="兼容旧字段；已由 rolled_back_map_observations 取代",
    )
    cleanup_todo: str | None = Field(
        None,
        description="兼容旧字段；当前清理已在放弃时完成",
    )


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
        return await _service.upload_and_import(
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
    )
    return result


async def _submit_stage(
    db: DbSession,
    body: DeepImportRequest,
    *,
    stage: str,
) -> dict:
    from modules.imports.facade import start_deep_import_stage as _start_stage

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


@router.post("/stages/map-observations", status_code=201)
async def submit_map_observation_enrichment(
    db: DbSession,
    body: MapObservationEnrichmentRequest = Body(
        ...,
        description="既有 Scene 的地图事实补充参数",
    ),
) -> dict:
    """提交地图事实补充任务；不重跑深度导入的任何阶段。"""
    from modules.imports.facade import start_map_observation_enrichment as _submit

    await _require_active_project(db, body.novel_id)
    end_chapter = await _resolve_end_chapter(db, body)
    _validate_chapter_count_limit(body.start_chapter, end_chapter)
    return await _submit(
        db,
        novel_id=body.novel_id,
        start_chapter=body.start_chapter,
        end_chapter=end_chapter,
        high_quality=body.high_quality,
        adoption_policy=body.adoption_policy,
        authorization_confirmed=body.authorization_confirmed,
    )


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
        result = await imports_facade.resume_deep_import(db, task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(404, detail=redact_diagnostic(exc)) from exc
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
        raise HTTPException(404, detail=redact_diagnostic(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=redact_diagnostic(exc)) from exc
    return DeepImportAbandonResponse.model_validate(result)
