"""Project-owned preference routes."""

from fastapi import APIRouter, Depends, HTTPException, Query

from core.csrf import require_xhr_request
from core.dependencies import DbSession
from modules.project.facade import (
    get_project_author_preferences,
    list_projects_using_defaults,
    reset_project_author_preferences_field,
    upsert_project_author_preferences,
)
from modules.project.settings_schemas import (
    ProjectAuthorPrefsResponse,
    ProjectAuthorPrefsUpdate,
    ProjectsUsingDefaultsResponse,
)

defaults_handler_router = APIRouter(tags=["settings"])
handler_router = APIRouter(tags=["settings"])
router = handler_router


@defaults_handler_router.get(
    "/projects-using-defaults", response_model=ProjectsUsingDefaultsResponse
)
async def api_list_projects_using_defaults(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ProjectsUsingDefaultsResponse:
    return await list_projects_using_defaults(db, limit=limit, offset=offset)


@router.get(
    "/{project_id}/author-preferences",
    response_model=ProjectAuthorPrefsResponse,
)
async def api_get_project_author_prefs(
    db: DbSession,
    project_id: str,
) -> ProjectAuthorPrefsResponse:
    return await get_project_author_preferences(db, project_id)


@router.put(
    "/{project_id}/author-preferences",
    response_model=ProjectAuthorPrefsResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_put_project_author_prefs(
    db: DbSession,
    project_id: str,
    data: ProjectAuthorPrefsUpdate,
) -> ProjectAuthorPrefsResponse:
    return await upsert_project_author_preferences(db, project_id, data.model_dump())


@router.delete(
    "/{project_id}/author-preferences/field/{field_name}",
    dependencies=[Depends(require_xhr_request)],
)
async def api_reset_project_author_prefs_field(
    db: DbSession,
    project_id: str,
    field_name: str,
):
    try:
        return await reset_project_author_preferences_field(
            db,
            project_id,
            field_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
