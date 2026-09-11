"""Thin authenticated assistant API; private execution state is never returned."""

from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from core.config import get_settings
from core.dependencies import DbSession
from core.errors import NotFoundError
from infrastructure.tasks.facade import cancel_exact_task
from modules.account.facade import current_account_id
from modules.assistant.models import AssistantRun
from modules.assistant.operations import catalog, decide_batch
from modules.assistant.schemas import (
    CONTROLLED_DESTINATIONS,
    BatchDecision,
    BatchRecheck,
    NoticeDecision,
    NoticeRecheck,
    ProactivePolicyUpdate,
    RunEventsResponse,
    RunResponse,
    RunResume,
    SessionCreate,
    TurnCreate,
)
from modules.assistant.service import AssistantService, record_run_event
from modules.project.facade import require_active_project

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
service = AssistantService()


@router.post("/notices/{notice_id}/recheck")
async def recheck_notice(
    db: DbSession, novel_id: UUID, notice_id: UUID, data: NoticeRecheck
):
    await require_active_project(db, str(novel_id))
    from modules.assistant.proactive import recheck_notice as recheck

    return await recheck(db, str(novel_id), notice_id, data.operation_id)


@router.get("/capabilities")
async def capabilities(db: DbSession, novel_id: UUID):
    await require_active_project(db, str(novel_id))
    from infrastructure.llm.native_search import native_search_status
    from infrastructure.llm.web_search import search_availability
    from modules.project.contracts import ProjectLLMConfigurationError
    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        get_effective_llm_settings,
    )
    from modules.world.map_atlas_facade import map_capabilities

    llm = await get_effective_llm_settings(db, novel_id)
    try:
        snapshot = await build_project_llm_execution_snapshot(db, str(novel_id))
        model_ready = bool(snapshot["profile"]["api_key_configured"])
    except ProjectLLMConfigurationError:
        model_ready = False
    reason = (
        "项目助手尚未开启"
        if not get_settings().assistant_enabled
        else None
        if model_ready
        else "请先连接并验证当前模型，讨论记录仍可查看。"
    )
    return {
        "enabled": get_settings().assistant_enabled,
        "operations": [
            {
                "name": name,
                "label": operation.label,
                "permission": operation.permission,
                "available": reason is None,
                "reason": reason,
            }
            for name, operation in catalog().items()
        ],
        "destinations": [
            {"id": key, "label": label} for key, label in CONTROLLED_DESTINATIONS.items()
        ],
        "runtime": "pydantic-ai-2.42.0",
        "model": {
            "available": model_ready,
            "reason": None
            if model_ready
            else "请先连接并验证当前模型，讨论记录仍可查看。",
            "destination": "model_settings",
        },
        "web_search": await search_availability(),
        "map": await map_capabilities(db, str(novel_id)),
        "native_search": native_search_status(
            str(llm.provider_id.value or ""), str(llm.model.value or "")
        ),
    }


@router.post("/sessions", status_code=201)
async def create_session(db: DbSession, data: SessionCreate):
    await require_active_project(db, str(data.novel_id))
    return await service.create_session(db, data)


@router.get("/sessions")
async def list_sessions(
    db: DbSession,
    novel_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    await require_active_project(db, str(novel_id))
    rows, total = await service.sessions.list_sessions(
        db, novel_id=str(novel_id), skip=skip, limit=limit
    )
    return {"items": rows, "total": total}


@router.get("/sessions/{session_id}")
async def get_session(db: DbSession, session_id: UUID, novel_id: UUID):
    await require_active_project(db, str(novel_id))
    detail = await service.sessions.get_detail(db, str(novel_id), str(session_id))
    latest = await db.scalar(
        select(AssistantRun)
        .where(AssistantRun.session_id == session_id, AssistantRun.novel_id == novel_id)
        .order_by(AssistantRun.created_at.desc(), AssistantRun.id.desc())
        .limit(1)
    )
    return {
        **detail.model_dump(mode="json"),
        "latest_run": await service.get_run(db, str(novel_id), str(latest.id))
        if latest
        else None,
        "last_context": latest.request_json.get("context") if latest else None,
        "last_allow_web": latest.request_json.get("allow_web", True) if latest else None,
        "last_web_backend": latest.request_json.get("web_backend") if latest else None,
    }


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    db: DbSession,
    session_id: UUID,
    novel_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
):
    await require_active_project(db, str(novel_id))
    rows, total, offset = await service.sessions.list_messages(
        db,
        novel_id=str(novel_id),
        session_id=str(session_id),
        skip=skip,
        limit=limit,
        search=search,
    )
    return {"items": rows, "total": total, "offset": offset}


