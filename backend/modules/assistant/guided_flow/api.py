"""引导流程 HTTP 入口；鉴权与项目隔离与 Assistant 其余入口一致。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from core.dependencies import DbSession
from modules.account.facade import current_account_id
from modules.assistant.guided_flow import runtime
from modules.assistant.guided_flow.contracts import (
    GuidedFlowAdvanceRequest,
    GuidedFlowSettingsUpdate,
    GuidedFlowStartRequest,
)
from modules.project.facade import require_active_project

router = APIRouter(prefix="/flows", tags=["assistant"])


@router.post("", status_code=201)
async def start_flow(db: DbSession, data: GuidedFlowStartRequest):
    await require_active_project(db, str(data.novel_id))
    return await runtime.start(db, str(data.novel_id), str(current_account_id()), data)


@router.get("/active")
async def active_flow(db: DbSession, novel_id: UUID):
    await require_active_project(db, str(novel_id))
    return await runtime.active_run(db, str(novel_id), str(current_account_id()))


@router.get("/{run_id}")
async def get_flow(db: DbSession, run_id: UUID, novel_id: UUID):
    await require_active_project(db, str(novel_id))
    return await runtime.view(db, str(novel_id), str(run_id), str(current_account_id()))


@router.post("/{run_id}/advance")
async def advance_flow(db: DbSession, run_id: UUID, data: GuidedFlowAdvanceRequest):
    await require_active_project(db, str(data.novel_id))
    return await runtime.advance(
        db,
        str(data.novel_id),
        str(run_id),
        str(current_account_id()),
        data.model_dump(mode="json"),
    )


@router.post("/{run_id}/settings")
async def update_flow_settings(
    db: DbSession, run_id: UUID, data: GuidedFlowSettingsUpdate
):
    await require_active_project(db, str(data.novel_id))
    return await runtime.save_settings(
        db,
        str(data.novel_id),
        str(run_id),
        str(current_account_id()),
        semantic_review=data.semantic_review,
        planning_window=data.planning_window,
    )


@router.post("/{run_id}/abandon")
async def abandon_flow(db: DbSession, run_id: UUID, novel_id: UUID):
    await require_active_project(db, str(novel_id))
    return await runtime.abandon(
        db, str(novel_id), str(run_id), str(current_account_id())
    )
