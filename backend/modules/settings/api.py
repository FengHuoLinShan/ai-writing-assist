"""Settings API router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.dependencies import DbSession
from modules.settings.schemas import (
    GlobalAuthorPrefsResponse,
    GlobalAuthorPrefsUpdate,
    GlobalLLMDefaultsResponse,
    GlobalLLMDefaultsUpdate,
    ProjectAuthorPrefsResponse,
    ProjectAuthorPrefsUpdate,
    ProjectsUsingDefaultsResponse,
)
from modules.settings.services import SettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])
_service = SettingsService()


@router.get("/llm-defaults", response_model=GlobalLLMDefaultsResponse | None)
async def api_get_global_llm_defaults(db: DbSession) -> GlobalLLMDefaultsResponse | None:
    return await _service.get_global_llm_defaults(db)


@router.put("/llm-defaults", response_model=GlobalLLMDefaultsResponse)
async def api_put_global_llm_defaults(
    db: DbSession,
    data: GlobalLLMDefaultsUpdate,
) -> GlobalLLMDefaultsResponse:
    try:
        return await _service.upsert_global_llm_defaults(
            db, data.model_dump(exclude_unset=True)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/author-preferences", response_model=GlobalAuthorPrefsResponse | None)
async def api_get_global_author_prefs(db: DbSession) -> GlobalAuthorPrefsResponse | None:
    return await _service.get_global_author_prefs(db)


@router.put("/author-preferences", response_model=GlobalAuthorPrefsResponse)
async def api_put_global_author_prefs(
    db: DbSession,
    data: GlobalAuthorPrefsUpdate,
) -> GlobalAuthorPrefsResponse:
    return await _service.upsert_global_author_prefs(
        db, data.model_dump(exclude_unset=True)
    )


@router.get("/projects-using-defaults", response_model=ProjectsUsingDefaultsResponse)
async def api_list_projects_using_defaults(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ProjectsUsingDefaultsResponse:
    return await _service.list_projects_using_defaults(db, limit=limit, offset=offset)


@router.post("/refresh")
async def api_refresh_settings() -> dict:
    """调试端点：触发客户端刷新（D16）。"""
    return {"ok": True}


@router.get(
    "/projects/{project_id}/author-preferences",
    response_model=ProjectAuthorPrefsResponse,
)
async def api_get_project_author_prefs(
    db: DbSession,
    project_id: str,
) -> ProjectAuthorPrefsResponse:
    return await _service.get_project_author_prefs(db, project_id)


@router.put(
    "/projects/{project_id}/author-preferences",
    response_model=ProjectAuthorPrefsResponse,
)
async def api_put_project_author_prefs(
    db: DbSession,
    project_id: str,
    data: ProjectAuthorPrefsUpdate,
) -> ProjectAuthorPrefsResponse:
    return await _service.upsert_project_author_prefs(db, project_id, data.model_dump())


@router.delete("/projects/{project_id}/author-preferences/field/{field_name}")
async def api_reset_project_author_prefs_field(
    db: DbSession,
    project_id: str,
    field_name: str,
):
    try:
        return await _service.reset_project_author_prefs_field(db, project_id, field_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