@router.post("/sessions/{session_id}/turns", status_code=202, response_model=RunResponse)
async def submit_turn(db: DbSession, session_id: UUID, data: TurnCreate):
    await require_active_project(db, str(data.novel_id))
    return await service.submit(db, str(session_id), data, str(current_account_id()))


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(db: DbSession, run_id: UUID, novel_id: UUID):
    await require_active_project(db, str(novel_id))
    return await service.get_run(db, str(novel_id), str(run_id))


@router.get("/runs/{run_id}/events", response_model=RunEventsResponse)
async def get_run_events(
    db: DbSession, run_id: UUID, novel_id: UUID, after: int = Query(0, ge=0)
):
    await require_active_project(db, str(novel_id))
    return await service.get_events(db, str(novel_id), str(run_id), after)


@router.post("/runs/{run_id}/stop", response_model=RunResponse)
async def stop_run(db: DbSession, run_id: UUID, novel_id: UUID):
    await require_active_project(db, str(novel_id))
    run = await service.require_run(db, str(novel_id), str(run_id), lock=True)
    if run.status in {"pending", "running"} and run.task_id is None:
        run.status = "cancelled"
        record_run_event(run, "cancelled")
        await db.flush()
    if run.status in {"pending", "running"} and run.task_id:
        try:
            await cancel_exact_task(
                db,
                task_id=str(run.task_id),
                novel_id=str(novel_id),
                task_types={"assistant_turn"},
                transition_reason="assistant_user_stop",
            )
        except ValueError as exc:
            raise NotFoundError("助手任务不存在") from exc
        run.status = "cancelled"
        await db.flush()
    if run.status == "cancelled":
        run.checkpoint_json = {
            key: value
            for key, value in (run.checkpoint_json or {}).items()
            if key != "model_history"
        }
        await db.flush()
    return service.view(run)


@router.post("/batches/{batch_id}/decide")
async def approve_batch(db: DbSession, batch_id: UUID, data: BatchDecision):
    await require_active_project(db, str(data.novel_id))
    return await decide_batch(db, str(batch_id), data, str(current_account_id()))


@router.post("/batches/{batch_id}/recheck", response_model=RunResponse, status_code=202)
async def recheck_batch(db: DbSession, batch_id: UUID, data: BatchRecheck):
    await require_active_project(db, str(data.novel_id))
    return await service.recheck_batch(db, str(batch_id), data, str(current_account_id()))


@router.post("/runs/{run_id}/resume", status_code=202, response_model=RunResponse)
async def resume_run(db: DbSession, run_id: UUID, data: RunResume):
    await require_active_project(db, str(data.novel_id))
    return await service.resume(db, str(run_id), data, str(current_account_id()))


@router.get("/policy")
async def get_policy(db: DbSession, novel_id: UUID):
    await require_active_project(db, str(novel_id))
    from modules.assistant.proactive import policy

    return await policy(db, str(novel_id))


@router.put("/policy")
async def update_policy(db: DbSession, data: ProactivePolicyUpdate):
    await require_active_project(db, str(data.novel_id))
    from modules.assistant.proactive import save_policy

    return await save_policy(db, str(data.novel_id), data.policy)


@router.get("/notices")
async def get_notices(db: DbSession, novel_id: UUID):
    await require_active_project(db, str(novel_id))
    from modules.assistant.proactive import list_notices

    return await list_notices(db, str(novel_id))


@router.post("/notices/{notice_id}/decide")
async def update_notice(db: DbSession, notice_id: UUID, data: NoticeDecision):
    await require_active_project(db, str(data.novel_id))
    from modules.assistant.proactive import decide_notice

    return await decide_notice(db, str(notice_id), data)
