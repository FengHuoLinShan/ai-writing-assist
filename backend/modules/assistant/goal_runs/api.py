"""Author-facing HTTP routes for persistent goal runs."""

from uuid import UUID

from fastapi import APIRouter, Query

from core.dependencies import DbSession
from core.errors import NotFoundError, ValidationError
from modules.account.facade import current_account_id
from modules.assistant.goal_runs import service
from modules.assistant.goal_runs.contracts import (
    GoalAction,
    GoalOutcomeReconciliation,
    GoalPlanApproval,
    GoalReceiptPreview,
    GoalReplanRequest,
    GoalResume,
    GoalRunStart,
    GoalStepApproval,
)
from modules.project.facade import require_active_project

router = APIRouter(prefix="/goals", tags=["assistant-goals"])
_ORCHESTRATION_EXEMPTION = (
    "Author-controlled goal orchestration. Every domain step is resolved from the "
    "registered Assistant operation catalog and revalidated against the frozen "
    "goal scope before its domain operation is called."
)


def _owner_id() -> str:
    return str(current_account_id())


@router.get("/capabilities")
async def goal_capabilities(db: DbSession, novel_id: UUID = Query(...)):
    try:
        await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    except NotFoundError:
        return {"enabled": False}
    return await service.goal_capabilities(db, str(novel_id), _owner_id())


@router.get("/active")
async def active_goal(db: DbSession, novel_id: UUID = Query(...)):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.get_active_goal(db, str(novel_id), _owner_id())


@router.get("/recent")
async def recent_goals(db: DbSession, novel_id: UUID = Query(...)):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.get_recent_goals(db, str(novel_id), _owner_id())


@router.post(
    "",
    openapi_extra={"x-novelcraft-operation-exemption": _ORCHESTRATION_EXEMPTION},
)
async def start_goal(db: DbSession, data: GoalRunStart):
    await require_active_project(db, str(data.novel_id), allow_demo_readonly=False)
    return await service.start_goal(db, data, _owner_id())


@router.get("/{run_id}")
async def goal_run(
    db: DbSession,
    run_id: UUID,
    novel_id: UUID = Query(...),
):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.get_goal(db, str(novel_id), str(run_id), _owner_id())


@router.post(
    "/{run_id}/approve",
    openapi_extra={"x-novelcraft-operation-exemption": _ORCHESTRATION_EXEMPTION},
)
async def approve_goal_plan(
    db: DbSession,
    run_id: UUID,
    data: GoalPlanApproval,
    novel_id: UUID = Query(...),
):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.approve_goal_plan(
        db,
        novel_id=str(novel_id),
        run_id=str(run_id),
        data=data,
        owner_id=_owner_id(),
    )


@router.post(
    "/{run_id}/advance",
    openapi_extra={"x-novelcraft-operation-exemption": _ORCHESTRATION_EXEMPTION},
)
async def advance_goal(
    db: DbSession, run_id: UUID, data: GoalAction, novel_id: UUID = Query(...)
):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.advance_goal(
        db, str(novel_id), str(run_id), _owner_id(), data=data
    )


@router.post(
    "/{run_id}/steps/{step_id}/approve",
    openapi_extra={"x-novelcraft-operation-exemption": _ORCHESTRATION_EXEMPTION},
)
async def approve_goal_step(
    db: DbSession,
    run_id: UUID,
    step_id: str,
    data: GoalStepApproval,
    novel_id: UUID = Query(...),
):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    if data.step_id != step_id:
        raise ValidationError("步骤标识与请求路径不一致")
    return await service.approve_goal_step(
        db, str(novel_id), str(run_id), data, _owner_id()
    )


@router.post(
    "/{run_id}/steps/{step_id}/reconcile",
    openapi_extra={"x-novelcraft-operation-exemption": _ORCHESTRATION_EXEMPTION},
)
async def reconcile_goal_step(
    db: DbSession,
    run_id: UUID,
    step_id: str,
    data: GoalOutcomeReconciliation,
    novel_id: UUID = Query(...),
):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.reconcile_goal_step(
        db, str(novel_id), str(run_id), step_id, data, _owner_id()
    )


@router.get(
    "/{run_id}/steps/{step_id}/receipt",
    response_model=GoalReceiptPreview,
)
async def goal_step_receipt_preview(
    db: DbSession,
    run_id: UUID,
    step_id: str,
    novel_id: UUID = Query(...),
    expected_revision: int = Query(..., ge=1),
):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.goal_step_receipt_preview(
        db,
        str(novel_id),
        str(run_id),
        step_id,
        expected_revision,
        _owner_id(),
    )


@router.post(
    "/{run_id}/pause",
    openapi_extra={"x-novelcraft-operation-exemption": _ORCHESTRATION_EXEMPTION},
)
async def pause_goal(
    db: DbSession, run_id: UUID, data: GoalAction, novel_id: UUID = Query(...)
):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.pause_goal(db, str(novel_id), str(run_id), data, _owner_id())


@router.post(
    "/{run_id}/resume",
    openapi_extra={"x-novelcraft-operation-exemption": _ORCHESTRATION_EXEMPTION},
)
async def resume_goal(
    db: DbSession, run_id: UUID, data: GoalResume, novel_id: UUID = Query(...)
):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.resume_goal(db, str(novel_id), str(run_id), data, _owner_id())


@router.post(
    "/{run_id}/cancel",
    openapi_extra={"x-novelcraft-operation-exemption": _ORCHESTRATION_EXEMPTION},
)
async def cancel_goal(
    db: DbSession, run_id: UUID, data: GoalAction, novel_id: UUID = Query(...)
):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.cancel_goal(db, str(novel_id), str(run_id), data, _owner_id())


@router.post(
    "/{run_id}/replan",
    openapi_extra={"x-novelcraft-operation-exemption": _ORCHESTRATION_EXEMPTION},
)
async def replan_goal(
    db: DbSession,
    run_id: UUID,
    data: GoalReplanRequest,
    novel_id: UUID = Query(...),
):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.replan_goal(db, str(novel_id), str(run_id), data, _owner_id())


@router.post(
    "/{run_id}/restore",
    openapi_extra={"x-novelcraft-operation-exemption": _ORCHESTRATION_EXEMPTION},
)
async def restore_goal_changes(
    db: DbSession, run_id: UUID, data: GoalAction, novel_id: UUID = Query(...)
):
    await require_active_project(db, str(novel_id), allow_demo_readonly=False)
    return await service.restore_goal_changes(
        db, str(novel_id), str(run_id), data, _owner_id()
    )
