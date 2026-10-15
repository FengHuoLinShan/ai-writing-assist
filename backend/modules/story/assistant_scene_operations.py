"""Scene ordering and split/merge operations through Story's workbench service."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from core.container import get
from core.errors import ConflictError, ValidationError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from infrastructure.stable_hash import stable_hash
from modules.story.outline_state.models import Scene
from modules.story.outline_state.scene_workbench import SceneWorkbenchService
from modules.story.outline_state.schemas import (
    SceneMergeRequest,
    SceneReorderRequest,
    SceneSplitRequest,
)
from modules.story.outline_state.services import SceneService


class ReorderScenes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_ids: list[UUID] = Field(min_length=1, max_length=200)


class MergeScenes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_scene_id: UUID
    source_scene_ids: list[UUID] = Field(min_length=1, max_length=20)


class SplitScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_scene_id: UUID
    split_chapter_index: int = Field(ge=1)
    split_pos: int | None = Field(default=None, ge=1)
    new_scene_title: str | None = Field(default=None, max_length=255)
    new_scene_status: Literal["draft", "canonical"] = "draft"


async def _require_scene_scope(db, novel_id, context, scene_ids, *, aggregate=False):
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db,
        novel_id,
        context,
        [("outline_scene", scene_id) for scene_id in scene_ids],
        aggregate=aggregate,
    )


async def _lock_scenes(db, novel_id, scene_ids):
    ids = sorted({UUID(str(value)) for value in scene_ids}, key=str)
    rows = list(
        (
            await db.scalars(
                select(Scene)
                .where(Scene.novel_id == UUID(str(novel_id)), Scene.id.in_(ids))
                .order_by(Scene.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(rows) != len(ids):
        raise ConflictError("Scene 不存在或已移出当前作品，请重新准备")


async def _scene_order_state(db, novel_id, scene_ids, context):
    scenes = await SceneService().get_ordered(db, novel_id)
    active_ids = {UUID(item.id) for item in scenes}
    ids = list(scene_ids)
    if len(set(ids)) != len(ids) or set(ids) != active_ids:
        raise ValidationError("排序必须完整包含当前作品的每个有效 Scene，且不能重复")
    await _require_scene_scope(db, novel_id, context, active_ids, aggregate=True)
    by_id = {UUID(item.id): item for item in scenes}
    return [asdict(item) for item in scenes], [
        asdict(by_id[scene_id]) for scene_id in ids
    ]


async def _reorder_preview(db, novel_id, args, *, context=None):
    current, ordered_after = await _scene_order_state(
        db, novel_id, args.scene_ids, context
    )
    from_scene_order = [
        {"id": item["id"], "scene_index": item["scene_index"], "title": item["title"]}
        for item in current
    ]
    return {
        "target_key": "story:scene_order",
        "title": "调整 Scene 顺序",
        "before": from_scene_order,
        "after": [
            {"id": item["id"], "scene_index": index, "title": item["title"]}
            for index, item in enumerate(ordered_after)
        ],
        "baseline_fingerprint": stable_hash(current),
        "effect": "只重排现有 Scene；Story 服务会同步更新依赖与演化失效状态",
    }


async def _reorder_apply(db, novel_id, args, preview, *, context=None):
    await _lock_scenes(db, novel_id, args.scene_ids)
    if await _reorder_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("Scene 内容或顺序已变化，请重新准备")
    result = await SceneWorkbenchService().reorder_scenes(
        db,
        novel_id,
        SceneReorderRequest(scene_ids=[str(value) for value in args.scene_ids]).scene_ids,
    )
    return {
        "type": "outline_scene_order",
        "id": str(UUID(str(novel_id))),
        "label": "Scene 顺序已更新",
        "updated": result["updated"],
        "total": result["total"],
    }


def _merge_request(args: MergeScenes, *, confirmed: bool = False) -> SceneMergeRequest:
    return SceneMergeRequest(
        target_scene_id=str(args.target_scene_id),
        source_scene_ids=[str(value) for value in args.source_scene_ids],
        confirmed=confirmed,
    )


async def _merge_preview(db, novel_id, args, *, context=None):
    if len(set(args.source_scene_ids)) != len(args.source_scene_ids):
        raise ValidationError("来源 Scene 不能重复")
    if args.target_scene_id in args.source_scene_ids:
        raise ValidationError("目标 Scene 不能同时作为来源 Scene")
    await _require_scene_scope(
        db,
        novel_id,
        context,
        [args.target_scene_id, *args.source_scene_ids],
        aggregate=True,
    )
    result = await SceneWorkbenchService().preview_merge(
        db, novel_id, _merge_request(args)
    )
    return {
        "target_key": f"outline_scene:{args.target_scene_id}",
        "title": "合并 Scene",
        "impact": result.model_dump(mode="json"),
        "effect": (
            "保留目标 Scene 并按领域规则归并章节和字段；来源 Scene 将被标记为已合并"
        ),
    }


async def _merge_apply(db, novel_id, args, preview, *, context=None):
    await _lock_scenes(db, novel_id, [args.target_scene_id, *args.source_scene_ids])
    if await _merge_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("合并范围或 Scene 基线已变化，请重新准备")
    result = await SceneWorkbenchService().merge(
        db, novel_id, _merge_request(args, confirmed=True)
    )
    return {
        "type": "outline_scene",
        "id": result.scene.id,
        "label": "Scene 已合并",
        "source_scene_ids": [str(value) for value in args.source_scene_ids],
    }


def _split_request(args: SplitScene, *, confirmed: bool = False) -> SceneSplitRequest:
    return SceneSplitRequest(
        source_scene_id=str(args.source_scene_id),
        split_chapter_index=args.split_chapter_index,
        split_pos=args.split_pos,
        new_scene_title=args.new_scene_title,
        new_scene_status=args.new_scene_status,
        confirmed=confirmed,
    )


async def _split_preview(db, novel_id, args, *, context=None):
    await _require_scene_scope(
        db, novel_id, context, [args.source_scene_id], aggregate=True
    )
    result = await SceneWorkbenchService().preview_split(
        db, novel_id, _split_request(args)
    )
    impact = result.model_dump(mode="json")
    new_scene = impact.get("new_scene")
    if isinstance(new_scene, dict) and isinstance(new_scene.get("structure_meta"), dict):
        # The domain preview stamps this proposed, not-yet-persisted scene with
        # a fresh adopted_at value on every read. It is not author-visible
        # impact and must not make prepare/apply CAS impossible.
        new_scene["structure_meta"].pop("adopted_at", None)
    for draft in impact.get("draft_scenes") or []:
        metadata = draft.get("structure_meta") if isinstance(draft, dict) else None
        if isinstance(metadata, dict):
            metadata.pop("adopted_at", None)
    return {
        "target_key": f"outline_scene:{args.source_scene_id}",
        "title": "拆分 Scene",
        "impact": impact,
        "effect": (
            "只调整 Scene 与章节/正文片段的映射，不改写正文；新 Scene 按预览中的状态创建"
        ),
    }


async def _split_apply(db, novel_id, args, preview, *, context=None):
    await _lock_scenes(db, novel_id, [args.source_scene_id])
    if await _split_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("拆分范围或 Scene 基线已变化，请重新准备")
    result = await SceneWorkbenchService().split(
        db, novel_id, _split_request(args, confirmed=True)
    )
    return {
        "type": "outline_scene",
        "id": result.scene.id,
        "new_scene_id": result.new_scene.id if result.new_scene else None,
        "label": "Scene 已拆分",
    }


OPERATIONS_SPEC = {
    "story.scene.reorder": {
        "label": "调整 Scene 顺序",
        "schema": ReorderScenes,
        "prepare": _reorder_preview,
        "apply": _reorder_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "按作者给出的完整顺序重排当前作品的 Scene，并保留 Story 服务的失效处理。"
        ),
        "risk_level": "R2",
        "fee_category": "free",
        "reversibility": "reorder_again",
        "preconditions": (
            "scene_ids 包含当前作品全部有效 Scene，且各 Scene 属于当前范围",
        ),
        "produces": ("outline_scene_order",),
        "target_type": "outline_scene_group",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("scene_ids",),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "story.scene.merge": {
        "label": "合并 Scene",
        "schema": MergeScenes,
        "prepare": _merge_preview,
        "apply": _merge_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "通过 Scene 工作台合并选定来源到目标 Scene；来源的归档与映射按领域规则处理。"
        ),
        "risk_level": "R3",
        "fee_category": "free",
        "reversibility": "scene_workbench_merge_history",
        "preconditions": ("目标和来源 Scene 属于当前作品", "Scene 影响预览仍然有效"),
        "produces": ("outline_scene_merge_receipt",),
        "target_type": "outline_scene_group",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("target_scene_id", "source_scene_ids"),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "story.scene.split": {
        "label": "拆分 Scene",
        "schema": SplitScene,
        "prepare": _split_preview,
        "apply": _split_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "按章节或正文偏移拆分 Scene，不改写正文；新 Scene 的状态由作者确认。"
        ),
        "risk_level": "R3",
        "fee_category": "free",
        "reversibility": "scene_workbench_split_history",
        "preconditions": ("来源 Scene 和拆分边界仍属于当前作品", "拆分预览没有来源冲突"),
        "produces": ("outline_scene_split_receipt",),
        "target_type": "outline_scene",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": (
                "source_scene_id",
                "split_chapter_index",
                "split_pos",
                "new_scene_title",
                "new_scene_status",
            ),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
}
