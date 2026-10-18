"""Verify versioned object, dossier, and relation focus for Assistant turns."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.dossier_facade import read_world_object_dossier_history
from modules.world.repositories import CoreEntityRepository, EntityRelationRepository
from modules.world.services.relation_group_views import relation_option_label

_entities = CoreEntityRepository()
_relations = EntityRelationRepository()


def _stale(message: str) -> ConflictError:
    return ConflictError(message, code="assistant_focus_stale")


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _same_saved_version(actual: datetime | None, expected: datetime) -> bool:
    # SQLite drops timezone metadata from database-generated UTC timestamps.
    return _utc(actual) == _utc(expected)


def _focus_uuid(value: Any, field: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError(f"世界对象定位缺少有效的 {field}") from exc


def _focus_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError("世界对象定位缺少有效的已保存版本") from exc
    raise ValidationError("世界对象定位缺少有效的已保存版本")


def _json_value(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return value


def _version_text(value: datetime | None) -> str | None:
    normalized = _utc(value)
    return normalized.isoformat() if normalized else None


async def _read_assistant_world_focus(
    db, novel_id: str, focus_ref: dict[str, Any]
) -> dict[str, Any]:
    """Read only the exact current author-selected World source."""
    if not isinstance(focus_ref, dict):
        raise ValidationError("世界对象定位格式无效")
    kind = focus_ref.get("kind")
    entity_id = _focus_uuid(focus_ref.get("entity_id"), "entity_id")
    project_id = UUID(str(novel_id))
    entities = await _entities.get_by_ids(db, project_id, [entity_id])
    entity = entities[0] if entities else None
    if entity is None:
        raise NotFoundError("当前作品中找不到这个对象")

    if kind == "entity":
        expected = _focus_timestamp(focus_ref.get("updated_at"))
        if not _same_saved_version(entity.updated_at, expected):
            raise _stale("对象资料已变化，请重新读取后再提问")
        return {
            "kind": kind,
            "title": entity.name,
            "version": _version_text(entity.updated_at),
            "content": {
                "name": entity.name,
                "entity_type": entity.entity_type,
                "summary": entity.summary,
                "public_info": entity.public_info,
                "hidden_truth": entity.hidden_truth,
                "content_json": entity.content_json or {},
                "status": entity.status,
            },
        }

    if kind == "dossier_entry":
        entry_group_id = _focus_uuid(focus_ref.get("entry_group_id"), "entry_group_id")
        revision_id = _focus_uuid(focus_ref.get("revision_id"), "revision_id")
        history = await read_world_object_dossier_history(
            db,
            novel_id,
            str(entity.id),
            entry_group_id=str(entry_group_id),
            limit=1,
        )
        current = history.entries[0] if history.entries else None
        if (
            current is None
            or current.status != "active"
            or str(current.id) != str(revision_id)
        ):
            raise _stale("档案条目已变化，请重新读取后再提问")
        return {
            "kind": kind,
            "title": f"{entity.name} · {current.facing_label or '档案条目'}",
            "version": str(current.id),
            "content": {
                "revision_number": current.revision_number,
                "facing": _json_value(current.facing),
                "facing_label": current.facing_label,
                "content": current.content,
                "legacy_value": current.legacy_value,
                "tags": list(current.tags or []),
                "visibility": current.visibility,
                "validity": _json_value(current.validity),
                "story_field_key": current.story_field_key,
                "status": current.status,
            },
        }

    if kind == "relation":
        relation_id = _focus_uuid(focus_ref.get("relation_id"), "relation_id")
        expected = _focus_timestamp(focus_ref.get("updated_at"))
        relation = await _relations.get(db, relation_id)
        if (
            relation is None
            or relation.novel_id != project_id
            or entity.id not in {relation.source_id, relation.target_id}
            or relation.status == "deprecated"
        ):
            raise NotFoundError("这条关系不属于当前对象或作品")
        if not _same_saved_version(relation.updated_at, expected):
            raise _stale("关系已变化，请重新读取后再提问")
        endpoints = await _entities.get_by_ids(
            db, project_id, [relation.source_id, relation.target_id]
        )
        by_id = {item.id: item for item in endpoints}
        source = by_id.get(relation.source_id)
        target = by_id.get(relation.target_id)
        if source is None or target is None:
            raise NotFoundError("这条关系的对象端点已不可用")
        return {
            "kind": kind,
            "title": f"{source.name} 与 {target.name} 的关系",
            "version": _version_text(relation.updated_at),
            "content": {
                "source_name": source.name,
                "target_name": target.name,
                "relation_type": relation.relation_type,
                "relation_type_label": relation_option_label(relation.relation_type),
                "relation_kind": relation.relation_kind,
                "description": relation.description,
                "strength": relation.strength,
                "quote": relation.quote,
                "validity": relation.validity_json,
                "status": relation.status,
            },
        }

    raise ValidationError("不支持的世界对象定位")


async def validate_assistant_world_focus(
    db, novel_id: str, focus_ref: dict[str, Any]
) -> None:
    """Require the exact current focus version inside this project's object."""
    await _read_assistant_world_focus(db, novel_id, focus_ref)


async def read_assistant_world_focus(
    db, novel_id: str, focus_ref: dict[str, Any]
) -> dict[str, Any]:
    """Materialize one exact, current author focus after version validation."""
    return await _read_assistant_world_focus(db, novel_id, focus_ref)
