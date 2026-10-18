"""Version-bound relation maintenance with recoverable, idempotent receipts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.stable_hash import stable_hash
from modules.project.facade import require_active_project
from modules.world.models import CoreEntity
from modules.world.repositories import CoreEntityRepository, EntityRelationRepository
from modules.world.schemas import EntityRelationUpdate, RelationKind
from modules.world.schemas.dossier import DossierAnchor, DossierValidity
from modules.world.services.common import entity_relation_execution_fingerprint
from modules.world.services.core.entity_relation_service import EntityRelationService


class RelationEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, max_length=12000)
    relation_type: str | None = Field(default=None, min_length=1, max_length=64)
    relation_kind: RelationKind | None = None
    strength: float | None = Field(default=None, ge=0, le=1)
    validity: DossierValidity | None = None

    @model_serializer(mode="wrap")
    def supplied_fields(self, handler):
        # Operation roundtrips must distinguish omitted fields from explicit null.
        return {
            key: value
            for key, value in handler(self).items()
            if key in self.model_fields_set
        }


class RelationChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation_id: uuid.UUID
    action: Literal["edit", "end", "remove", "restore"]
    changes: RelationEdit | None = None
    end: DossierAnchor | None = None
    history_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def match_action(self):
        if self.action == "edit":
            if (
                not self.changes
                or not self.changes.model_fields_set
                or self.end
                or self.history_id
            ):
                raise ValueError("编辑关系需要具体修改，不能混合结束或恢复")
            if (
                self.changes.relation_type is None
                and "relation_type" in self.changes.model_fields_set
            ):
                raise ValueError("关系类型不能为空")
            if any(
                getattr(self.changes, field) is None
                for field in {"relation_kind", "strength"} & self.changes.model_fields_set
            ):
                raise ValueError("关系分类与强度不能为空")
        elif self.action == "end":
            if not self.end or self.changes or self.history_id:
                raise ValueError("结束有效期需要明确章节或场景锚点")
        elif self.action == "restore":
            if not self.history_id or self.changes or self.end:
                raise ValueError("恢复需要选择一条原修改记录")
        elif self.changes or self.end or self.history_id:
            raise ValueError("移除关系不能同时修改内容")
        return self


class RelationChangeConfirmed(RelationChange):
    operation_id: uuid.UUID
    expected_preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]


async def _row(db, novel_id, relation_id, *, lock=False):
    await require_active_project(db, novel_id)
    relation_id = uuid.UUID(str(relation_id))
    repo, nid = EntityRelationRepository(), uuid.UUID(str(novel_id))
    row = await repo.get(db, relation_id)
    if row is None or row.novel_id != nid:
        raise NotFoundError("关系不存在")
    if lock:
        # Match membership/review lock order: endpoints first, then the relation.
        endpoints = (row.source_id, row.target_id)
        await CoreEntityRepository().get_many_for_update(db, nid, list(endpoints))
        row = await repo.get_for_update(db, nid, relation_id)
        if row is None:
            raise NotFoundError("关系不存在")
        if (row.source_id, row.target_id) != endpoints:
            raise ConflictError("关系方向刚刚变化，请重新核对")
    return row


async def preview_change(db, novel_id: str, args: RelationChange) -> dict:
    row = await _row(db, novel_id, args.relation_id)
    service = EntityRelationService()
    before = service._relation_snapshot(row)
    history = list((row.review_meta or {}).get("author_change_history") or [])
    after = dict(before)
    if args.action == "restore":
        selected = next(
            (item for item in history if item["id"] == str(args.history_id)), None
        )
        if selected is None:
            raise NotFoundError("原修改记录不存在；旧操作没有恢复快照时不能猜测恢复")
        after.update(selected["before"])
        if after["status"] == "deprecated" and row.status != "deprecated":
            raise ValidationError("恢复目标会移除当前关系，请改用明确的人工移除操作")
    elif args.action == "remove":
        after.update(status="deprecated", validity=None)
    else:
        if row.status == "deprecated":
            raise ConflictError("关系已移除，请先选择历史记录恢复")
        if args.action == "end":
            if row.status != "canonical":
                raise ValidationError("只有已采用关系可以声明结束有效期")
            after["validity"] = {
                **(row.validity_json or {}),
                "end": args.end.model_dump(mode="json"),
            }
        else:
            after.update(args.changes.model_dump(mode="json", exclude_unset=True))
    if (after["source_id"], after["target_id"]) != (
        before["source_id"],
        before["target_id"],
    ):
        raise ConflictError("关系方向已变化，请重新核对端点，不能沿旧历史交换方向")
    if before["status"] == "canonical" or after["status"] == "canonical":
        await service._require_legacy_canon_write_allowed(db, novel_id)
    await service._validate_relation_validity(
        db, novel_id, str(after["status"]), after["validity"]
    )
    endpoints = (
        await db.scalars(
            select(CoreEntity).where(
                CoreEntity.novel_id == row.novel_id,
                CoreEntity.id.in_([row.source_id, row.target_id]),
            )
        )
    ).all()
    names = {
        str(entity.id): entity.name
        for entity in endpoints
        if entity.novel_id == row.novel_id
    }
    if len(names) != 2 or (
        after["status"] != "deprecated"
        and any(entity.status == "deprecated" for entity in endpoints)
    ):
        raise ConflictError("关系端点不可用，请先核对对象")
    return {
        "target_key": f"world_relation:{row.id}",
        "title": f"{names[str(row.source_id)]} → {names[str(row.target_id)]}",
        "before": before,
        "after": after,
        "source_version": entity_relation_execution_fingerprint(row),
        "action": args.action,
        "effect": "结束只设置作者有效期；移除保留历史；恢复需重新核对当前差异",
    }


async def change_history(
    db, novel_id: str, relation_id: uuid.UUID, *, skip: int = 0, limit: int = 20
) -> dict:
    row = await _row(db, novel_id, relation_id)
    history = list(reversed((row.review_meta or {}).get("author_change_history") or []))
    return {
        "items": history[skip : skip + limit],
        "total": len(history),
        "has_more": skip + limit < len(history),
        "status": row.status,
        "current": EntityRelationService()._relation_snapshot(row),
        "current_version": entity_relation_execution_fingerprint(row),
    }


async def apply_change(
    db,
    novel_id: str,
    args: RelationChange,
    *,
    operation_id: str,
    expected_preview_hash: str,
    actor: str,
) -> dict:
    row = await _row(db, novel_id, args.relation_id, lock=True)
    args_payload = args.model_dump(mode="json")
    arguments_hash = stable_hash(args_payload)
    meta = dict(row.review_meta or {})
    history = list(meta.get("author_change_history") or [])
    replay = next(
        (item for item in history if item["operation_id"] == operation_id), None
    )
    if replay:
        if (
            replay["arguments_hash"] != arguments_hash
            or replay["preview_hash"] != expected_preview_hash
        ):
            raise ConflictError("该提交标识已经用于其他关系修改，请读取原回执")
        return replay["receipt"]
    preview = await preview_change(db, novel_id, args)
    if stable_hash(preview) != expected_preview_hash:
        raise ConflictError("关系或历史已变化，请重新预览，当前内容没有被覆盖")
    before, after = preview["before"], preview["after"]
    changed = {
        key: value
        for key, value in after.items()
        if key in EntityRelationUpdate.model_fields and before.get(key) != value
    }
    if changed:
        await EntityRelationService().update(
            db,
            str(row.id),
            EntityRelationUpdate.model_validate(changed),
            novel_id=novel_id,
        )
    history_id = str(uuid.uuid4())
    receipt = {
        "action": args.action,
        "target": {"type": "world_entity", "id": str(row.source_id)},
        "type": "world_relation",
        "id": str(row.id),
        "history_id": history_id,
        "operation_id": operation_id,
        "label": {
            "edit": "已修改关系",
            "end": "已设置结束有效期",
            "remove": "已移除关系，历史仍保留",
            "restore": "已恢复关系快照",
        }[args.action],
        "status": "completed",
        "changed": bool(changed),
    }
    history.append(
        {
            "id": history_id,
            "operation_id": operation_id,
            "arguments_hash": arguments_hash,
            "preview_hash": expected_preview_hash,
            "action": args.action,
            "actor": actor,
            "created_at": datetime.now(UTC).isoformat(),
            "before": before,
            "after": after,
            "receipt": receipt,
        }
    )
    row.review_meta = {**(row.review_meta or {}), "author_change_history": history}
    db.add(row)
    await db.flush()
    return receipt
