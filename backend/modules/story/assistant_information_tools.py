"""Edit existing information plans through their original domain validation."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from modules.assistant.contracts import AssistantOperation
from modules.assistant.facade import require_operation_targets
from modules.story.outline_state.models import ForeshadowingPlan, RevealPlan
from modules.story.outline_state.schemas import ForeshadowingPlanUpdate, RevealPlanUpdate
from modules.story.outline_state.services import (
    ForeshadowingPlanService,
    RevealPlanService,
)
from modules.story.service import _hash_payload

KINDS = {
    "foreshadowing_plan": (
        ForeshadowingPlan,
        ForeshadowingPlanUpdate,
        ForeshadowingPlanService,
    ),
    "reveal_plan": (RevealPlan, RevealPlanUpdate, RevealPlanService),
}


class EditInformationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["foreshadowing_plan", "reveal_plan"]
    plan_id: UUID
    changes: dict = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_changes(self):
        model, schema, _ = KINDS[self.kind]
        allowed = set(schema.model_fields) - {
            "novel_id",
            "provenance_meta",
            "related_entity_ids",
            "target_id",
            "target_type",
        }
        if set(self.changes) - allowed:
            raise ValueError(
                "此工具只修改计划内容、章节和关联剧情线；目标对象请从结构工作台调整"
            )
        self.changes = schema.model_validate(self.changes).model_dump(
            mode="json", exclude_unset=True
        )
        if "status" in self.changes:
            allowed_statuses = (
                {
                    "draft",
                    "planned",
                    "seeded",
                    "planted",
                    "reinforced",
                    "triggered",
                    "paid_off",
                    "resolved",
                    "abandoned",
                    "deprecated",
                }
                if self.kind == "foreshadowing_plan"
                else {"draft", "planned", "revealed", "resolved", "deprecated"}
            )
            if self.changes["status"] not in allowed_statuses:
                raise ValueError("请选择已有的计划状态")
        for key, value in self.changes.items():
            if value is None and not model.__table__.columns[key].nullable:
                raise ValueError("计划名称、目标和状态等必填内容不能清空")
        return self


async def inspect_information_plan(db, novel_id, kind, plan_id):
    if kind not in KINDS:
        raise NotFoundError("信息计划类型不可用")
    row = await KINDS[kind][2]().get(db, plan_id, novel_id=novel_id)
    return row.model_dump(mode="json")


async def _preview(db, novel_id, args, *, context=None):
    await require_operation_targets(
        db, novel_id, context, [(args.kind, args.plan_id)], aggregate=True
    )
    before = await inspect_information_plan(db, novel_id, args.kind, str(args.plan_id))
    baseline = dict(before)
    for key in ("created_at", "updated_at"):
        if baseline.get(key):
            value = datetime.fromisoformat(baseline[key])
            baseline[key] = (
                value.replace(tzinfo=UTC)
                if value.tzinfo is None
                else value.astimezone(UTC)
            ).isoformat()
    return {
        "title": "修改信息计划",
        "target_key": f"{args.kind}:{args.plan_id}",
        "before": {key: before.get(key) for key in args.changes},
        "after": args.changes,
        "baseline_hash": _hash_payload(baseline),
        "effect": "更新伏笔或揭示安排，保留来源与关联校验；计划不等于已发生的故事",
    }


async def _apply(db, novel_id, args, preview, *, context=None):
    model, schema, service = KINDS[args.kind]
    row = await db.scalar(
        select(model)
        .where(model.novel_id == UUID(novel_id), model.id == args.plan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise NotFoundError("信息计划不存在")
    if await _preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("计划内容已变化，请重新查看修改方案")
    result = await service().update(
        db, str(args.plan_id), schema.model_validate(args.changes), novel_id=novel_id
    )
    return {"type": args.kind, "id": str(result.id), "label": "信息计划已更新"}


OPERATIONS = {
    "story.edit_information_plan": AssistantOperation(
        "修改伏笔与揭示安排", EditInformationPlan, _preview, _apply
    )
}
