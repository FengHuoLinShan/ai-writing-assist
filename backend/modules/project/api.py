"""
Project API Router
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from core.csrf import require_xhr_request
from core.dependencies import DbSession
from infrastructure.tasks.enqueuer import enqueue_task
from modules.project.schemas import (
    LLMFieldResetResponse,
    LLMProviderTemplateListResponse,
    ProjectBulkPermanentDeleteRequest,
    ProjectBulkPermanentDeleteResponse,
    ProjectCreate,
    ProjectListResponse,
    ProjectLLMSettingsResponse,
    ProjectLLMSettingsUpdate,
    ProjectResponse,
    ProjectUpdate,
    SmartDedupApplyRequest,
    SmartDedupApplyResponse,
    SmartDedupScanRequest,
    SmartDedupScanResponse,
)
from modules.project.services import ProjectService
from modules.project.smart_dedup import SmartDedupService
from modules.settings.contracts import (
    EffectiveAuthorPrefsResponse,
    EffectiveLLMSettingsResponse,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/projects", tags=["projects"])
_service = ProjectService()
_smart_dedup_service = SmartDedupService()


@router.post("", response_model=ProjectResponse, status_code=201)
async def api_create_project(
    db: DbSession,
    data: ProjectCreate,
) -> ProjectResponse:
    """创建新小说项目"""
    return await _service.create_project(db, data)


@router.get("", response_model=ProjectListResponse)
async def api_list_projects(
    db: DbSession,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> ProjectListResponse:
    """获取项目列表"""
    return await _service.list_projects(db, skip=skip, limit=limit)


@router.get("/recycle-bin", response_model=ProjectListResponse)
async def api_list_deleted_projects(
    db: DbSession,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> ProjectListResponse:
    """获取回收站中的项目列表"""
    return await _service.list_deleted_projects(db, skip=skip, limit=limit)


@router.post(
    "/recycle-bin/permanent-delete",
    response_model=ProjectBulkPermanentDeleteResponse,
)
async def api_bulk_permanent_delete_projects(
    db: DbSession,
    data: ProjectBulkPermanentDeleteRequest,
) -> ProjectBulkPermanentDeleteResponse:
    """批量永久删除回收站项目（原子操作）。"""
    return await _service.permanent_delete_projects(
        db,
        data.project_ids,
        confirmed=data.confirmed,
    )


@router.get("/llm/provider-templates", response_model=LLMProviderTemplateListResponse)
async def api_list_llm_provider_templates() -> LLMProviderTemplateListResponse:
    """获取前端可选的 LLM 供应商模板"""
    return _service.list_llm_provider_templates()


@router.get("/{project_id}/llm-settings", response_model=ProjectLLMSettingsResponse)
async def api_get_project_llm_settings(
    db: DbSession,
    project_id: str,
) -> ProjectLLMSettingsResponse:
    """读取兼容的项目级非 secret LLM/工作流配置。"""
    return await _service.get_llm_settings(db, project_id)


@router.put(
    "/{project_id}/llm-settings",
    response_model=ProjectLLMSettingsResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_update_project_llm_settings(
    db: DbSession,
    project_id: str,
    data: ProjectLLMSettingsUpdate,
) -> ProjectLLMSettingsResponse:
    """更新兼容的项目级非 secret 配置；任何 Key 写入都会被拒绝。"""
    return await _service.update_llm_settings(db, project_id, data)


@router.get(
    "/{project_id}/effective-llm-settings",
    response_model=EffectiveLLMSettingsResponse,
)
async def api_get_effective_llm_settings(
    db: DbSession,
    project_id: str,
) -> EffectiveLLMSettingsResponse:
    """读取账户连接与项目工作流设置合成的 effective 视图。"""
    from modules.settings.facade import get_effective_llm_settings

    return await get_effective_llm_settings(db, project_id)


@router.get(
    "/{project_id}/effective-author-preferences",
    response_model=EffectiveAuthorPrefsResponse,
)
async def api_get_effective_author_prefs(
    db: DbSession,
    project_id: str,
) -> EffectiveAuthorPrefsResponse:
    """获取项目级作者偏好的 effective 视图（项目 > 全局 > 系统）"""
    from modules.settings.facade import get_effective_author_prefs

    return await get_effective_author_prefs(db, project_id)


@router.delete(
    "/{project_id}/llm-settings/field/{field_name}",
    response_model=LLMFieldResetResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_reset_llm_settings_field(
    db: DbSession,
    project_id: str,
    field_name: str,
) -> LLMFieldResetResponse:
    """重置项目级 LLM 单字段为继承全局（D4 白名单）"""
    try:
        return await _service.reset_llm_settings_field(db, project_id, field_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/{project_id}/smart-dedup/scan",
    response_model=SmartDedupScanResponse,
    status_code=201,
)
async def api_start_smart_dedup_scan(
    db: DbSession,
    project_id: str,
    data: SmartDedupScanRequest,
) -> SmartDedupScanResponse:
    """提交项目级智能去重扫描任务。"""
    await _service.get_project(db, project_id)
    from modules.project.facade import build_project_llm_execution_snapshot

    llm_execution_snapshot = await build_project_llm_execution_snapshot(db, project_id)
    task_id = enqueue_task(
        db,
        "smart_dedup_scan",
        meta={
            "novel_id": project_id,
            "llm_execution_snapshot": llm_execution_snapshot,
            **data.model_dump(exclude_none=True),
        },
    )
    await db.flush()
    return SmartDedupScanResponse(task_id=task_id)


@router.post(
    "/{project_id}/smart-dedup/apply",
    response_model=SmartDedupApplyResponse,
)
async def api_apply_smart_dedup(
    db: DbSession,
    project_id: str,
    data: SmartDedupApplyRequest,
) -> SmartDedupApplyResponse:
    """应用用户确认的项目级智能去重建议。"""
    await _service.get_project(db, project_id)
    if data.groups:
        result = await _smart_dedup_service.apply_groups(
            db,
            novel_id=project_id,
            scan_task_id=str(data.scan_task_id),
            groups=[item.model_dump(exclude_none=True) for item in data.groups],
            confirmed=data.confirmed,
        )
    else:
        result = await _smart_dedup_service.apply(
            db,
            novel_id=project_id,
            confirmed=data.confirmed,
            suggestions=[
                item.model_dump(exclude_none=True) for item in (data.suggestions or [])
            ],
        )
    return SmartDedupApplyResponse(**result)


@router.get("/{project_id}", response_model=ProjectResponse)
async def api_get_project(
    db: DbSession,
    project_id: str,
) -> ProjectResponse:
    """获取项目详情"""
    return await _service.get_project(db, project_id)


@router.put("/{project_id}", response_model=ProjectResponse)
async def api_update_project(
    db: DbSession,
    project_id: str,
    data: ProjectUpdate,
) -> ProjectResponse:
    """更新项目信息"""
    return await _service.update_project(db, project_id, data)


@router.delete("/{project_id}", status_code=204)
async def api_delete_project(
    db: DbSession,
    project_id: str,
) -> None:
    """软删除项目（移至回收站）"""
    await _service.delete_project(db, project_id)


@router.post("/{project_id}/restore", response_model=ProjectResponse)
async def api_restore_project(
    db: DbSession,
    project_id: str,
) -> ProjectResponse:
    """从回收站恢复项目"""
    return await _service.restore_project(db, project_id)


@router.delete("/{project_id}/permanent", status_code=204)
async def api_permanent_delete_project(
    db: DbSession,
    project_id: str,
    confirmed: bool = Query(default=False, description="二次确认永久删除"),
) -> None:
    """永久删除项目（级联删除所有关联数据，不可恢复）"""
    await _service.permanent_delete_project(db, project_id, confirmed=confirmed)
