"""
Project API Router
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.csrf import require_xhr_request
from core.dependencies import DbSession
from modules.project.ai_usage import get_project_ai_usage
from modules.project.author_examples import AuthorExamplesUpdate
from modules.project.author_task_service import AuthorTaskService
from modules.project.editorial_brief import EditorialBriefUpdate
from modules.project.facade import (
    read_editorial_brief,
    read_editorial_brief_for_writing,
    save_editorial_brief,
    set_editorial_brief_for_writing,
)
from modules.project.schemas import (
    AuthorTaskCreateRequest,
    AuthorTaskListResponse,
    AuthorTaskPatchRequest,
    AuthorTaskResponse,
    DemoProjectCopyResponse,
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
    ProjectWorkspaceSummaryResponse,
    SmartDedupApplyRequest,
    SmartDedupApplyResponse,
    SmartDedupScanRequest,
    SmartDedupScanResponse,
)
from modules.project.services import ProjectService
from modules.project.settings_schemas import (
    EffectiveAuthorPrefsResponse,
    EffectiveLLMSettingsResponse,
)
from modules.project.smart_dedup import SmartDedupService
from modules.project.workspace_service import ProjectWorkspaceSummaryService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/projects", tags=["projects"])
class EditorialBriefWritingToggle(BaseModel):
    enabled: bool


_service = ProjectService()
_author_task_service = AuthorTaskService(_service)
_smart_dedup_service = SmartDedupService()
_workspace_summary_service = ProjectWorkspaceSummaryService(
    project_reader=_service.get_project,
    author_task_summary_reader=_author_task_service.get_workspace_summary,
)


@router.get("/{project_id}/editorial-brief")
async def get_editorial_brief(db: DbSession, project_id: UUID):
    return await read_editorial_brief(db, str(project_id))


@router.put(
    "/{project_id}/editorial-brief",
    dependencies=[Depends(require_xhr_request)],
)
async def put_editorial_brief(
    db: DbSession, project_id: UUID, data: EditorialBriefUpdate
):
    return await save_editorial_brief(db, str(project_id), data)


@router.get("/{project_id}/ai-usage")
async def read_project_ai_usage(
    db: DbSession,
    project_id: UUID,
    days: int = Query(default=30, ge=1, le=365),
):
    """按能力汇总近 N 天 AI 用量（owner 次级诊断入口）。"""
    return await get_project_ai_usage(db, str(project_id), days=days)


@router.get("/{project_id}/editorial-brief/for-writing")
async def get_editorial_brief_for_writing(db: DbSession, project_id: UUID):
    """读取「编辑约定也用于 AI 写作」开关（默认关闭）。

    enabled 为作者设置的原始开关；effective 表示开关开启且约定非空
    （实际进入写作上下文的有效态）。
    """
    from modules.project.editorial_brief import read_editorial_brief_writing_toggle

    toggle = await read_editorial_brief_writing_toggle(db, str(project_id))
    payload = await read_editorial_brief_for_writing(db, str(project_id))
    return {
        "enabled": bool(toggle.get("enabled")),
        "effective": payload is not None,
        "brief": payload,
    }


@router.put(
    "/{project_id}/editorial-brief/for-writing",
    dependencies=[Depends(require_xhr_request)],
)
async def put_editorial_brief_for_writing(
    db: DbSession,
    project_id: UUID,
    data: EditorialBriefWritingToggle,
):
    return await set_editorial_brief_for_writing(
        db, str(project_id), enabled=data.enabled
    )


class AuthorExamplesWritingToggle(BaseModel):
    enabled: bool


@router.get("/{project_id}/author-examples")
async def get_author_examples(db: DbSession, project_id: UUID):
    """作者写作示例（好例/反例）列表。"""
    from modules.project.author_examples import read_author_examples

    return await read_author_examples(db, str(project_id))


@router.put(
    "/{project_id}/author-examples",
    dependencies=[Depends(require_xhr_request)],
)
async def put_author_examples(
    db: DbSession, project_id: UUID, data: AuthorExamplesUpdate
):
    from modules.project.author_examples import save_author_examples

    return await save_author_examples(db, str(project_id), data)


@router.get("/{project_id}/author-examples/for-writing")
async def get_author_examples_for_writing(db: DbSession, project_id: UUID):
    """读取「示例用于 AI 写作」开关（默认关闭）。"""
    from modules.project.author_examples import (
        read_author_examples_for_writing,
        read_author_examples_writing_toggle,
    )

    toggle = await read_author_examples_writing_toggle(db, str(project_id))
    payload = await read_author_examples_for_writing(db, str(project_id))
    return {
        "enabled": bool(toggle.get("enabled")),
        "effective": payload is not None,
        "examples": payload,
    }


@router.put(
    "/{project_id}/author-examples/for-writing",
    dependencies=[Depends(require_xhr_request)],
)
async def put_author_examples_for_writing(
    db: DbSession,
    project_id: UUID,
    data: AuthorExamplesWritingToggle,
):
    from modules.project.author_examples import set_author_examples_for_writing

    return await set_author_examples_for_writing(
        db, str(project_id), enabled=data.enabled
    )


@router.post(
    "/demo-copy",
    response_model=DemoProjectCopyResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_copy_public_demo(db: DbSession) -> DemoProjectCopyResponse:
    """Copy the configured public demo into the current account once per version."""
    from modules.project.demo_copy import DemoProjectCopyService

    result = await DemoProjectCopyService().copy(db)
    return DemoProjectCopyResponse(status=result.status, project=result.project)


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
    from modules.project.facade import get_effective_llm_settings

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
    from modules.project.facade import get_effective_author_prefs

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
    try:
        return await _smart_dedup_service.submit_scan(db, project_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.get(
    "/{project_id}/workspace-summary",
    response_model=ProjectWorkspaceSummaryResponse,
)
async def api_get_project_workspace_summary(
    db: DbSession,
    project_id: str,
    focus_chapter_index: int | None = Query(default=None, ge=0),
    focus_scene_id: str | None = Query(default=None),
    on_date: date | None = Query(default=None),
) -> ProjectWorkspaceSummaryResponse:
    """Return the safe, task-oriented read model for the author's project home."""
    return await _workspace_summary_service.get_summary(
        db,
        project_id,
        focus_chapter_index=focus_chapter_index,
        focus_scene_id=focus_scene_id,
        on_date=on_date,
    )


