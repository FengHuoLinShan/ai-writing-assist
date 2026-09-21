"""Journey-only forecast routes: the server resolves the private consumer project."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from core.config import get_settings
from core.csrf import require_xhr_request
from core.dependencies import DbSession
from core.errors import ConflictError
from modules.assistant.contracts import (
    DecisionRequest,
    EvaluateRequest,
    FeedRequest,
    FocusRequest,
    Horizon,
)
from modules.assistant.facade import (
    forecast_cancel,
    forecast_candidate,
    forecast_decide,
    forecast_feed,
    forecast_run,
    forecast_submit,
)
from modules.interaction.forecast import require_personal
from modules.interaction.services import InteractionService

router = APIRouter(
    prefix="/api/interactions/journeys/{journey_id}/forecasts",
    tags=["interaction"],
    dependencies=[Depends(require_xhr_request)],
)


class PlayerFocus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_context_id: UUID
    focus_seq: int = Field(ge=0)
    selected_leaf_node_id: UUID
    selection_epoch: int = Field(ge=0)
    source_context_epoch: int = Field(ge=0)
    overview_epoch: int = Field(ge=0)
    explicit_instruction: str = Field(default="", max_length=2000)

    def focus(self, journey_id):
        return FocusRequest(
            **self.model_dump(),
            page="interaction",
            journey_id=journey_id,
            task_hint="roleplay",
        )


class PlayerFeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context: PlayerFocus
    include_deferred: bool = False


class PlayerEvaluate(PlayerFeed):
    operation_id: UUID


class PrefillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction_id: str = Field(min_length=1, max_length=40)
    expected_assessment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


async def consumer(db, journey_id):
    require_personal()
    journey = await InteractionService()._owned_journey(db, str(journey_id))
    return str(journey.novel_id)


@router.get("/capabilities")
async def capabilities(db: DbSession, journey_id: UUID):
    await consumer(db, journey_id)
    settings = get_settings()
    return {
        "enabled": settings.assistant_enabled
        and settings.assistant_forecast_enabled
        and settings.interaction_forecast_enabled,
        "semantic_enabled": settings.assistant_forecast_semantic_enabled,
    }


@router.post("/feed")
async def feed(db: DbSession, journey_id: UUID, data: PlayerFeed):
    return await forecast_feed(
        db,
        await consumer(db, journey_id),
        FeedRequest(
            context=data.context.focus(journey_id), include_deferred=data.include_deferred
        ),
        persona="rp",
    )


@router.post("/evaluate", status_code=202)
async def evaluate(db: DbSession, journey_id: UUID, data: PlayerEvaluate):
    return await forecast_submit(
        db,
        await consumer(db, journey_id),
        EvaluateRequest(
            operation_id=data.operation_id,
            context=data.context.focus(journey_id),
            horizon=Horizon(unit="interaction_beat"),
        ),
        persona="rp",
    )


@router.get("/runs/{run_id}")
async def run(db: DbSession, journey_id: UUID, run_id: UUID):
    return await forecast_run(db, await consumer(db, journey_id), run_id, persona="rp")


@router.post("/runs/{run_id}/cancel")
async def cancel(db: DbSession, journey_id: UUID, run_id: UUID):
    return await forecast_cancel(db, await consumer(db, journey_id), run_id, persona="rp")


@router.post("/candidates/{candidate_id}/decision")
async def decide(
    db: DbSession, journey_id: UUID, candidate_id: UUID, data: DecisionRequest
):
    return await forecast_decide(
        db, await consumer(db, journey_id), candidate_id, data, persona="rp"
    )


@router.post("/candidates/{candidate_id}/prefill")
async def prefill(
    db: DbSession, journey_id: UUID, candidate_id: UUID, data: PrefillRequest
):
    candidate, _ = await forecast_candidate(
        db, await consumer(db, journey_id), candidate_id, persona="rp"
    )
    if candidate.assessment_hash != data.expected_assessment_hash:
        raise ConflictError("建议已变化，请重新查看")
    direction = next(
        (
            value
            for value in candidate.payload_json["proposal"].get("directions", [])
            if value["direction_id"] == data.direction_id
        ),
        None,
    )
    if direction is None:
        raise ConflictError("该方向不属于当前建议")
    return {"text": direction["proposal"], "input_kind": "action", "sent": False}


@router.get("/operations/{operation_id}")
async def operation(db: DbSession, journey_id: UUID, operation_id: UUID):
    return await forecast_run(
        db, await consumer(db, journey_id), operation_id, persona="rp"
    )


@router.post("/runs/{run_id}/resume")
async def resume(db: DbSession, journey_id: UUID, run_id: UUID):
    from modules.assistant.facade import forecast_resume

    return await forecast_resume(db, await consumer(db, journey_id), run_id, persona="rp")
