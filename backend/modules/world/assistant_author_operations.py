"""Author-confirmed, revision-aware World operations for A1."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.world.entity_fusion import WorldEntityFusionService
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.models import (
    CoreEntity,
    EntityRevision,
    WorldBiblePage,
    WorldBiblePageRevision,
)
from modules.world.revision_history_schemas import RevisionTargetKind
from modules.world.schemas import CoreEntityUpdate, EntityFusionApplyItem
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.revision_notes import (
    load_revision_notes,
    set_revision_note,
)


class TransitionEntityType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: UUID
    new_type: str = Field(min_length=1, max_length=64)

    @field_validator("new_type")
    @classmethod
    def normalize_new_type(cls, value: str) -> str:
        return CoreEntityUpdate(entity_type=value).entity_type


class FusionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["merge", "alias_only"]
    source_entity_id: UUID
    target_entity_id: UUID
    alias: str | None = Field(default=None, max_length=255)


class ApplyEntityFusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestions: list[FusionDecision] = Field(min_length=1, max_length=20)


class SetRevisionNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_kind: RevisionTargetKind
    revision_id: UUID
    note: str = Field(max_length=500)


class RestoreEntityRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: UUID
    revision_id: UUID


async def _require_target(db, novel_id, context, kind, target_id):
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db, novel_id, context, [(kind, target_id)]
    )


async def _transition_preview(db, novel_id, args, *, context=None):
    await _require_target(db, novel_id, context, "core_entity", args.entity_id)
    entity = await WorldEntityService().get(db, str(args.entity_id), novel_id=novel_id)
    if entity.entity_type == args.new_type:
        raise ValidationError("对象已经属于该类型")
    return {
        "target_key": f"world_entity:{entity.id}",
        "title": entity.name,
        "before": {"entity_type": entity.entity_type},
        "after": {"entity_type": args.new_type},
        "updated_at": entity.updated_at.isoformat() if entity.updated_at else None,
        "effect": "调用对象类型迁移服务；专属数据或类型依赖冲突时保持不变",
    }


async def _transition_apply(db, novel_id, args, preview, *, context=None):
    if await _transition_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("对象类型或资料版本已变化，请重新准备")
    from datetime import datetime

    baseline = (
        datetime.fromisoformat(preview["updated_at"]) if preview["updated_at"] else None
    )
    entity = await WorldEntityService().update(
        db,
        str(args.entity_id),
        CoreEntityUpdate(entity_type=args.new_type),
        novel_id=novel_id,
        expected_updated_at=baseline,
        require_edit_baseline=True,
    )
    return {"type": "world_entity", "id": str(entity.id), "label": "对象类型已迁移"}


async def _fusion_rows(db, novel_id, args):
    decisions = args.suggestions
    source_ids = [item.source_entity_id for item in decisions]
    target_ids = [item.target_entity_id for item in decisions]
    participant_ids = [*source_ids, *target_ids]
    if len(set(participant_ids)) != len(participant_ids):
        raise ValidationError("每个对象只能出现在一条融合决定中")
    if any(
        source_id == target_id for source_id, target_id in zip(source_ids, target_ids)
    ):
        raise ValidationError("对象不能合并到自身")
    ids = list(dict.fromkeys([*source_ids, *target_ids]))
    rows = (
        await db.scalars(
            select(CoreEntity).where(
                CoreEntity.novel_id == UUID(str(novel_id)),
                CoreEntity.id.in_(ids),
            )
        )
    ).all()
    by_id = {row.id: row for row in rows}
    if len(by_id) != len(ids):
        raise NotFoundError("融合对象不存在或不属于当前作品")
    return by_id


async def _lock_fusion_entities(db, novel_id, args):
    ids = sorted(
        set(
            entity_id
            for item in args.suggestions
            for entity_id in (item.source_entity_id, item.target_entity_id)
        ),
        key=str,
    )
    rows = list(
        (
            await db.scalars(
                select(CoreEntity.id)
                .where(
                    CoreEntity.novel_id == UUID(str(novel_id)),
                    CoreEntity.id.in_(ids),
                )
                .order_by(CoreEntity.id)
                .with_for_update()
            )
        ).all()
    )
    if len(rows) != len(ids):
        raise NotFoundError("融合对象不存在或不属于当前作品")


async def _fusion_preview(db, novel_id, args, *, context=None):
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db,
        novel_id,
        context,
        [
            ("core_entity", entity_id)
            for item in args.suggestions
            for entity_id in (item.source_entity_id, item.target_entity_id)
        ],
        aggregate=True,
    )
    by_id = await _fusion_rows(db, novel_id, args)
    decisions = []
    for item in args.suggestions:
        source = by_id[item.source_entity_id]
        target = by_id[item.target_entity_id]
        if source.entity_type != target.entity_type:
            raise ValidationError("对象类型不同，不能直接融合")
        decisions.append(
            {
                "action": item.action,
                "source": {
                    "id": str(source.id),
                    "name": source.name,
                    "status": source.status,
                    "updated_at": source.updated_at.isoformat()
                    if source.updated_at
                    else None,
                },
                "target": {
                    "id": str(target.id),
                    "name": target.name,
                    "status": target.status,
                    "updated_at": target.updated_at.isoformat()
                    if target.updated_at
                    else None,
                },
                "alias": item.alias,
                "author_confirmation_required": source.status == "canonical"
                or target.status == "canonical",
            }
        )
    return {
        "target_key": "world_entity_fusion",
        "title": f"核对 {len(decisions)} 条对象融合决定",
        "decisions": decisions,
        "effect": "仅在作者确认后调用现有融合服务；来源保留为领域归档并返回融合回执",
    }


async def _fusion_apply(db, novel_id, args, preview, *, context=None):
    await _lock_fusion_entities(db, novel_id, args)
    if await _fusion_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("融合对象或基线已变化，请重新准备")
    suggestions = [
        EntityFusionApplyItem(
            action=item.action,
            source_entity_id=str(item.source_entity_id),
            target_entity_id=str(item.target_entity_id),
            alias=item.alias,
            # The operation's R3 confirmation is the explicit author decision.
            allow_canonical_merge=True,
            allow_canonical_alias=True,
        )
        for item in args.suggestions
    ]
    result = await WorldEntityFusionService().apply(
        db,
        novel_id=novel_id,
        confirmed=True,
        suggestions=suggestions,
    )
    affected_ids = sorted(
        {
            str(entity_id)
            for item in result["results"]
            for entity_id in (
                item.get("source_entity_id"),
                item.get("candidate_entity_id"),
                item.get("target_entity_id"),
                *(item.get("affected_ids") or []),
                *(item.get("merged_ids") or []),
            )
            if entity_id
        }
    )
    return {
        "type": "world_entity_fusion_result",
        "affected_entity_ids": affected_ids,
        "label": "对象融合已处理",
        "applied": result["applied"],
        "skipped": result["skipped"],
        "warning_count": len(result["warnings"]),
    }


_REVISION_MODELS = {
    "entity": (EntityRevision, CoreEntity, CoreEntity.id, "core_entity"),
    "page": (
        WorldBiblePageRevision,
        WorldBiblePage,
        WorldBiblePage.id,
        "world_bible_page",
    ),
    "map": (MapAtlasRevision, MapAtlasNode, MapAtlasNode.id, "map_atlas_node"),
}


async def _revision_note_state(db, novel_id, args, context, *, for_update=False):
    revision_model, target_model, target_id_column, target_kind = _REVISION_MODELS[
        args.target_kind
    ]
    statement = select(revision_model).where(
        revision_model.novel_id == UUID(str(novel_id)),
        revision_model.id == args.revision_id,
    )
    if for_update:
        statement = statement.with_for_update()
    revision = await db.scalar(statement)
    if revision is None:
        raise NotFoundError("修订不存在或不属于当前作品")
    if args.target_kind == "entity":
        target_id = revision.entity_id
    elif args.target_kind == "page":
        target_id = revision.page_id
    else:
        if revision.status != "saved":
            raise ConflictError("只有已保存的地图版本可以补写备注")
        target_id = revision.node_id
    await _require_target(db, novel_id, context, target_kind, target_id)
    target = await db.scalar(
        select(target_model).where(
            target_model.novel_id == UUID(str(novel_id)),
            target_id_column == target_id,
        )
    )
    if target is None:
        raise NotFoundError("修订目标不存在或不属于当前作品")
    notes = await load_revision_notes(db, novel_id, args.target_kind, [args.revision_id])
    return target, notes.get(args.revision_id)


async def _revision_note_preview(db, novel_id, args, *, context=None, for_update=False):
    _target, current = await _revision_note_state(
        db, novel_id, args, context, for_update=for_update
    )
    return {
        "target_key": f"{args.target_kind}_revision:{args.revision_id}",
        "title": "补写修订备注",
        "before": {"note": current},
        "after": {"note": args.note.strip() or None},
        "effect": "仅更新修订说明；修订记录本身不会被删除或改写",
    }


async def _revision_note_apply(db, novel_id, args, preview, *, context=None):
    if (
        await _revision_note_preview(db, novel_id, args, context=context, for_update=True)
        != preview
    ):
        raise ConflictError("修订备注或目标已变化，请重新准备")
    result = await set_revision_note(
        db,
        novel_id,
        args.target_kind,
        args.revision_id,
        args.note,
    )
    return {
        "type": f"{args.target_kind}_revision_note",
        "id": str(args.revision_id),
        "label": "修订备注已更新",
        "note": result.note,
    }


async def _restore_preview(db, novel_id, args, *, context=None):
    await _require_target(db, novel_id, context, "core_entity", args.entity_id)
    entity_service = WorldEntityService()
    entity = await entity_service.get(db, str(args.entity_id), novel_id=novel_id)
    revision = await db.scalar(
        select(EntityRevision).where(
            EntityRevision.id == args.revision_id,
            EntityRevision.novel_id == UUID(str(novel_id)),
            EntityRevision.entity_id == args.entity_id,
        )
    )
    if revision is None:
        raise NotFoundError("目标修订不存在或不属于该对象")
    snapshot = revision.snapshot or {}
    fields = (
        "entity_type",
        "name",
        "summary",
        "public_info",
        "hidden_truth",
        "content_json",
        "importance",
        "importance_level",
        "reveal_level",
    )
    changed = [field for field in fields if getattr(entity, field) != snapshot.get(field)]
    return {
        "target_key": f"world_entity:{entity.id}",
        "title": f"恢复 {entity.name} 的历史版本",
        "revision_id": str(args.revision_id),
        "base_updated_at": entity.updated_at.isoformat() if entity.updated_at else None,
        "revision_created_at": revision.created_at.isoformat()
        if revision.created_at
        else None,
        "changed_fields": changed,
        "effect": (
            "按指定历史修订恢复对象内容；保留当前采用状态和来源标记，"
            "并继续走正式更新与历史记录服务"
        ),
    }


async def _restore_apply(db, novel_id, args, preview, *, context=None):
    if await _restore_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("对象当前版本或目标历史已变化，请重新准备")
    from datetime import datetime

    result = await WorldEntityService().rollback_to_revision(
        db,
        str(args.entity_id),
        str(args.revision_id),
        novel_id=novel_id,
        expected_updated_at=(
            datetime.fromisoformat(preview["base_updated_at"])
            if preview["base_updated_at"]
            else None
        ),
    )
    return {"type": "world_entity", "id": str(result.id), "label": "对象已恢复到所选修订"}


OPERATIONS_SPEC = {
    "world.entity.transition_type": {
        "label": "迁移世界对象类型",
        "schema": TransitionEntityType,
        "prepare": _transition_preview,
        "apply": _transition_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "在保留对象身份的前提下迁移其类型与专属档案；存在未兼容依赖时由领域服务阻止。"
        ),
        "risk_level": "R3",
        "fee_category": "free",
        "reversibility": "history_restore",
        "preconditions": ("对象属于当前作品", "目标类型可由 World 领域服务迁移"),
        "produces": ("world_entity_revision",),
        "target_type": "world_entity",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("entity_id", "new_type"),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "world.entity.fuse": {
        "label": "融合已选世界对象",
        "schema": ApplyEntityFusion,
        "prepare": _fusion_preview,
        "apply": _fusion_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "按作者明确的来源对象、目标对象与动作调用既有融合服务；"
            "融合属于 R3，需要作者确认。"
        ),
        "risk_level": "R3",
        "fee_category": "free",
        "reversibility": "world_fusion_domain_receipt",
        "preconditions": ("来源与目标对象均属于当前作品", "同一融合批次的对象类型兼容"),
        "produces": ("world_entity_fusion_result",),
        "target_type": "world_entity_group",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("suggestions",),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "world.history.set_note": {
        "label": "补写世界修订备注",
        "schema": SetRevisionNote,
        "prepare": _revision_note_preview,
        "apply": _revision_note_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "为实体、世界书页或已保存地图修订补写备注；只改变备注，不触碰历史记录。"
        ),
        "risk_level": "R2",
        "fee_category": "free",
        "reversibility": "revision_note_editable",
        "preconditions": ("修订属于当前作品", "地图修订状态为已保存"),
        "produces": ("world_revision_note",),
        "target_type": "world_revision",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("target_kind", "revision_id", "note"),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "world.entity.restore_revision": {
        "label": "恢复对象历史修订",
        "schema": RestoreEntityRevision,
        "prepare": _restore_preview,
        "apply": _restore_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "恢复指定实体修订中的内容；保留当前采用状态和来源标记，"
            "并在执行时重验当前基线。"
        ),
        "risk_level": "R2",
        "fee_category": "free",
        "reversibility": "history_restore",
        "preconditions": ("历史修订属于指定实体和当前作品", "当前对象基线未变化"),
        "produces": ("world_entity_revision",),
        "target_type": "world_entity",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": ("entity_id", "revision_id"),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
}
