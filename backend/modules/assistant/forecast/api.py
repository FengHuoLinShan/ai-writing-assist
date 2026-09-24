"""Author forecast endpoints, separate from journey-scoped RP authorization."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from core.config import get_settings
from core.dependencies import DbSession
from core.errors import NotFoundError
from modules.assistant.forecast import policy, runtime, service
from modules.assistant.forecast.context import authorize
from modules.assistant.forecast.contracts import (
    CapabilitiesResponse,
    CapabilityView,
    DecisionRequest,
    EvaluateRequest,
    FeedRequest,
    FocusRequest,
    Horizon,
    OperationRequest,
    OperationView,
    PolicyUpdate,
    PrepareRequest,
    RunView,
    UsageView,
)
from modules.assistant.forecast.models import ForecastCandidate
from modules.assistant.forecast.registry import CAPABILITIES, SEMANTIC, rollout_available
from modules.assistant.models import AssistantRun
from modules.project.contracts import ProjectLLMConfigurationError
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.writing.facade import get_latest_draft_for_chapter


async def _guard_author(db: DbSession, novel_id: UUID):
    await require_active_project(db, str(novel_id))


router = APIRouter(
    prefix="/forecasts", tags=["forecasts"], dependencies=[Depends(_guard_author)]
)


@router.post("/candidates/{candidate_id}/prepare")
async def prepare(
    db: DbSession, novel_id: UUID, candidate_id: UUID, data: PrepareRequest
):
    from modules.assistant.forecast.preparation import prepare as prepare_choice

    return await prepare_choice(db, str(novel_id), candidate_id, data)


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities(db: DbSession, novel_id: UUID):
    await authorize(db, str(novel_id))
    settings = get_settings()
    try:
        await build_project_llm_execution_snapshot(
            db, str(novel_id), agent_executor=True
        )
        model_ready = True
    except ProjectLLMConfigurationError:
        model_ready = False
    enabled = settings.assistant_enabled and settings.assistant_forecast_enabled
    return CapabilitiesResponse(
        items=[
            CapabilityView(
                capability_id=key,
                compute_kind="semantic" if key in SEMANTIC else "deterministic",
                available=enabled
                and rollout_available(novel_id, key)
                and (
                    key not in SEMANTIC
                    or (model_ready and settings.assistant_forecast_semantic_enabled)
                ),
                reason="前瞻辅助尚未开启"
                if not enabled
                else "模型未连接或语义前瞻尚未开启"
                if key in SEMANTIC
                and not (model_ready and settings.assistant_forecast_semantic_enabled)
                else "该能力尚未向本作品开放或已暂停"
                if not rollout_available(novel_id, key)
                else None,
            )
            for key in CAPABILITIES
            if not key.startswith("interaction.")
        ]
    )


@router.get("/policy")
async def read_policy(db: DbSession, novel_id: UUID):
    await authorize(db, str(novel_id))
    return await policy.read_policy(db, str(novel_id))


@router.put("/policy")
async def save_policy(db: DbSession, novel_id: UUID, data: PolicyUpdate):
    project = await authorize(db, str(novel_id))
    return await policy.save_policy(db, str(novel_id), project.owner_id, data)


@router.post("/feed")
async def feed(db: DbSession, novel_id: UUID, data: FeedRequest):
    return await service.feed(db, str(novel_id), data)


@router.post("/evaluate", status_code=202)
async def evaluate(db: DbSession, novel_id: UUID, data: EvaluateRequest):
    return await runtime.submit(db, str(novel_id), data)


@router.get("/runs/{run_id}")
async def get_run(db: DbSession, novel_id: UUID, run_id: UUID):
    return await runtime.view(db, str(novel_id), run_id)


@router.post("/runs/{run_id}/cancel")
async def cancel(db: DbSession, novel_id: UUID, run_id: UUID):
    return await runtime.cancel(db, str(novel_id), run_id)


@router.get("/candidates/{candidate_id}")
async def get_candidate(db: DbSession, novel_id: UUID, candidate_id: UUID):
    candidate, _ = await service.require_candidate(db, str(novel_id), candidate_id)
    return service.candidate_view(candidate, await service._notice(db, candidate))


@router.post("/candidates/{candidate_id}/decision")
async def decide(
    db: DbSession, novel_id: UUID, candidate_id: UUID, data: DecisionRequest
):
    return await service.decide(db, str(novel_id), candidate_id, data)


@router.post("/candidates/{candidate_id}/recheck", status_code=202)
async def recheck(
    db: DbSession, novel_id: UUID, candidate_id: UUID, data: OperationRequest
):
    await authorize(db, str(novel_id))
    candidate = await db.scalar(
        select(ForecastCandidate).where(
            ForecastCandidate.novel_id == novel_id, ForecastCandidate.id == candidate_id
        )
    )
    if candidate is None:
        raise NotFoundError("前瞻结果不可访问")
    run = await runtime.require_run(db, str(novel_id), candidate.run_id)
    focus = FocusRequest.model_validate(run.request_json["context"])
    if run.request_json.get("chapter_index"):
        current = await get_latest_draft_for_chapter(
            db, str(novel_id), run.request_json["chapter_index"]
        )
        if current is None:
            raise NotFoundError("当前正文不可访问")
        focus = focus.model_copy(
            update={
                "draft_id": UUID(current.id),
                "expected_source_hash": current.content_hash,
                "selected_range": None,
            }
        )
    return await runtime.submit(
        db,
        str(novel_id),
        EvaluateRequest(
            operation_id=data.operation_id,
            context=focus,
            horizon=Horizon.model_validate(run.request_json["horizon"]),
            requested_capabilities=run.request_json["selected_capabilities"],
        ),
    )


@router.get("/operations/{operation_id}", response_model=OperationView)
async def get_operation(db: DbSession, novel_id: UUID, operation_id: UUID):
    await authorize(db, str(novel_id))
    run = await db.scalar(
        select(AssistantRun).where(
            AssistantRun.novel_id == novel_id, AssistantRun.operation_id == operation_id
        )
    )
    if run is None:
        raise NotFoundError("此操作尚无执行记录")
    if run.request_json.get("forecast_parent"):
        from modules.assistant.forecast.preparation import receipt

        preparation = await receipt(db, str(novel_id), run)
        return {
            "operation_id": operation_id,
            "kind": "prepare",
            "preparation": preparation,
            "run": RunView(
                run_id=run.id,
                task_id=run.task_id,
                status=run.status,
                phase="done",
                completion="complete"
                if preparation.status == "preview_ready"
                else "not_run",
                usage=UsageView(
                    requests=0, input_tokens=0, output_tokens=0, usage_complete=True
                ),
                error_code="SOURCE_STALE" if preparation.status == "stale" else None,
            ),
        }
    return {
        "operation_id": str(operation_id),
        "kind": "evaluate",
        "run": await runtime.view(db, str(novel_id), run.id),
    }


@router.post("/runs/{run_id}/revisit", status_code=202)
async def revisit(db: DbSession, novel_id: UUID, run_id: UUID, data: EvaluateRequest):
    await runtime.require_run(db, str(novel_id), run_id)
    return await runtime.submit(
        db,
        str(novel_id),
        data.model_copy(
            update={
                "context": data.context.model_copy(
                    update={"prior_forecast_run_id": run_id}
                ),
            }
        ),
    )


@router.post("/runs/{run_id}/resume")
async def resume_run(db: DbSession, novel_id: UUID, run_id: UUID):
    return await runtime.resume(db, str(novel_id), run_id)


@router.post("/activity")
async def activity(db: DbSession, novel_id: UUID, data: FocusRequest):
    from modules.assistant.forecast.context import materialize
    from modules.assistant.forecast.wake import evaluate_conditions

    ctx = await materialize(db, str(novel_id), data)
    return await evaluate_conditions(db, str(novel_id), ctx.focus)


@router.get("/diagnostics")
async def diagnostics(db: DbSession, novel_id: UUID):
    from modules.assistant.forecast.maintenance import diagnostics as inspect

    await authorize(db, str(novel_id))
    return await inspect(db, str(novel_id))
