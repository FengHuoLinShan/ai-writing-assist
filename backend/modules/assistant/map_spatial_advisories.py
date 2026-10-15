"""Explain World reminders and silence one unchanged item without changing its truth."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import RunContext
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from core.config import get_settings
from core.container import get
from core.errors import ConflictError, DomainError
from core.service_keys import (
    ASSISTANT_REQUIRE_OPERATION_TARGETS,
    WORLD_READ_MAP_SPATIAL_ADVISORIES,
)
from infrastructure.llm.workflow_budget import budgeted_tool
from infrastructure.stable_hash import stable_hash
from modules.assistant.evidence_tools import (
    AssistantToolContext,
    fixed_reference_context,
)
from modules.assistant.models import AssistantNotice
from modules.evidence.facade import prepare_confirmed_ai_action


async def _read(db, novel_id, work):
    if "assistant.turn" not in get_settings().map_spatial_enabled_capabilities:
        return None
    if work.scene_id is None:
        return None
    return await get(WORLD_READ_MAP_SPATIAL_ADVISORIES)(
        db,
        {
            "novel_id": novel_id,
            "scene_id": str(work.scene_id),
            "reveal_mode": "author_safe",
            "excluded_ids": list(work.excluded_targets),
        },
    )


def _identity(scene_id, item):
    return stable_hash({"scene_id": scene_id, "item": item})


def _allowed_revisions(fixed_context):
    if fixed_context is None:
        return None
    return {
        (str(item.get("node_id") or item.get("id")), str(item.get("revision_id")))
        for item in (fixed_context.get("map_spatial") or {}).get("items", [])
    }


@budgeted_tool
async def map_spatial_advisories(ctx: RunContext[AssistantToolContext]) -> dict:
    """解释当前场景的空间提醒；给出正文候选、地图预览和逐项静默入口。"""
    deps = ctx.deps
    await deps.guard()
    try:
        async with deps.db.begin_nested():
            result = await _read(deps.db, deps.novel_id, deps.work)
    except (DomainError, SQLAlchemyError):
        return {
            "status": "unknown",
            "items": [],
            "degraded": True,
            "reason": "空间参考暂不可读取，请到地图工作台核对；不影响正文工作",
        }
    if result is None:
        return {"status": "unknown", "items": [], "reason": "当前没有可核验的场景位置"}
    allowed = _allowed_revisions(deps.fixed_context)
    rows = [
        item
        for item in result.items
        if allowed is None or (str(item.node_id), str(item.revision_id)) in allowed
    ]
    raw = [item.model_dump(mode="json") for item in rows]
    keys = {_identity(result.scene_id, item) for item in raw}
    dismissed = (
        set(
            (
                await deps.db.scalars(
                    select(AssistantNotice.fingerprint).where(
                        AssistantNotice.novel_id == UUID(deps.novel_id),
                        AssistantNotice.fingerprint.in_(keys),
                        AssistantNotice.status == "dismissed",
                    )
                )
            ).all()
        )
        if keys
        else set()
    )
    items = []
    for item in raw:
        identity = _identity(result.scene_id, item)
        if identity in dismissed:
            continue
        saved = deps.remember(
            {
                "title": "空间提醒",
                "snippet": item["summary"],
                "target_ref": {
                    "target_type": "map_spatial",
                    "target_id": item["node_id"],
                },
                "spatial_advisory": item,
                "advisory_fingerprint": identity,
            }
        )
        if saved is None:
            continue
        items.append(
            {
                **saved,
                "repair_paths": [
                    {
                        "page": "writing",
                        "capability": "writing.generate_candidate",
                        "targeted_capability": "writing.targeted_revision",
                        "requires_original_review_for_targeted_revision": True,
                        "effect": "另存正文候选，沿用Writing的资料确认、审稿与采用入口",
                    },
                    {
                        "page": "map",
                        "capability": "map.edit_spatial_structure",
                        "node_id": item["node_id"],
                        "base_revision_id": item["revision_id"],
                        "effect": "准备整个空间版本的修改预览，作者确认后保存",
                    },
                ],
                "silence": {
                    "capability": "assistant.silence_spatial_advisory",
                    "arguments": {"fingerprint": identity},
                },
            }
        )
    await deps.db.commit()
    covered = [
        entry.model_dump(mode="json")
        for entry in result.map_revisions
        if allowed is None or (str(entry.node_id), str(entry.revision_id)) in allowed
    ]
    unknowns = list(result.unknowns)
    if not covered:
        unknowns.append("本次确认没有可核对的地图版本，未判断空间是否一致。")
    return {
        "status": "known" if items else "unknown" if unknowns else "clear",
        "items": items,
        "unknowns": unknowns,
        "omitted_count": result.omitted_count,
        "map_revisions": covered,
        "silenced_count": len(dismissed),
        "authority": "只作提醒，不拦截写作",
    }


class SilenceSpatialAdvisory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


async def _silence_preview(db, novel_id, args, *, context=None):
    if context is None:
        raise ConflictError("静默提醒需要当前助手的场景范围")
    allowed = None
    if context.work.context_confirmation_id:
        prepared = await prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action=context.work.context_confirmation_action,
            confirmation_id=str(context.work.context_confirmation_id),
        )
        allowed = _allowed_revisions(fixed_reference_context(prepared))
    result = await _read(db, novel_id, context.work)
    if result is None:
        raise ConflictError("当前没有可核验的空间提醒")
    for item in result.items:
        value = item.model_dump(mode="json")
        if _identity(result.scene_id, value) == args.fingerprint:
            if (
                allowed is not None
                and (str(item.node_id), str(item.revision_id)) not in allowed
            ):
                raise ConflictError("该地图版本不在当前确认范围中，请重新选择资料")
            await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
                db, novel_id, context, [("map_atlas_node", item.node_id)]
            )
            return {
                "target_key": "spatial-advisory:" + args.fingerprint,
                "scene_id": result.scene_id,
                "item": value,
                "effect": "只静默这一条当前版本的提醒，不修改地图或领域结论",
            }
    raise ConflictError("提醒或地图版本已变化，请重新读取")


async def _silence_apply(db, novel_id, args, preview, *, context=None):
    if await _silence_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("提醒已变化，请重新确认")
    row = await db.scalar(
        select(AssistantNotice).where(
            AssistantNotice.novel_id == UUID(novel_id),
            AssistantNotice.fingerprint == args.fingerprint,
        )
    )
    if row is None:
        row = AssistantNotice(
            novel_id=UUID(novel_id),
            fingerprint=args.fingerprint,
            title="空间提醒",
            summary=preview["item"]["summary"],
            result_ref_json={
                "scene_id": preview["scene_id"],
                "spatial_advisory": preview["item"],
            },
        )
        db.add(row)
    row.status = "dismissed"
    row.disposition = "ignore"
    await db.flush()
    return {"type": "assistant_notice", "id": str(row.id), "status": "dismissed"}


OPERATIONS_SPEC = {
    "assistant.silence_spatial_advisory": {
        "label": "静默这一条空间提醒",
        "schema": SilenceSpatialAdvisory,
        "prepare": _silence_preview,
        "apply": _silence_apply,
    }
}