@router.get(
    "/{project_id}/author-tasks",
    response_model=AuthorTaskListResponse,
)
async def api_list_author_tasks(
    db: DbSession,
    project_id: str,
    scope: Literal["today", "inbox", "later", "completed", "archived"] = Query(
        default="today"
    ),
    on_date: date | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> AuthorTaskListResponse:
    """List one project task view without exposing domain or worker tasks."""
    return await _author_task_service.list_tasks(
        db,
        project_id,
        scope=scope,
        on_date=on_date or datetime.now(UTC).date(),
        skip=skip,
        limit=limit,
    )


@router.post(
    "/{project_id}/author-tasks",
    response_model=AuthorTaskResponse,
    status_code=201,
    dependencies=[Depends(require_xhr_request)],
)
async def api_create_author_task(
    db: DbSession,
    project_id: str,
    data: AuthorTaskCreateRequest,
) -> AuthorTaskResponse:
    """Create an author-owned task; initial status is always open."""
    return await _author_task_service.create_task(db, project_id, data)


@router.patch(
    "/{project_id}/author-tasks/{task_id}",
    response_model=AuthorTaskResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_patch_author_task(
    db: DbSession,
    project_id: str,
    task_id: str,
    data: AuthorTaskPatchRequest,
) -> AuthorTaskResponse:
    """Edit, complete, reopen, archive, or detach one author task."""
    return await _author_task_service.patch_task(db, project_id, task_id, data)


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


from modules.project.settings_api import (  # noqa: E402
    handler_router as settings_handler_router,
)

router.include_router(settings_handler_router)


@router.get("/{project_id}/smart-dedup/scans")
async def recent_smart_dedup_scans(project_id: str, db: DbSession) -> dict:
    from modules.project.facade import require_active_project

    await require_active_project(db, project_id)
    from infrastructure.tasks.facade import list_recent_task_summaries

    return {
        "items": await list_recent_task_summaries(
            db, novel_id=project_id, task_type="smart_dedup_scan", limit=20
        )
    }


@router.get("/{project_id}/smart-dedup/scans/{task_id}/review-state")
async def smart_dedup_scan_review_state(
    project_id: str, task_id: UUID, db: DbSession
) -> dict:
    from modules.project.facade import require_active_project

    await require_active_project(db, project_id)
    return await _smart_dedup_service.scan_review_state(
        db, novel_id=project_id, task_id=str(task_id)
    )
