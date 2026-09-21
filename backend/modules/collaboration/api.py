"""Author routes. Runtime plans never determine routes or caller identity."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from core.dependencies import DbSession
from core.errors import NotFoundError
from modules.collaboration import cases, views, workspaces
from modules.collaboration.contracts import (
    CaseCreate,
    GoalUpdate,
    GrantUpdate,
    MergeRequest,
    RebaseRequest,
    ResourceKind,
    RevisionRequest,
    RunCreate,
    WorkspaceCreate,
    WorkspaceEdit,
)
from modules.collaboration.merge import merge_workspace
from modules.collaboration.models import CollaborationCase, CollaborationRun
from modules.collaboration.recipes import RECIPES
from modules.project.facade import (
    require_active_project,
)
from modules.project.facade import (
    require_active_project_exclusive as _require_active_project_exclusive,
)


async def _guard_project(request: Request, db: DbSession, novel_id: UUID):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        await _require_active_project_exclusive(db, str(novel_id))
    else:
        await require_active_project(db, str(novel_id))


router = APIRouter(
    prefix="/api/collaboration",
    tags=["collaboration"],
    dependencies=[Depends(_guard_project)],
)


@router.get("/resources")
async def resources(
    db: DbSession,
    novel_id: UUID,
    kind: ResourceKind = "writing_draft",
    offset: int = Query(0, ge=0),
    query: str = Query("", max_length=200),
):
    return await views.resource_choices(db, str(novel_id), kind, offset, query)


@router.get("/capabilities")
async def capabilities(db: DbSession, novel_id: UUID):
    from core.config import get_settings
    from infrastructure.llm.web_search import search_status

    await require_active_project(db, str(novel_id))
    from modules.account.facade import get_account_llm_settings_contract
    from modules.project.facade import get_project_context

    project = await get_project_context(db, str(novel_id))
    account_settings = await get_account_llm_settings_contract(
        db, owner_id=UUID(project.owner_id)
    )
    return {
        "web_search": search_status(),
        "model_connections": [
            {"provider_id": value, "label": value}
            for value in account_settings.configured_provider_ids
        ],
        "enabled": get_settings().assistant_enabled
        and get_settings().collaboration_v2_enabled,
        "experimental": True,
        "recipes": [recipe.model_dump(mode="json") for recipe in RECIPES.values()],
        "resource_kinds": [
            "writing_draft",
            "scene",
            "foreshadowing_plan",
            "reveal_plan",
            "world_bible_draft",
        ],
    }


@router.post("/cases", status_code=201)
async def create_case(db: DbSession, novel_id: UUID, data: CaseCreate):
    return await cases.create_case(db, str(novel_id), data)


@router.get("/cases")
async def list_cases(db: DbSession, novel_id: UUID, limit: int = Query(20, ge=1, le=100)):
    await require_active_project(db, str(novel_id))
    rows = await db.scalars(
        select(CollaborationCase)
        .where(CollaborationCase.novel_id == novel_id)
        .order_by(CollaborationCase.updated_at.desc())
        .limit(limit)
    )
    return {"items": [cases.case_view(case) for case in rows]}


@router.get("/cases/{case_id}")
async def get_case(db: DbSession, novel_id: UUID, case_id: UUID):
    return cases.case_view(await cases.require_case(db, str(novel_id), case_id))


@router.put("/cases/{case_id}/goal")
async def update_goal(db: DbSession, novel_id: UUID, case_id: UUID, data: GoalUpdate):
    return await cases.update_goal(db, str(novel_id), case_id, data)


@router.post("/cases/{case_id}/runs", status_code=202)
async def submit_run(db: DbSession, novel_id: UUID, case_id: UUID, data: RunCreate):
    return await cases.submit_run(db, str(novel_id), case_id, data)


@router.get("/cases/{case_id}/runs")
async def list_runs(db: DbSession, novel_id: UUID, case_id: UUID):
    await cases.require_case(db, str(novel_id), case_id)
    rows = await db.scalars(
        select(CollaborationRun)
        .where(CollaborationRun.novel_id == novel_id, CollaborationRun.case_id == case_id)
        .order_by(CollaborationRun.created_at.desc())
        .limit(50)
    )
    return {
        "items": [
            {"id": str(row.id), "status": row.status, "created_at": row.created_at}
            for row in rows
        ]
    }


@router.get("/runs/{run_id}")
async def get_run(db: DbSession, novel_id: UUID, run_id: UUID):
    return await views.run_view(db, str(novel_id), str(run_id))


@router.post("/runs/{run_id}/stop")
async def stop_run(db: DbSession, novel_id: UUID, run_id: UUID):
    return await cases.stop_run(db, str(novel_id), str(run_id))


@router.post("/cases/{case_id}/workspaces", status_code=201)
async def create_workspace(
    db: DbSession, novel_id: UUID, case_id: UUID, data: WorkspaceCreate
):
    return await workspaces.create_workspace(db, str(novel_id), case_id, data)


@router.get("/cases/{case_id}/workspaces")
async def list_workspaces(db: DbSession, novel_id: UUID, case_id: UUID):
    return {"items": await views.workspace_list(db, str(novel_id), case_id)}


@router.post("/workspaces/{workspace_id}/fork", status_code=201)
async def fork_workspace(
    db: DbSession, novel_id: UUID, workspace_id: UUID, data: WorkspaceCreate
):
    workspace = await workspaces.require_workspace(db, str(novel_id), workspace_id)
    parent, _ = await workspaces.require_revision(
        db, str(novel_id), data.parent_revision_id or workspace.current_revision_id
    )
    if parent.id != workspace.id:
        raise NotFoundError("试改修订不可访问")
    return await workspaces.create_workspace(
        db,
        str(novel_id),
        workspace.case_id,
        data.model_copy(
            update={
                "parent_revision_id": data.parent_revision_id
                or workspace.current_revision_id
            }
        ),
    )


@router.get("/workspaces/{workspace_id}/diff")
async def get_diff(
    db: DbSession, novel_id: UUID, workspace_id: UUID, revision_id: UUID | None = None
):
    return await workspaces.workspace_view(
        db, str(novel_id), workspace_id, revision_id=revision_id
    )


@router.post("/workspaces/{workspace_id}/revisions", status_code=201)
async def edit_workspace(
    db: DbSession, novel_id: UUID, workspace_id: UUID, data: WorkspaceEdit
):
    return await workspaces.edit_workspace(db, str(novel_id), workspace_id, data)


@router.post("/workspaces/{workspace_id}/test", status_code=202)
async def test_workspace(
    db: DbSession, novel_id: UUID, workspace_id: UUID, data: RunCreate
):
    workspace = await workspaces.require_workspace(db, str(novel_id), workspace_id)
    parent, _ = await workspaces.require_revision(
        db, str(novel_id), data.workspace_revision_id or workspace.current_revision_id
    )
    if parent.id != workspace.id:
        raise NotFoundError("试改修订不可访问")
    return await cases.submit_run(
        db,
        str(novel_id),
        workspace.case_id,
        data.model_copy(
            update={
                "workspace_revision_id": data.workspace_revision_id
                or workspace.current_revision_id
            }
        ),
    )


@router.post("/workspaces/{workspace_id}/seal")
async def seal_workspace(
    db: DbSession, novel_id: UUID, workspace_id: UUID, data: RevisionRequest
):
    return await workspaces.seal_workspace(db, str(novel_id), workspace_id, data)


@router.post("/workspaces/{workspace_id}/merge")
async def merge(db: DbSession, novel_id: UUID, workspace_id: UUID, data: MergeRequest):
    return await merge_workspace(db, str(novel_id), workspace_id, data)


@router.put("/cases/{case_id}/grant")
async def update_grant(db: DbSession, novel_id: UUID, case_id: UUID, data: GrantUpdate):
    return await cases.update_grant(db, str(novel_id), case_id, data)


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(db: DbSession, novel_id: UUID, run_id: UUID):
    return await cases.resume_run(db, str(novel_id), run_id)


@router.post("/workspaces/{workspace_id}/rebase")
async def rebase_workspace(
    db: DbSession, novel_id: UUID, workspace_id: UUID, data: RebaseRequest
):
    from modules.collaboration.recovery import rebase

    return await rebase(db, str(novel_id), workspace_id, data)


@router.post("/workspaces/{workspace_id}/revert")
async def revert_workspace(
    db: DbSession, novel_id: UUID, workspace_id: UUID, data: RebaseRequest
):
    from modules.collaboration.recovery import rebase

    return await rebase(db, str(novel_id), workspace_id, data, revert=True)


from modules.imports.contracts import ImportConsultScope  # noqa: E402


@router.post("/import-scope")
async def inspect_import_scope(db: DbSession, novel_id: UUID, data: ImportConsultScope):
    from modules.imports.facade import inspect_consultation_scope

    await require_active_project(db, str(novel_id))
    return await inspect_consultation_scope(db, str(novel_id), data)
