"""Authoritative World-layer storage and compatibility for object dossiers."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from core.service_keys import STORY_SCENE_SOURCE
from modules.project.facade import read_object_dossier_settings, require_active_project
from modules.world.dossier_repository import WorldObjectDossierRepository
from modules.world.map_spatial_anchors import resolve_anchor, resolve_validity
from modules.world.models import (
    Character,
    CoreEntity,
    EntityProfileTemplate,
    EntityProfileTemplateRevision,
    GenericEntityProfile,
    ProjectVocabularyRevision,
    ProjectVocabularyTerm,
    WorldObjectDossierEntry,
)
from modules.world.project_vocabulary_presets import preset_item_profile_type
from modules.world.schemas.dossier import (
    DossierAnchor,
    DossierEntryCreate,
    DossierEntryResponse,
    DossierEntryRestore,
    DossierEntryUpdate,
    DossierEvidenceRef,
    DossierFacetCatalog,
    DossierFacetOption,
    DossierFacingRef,
    DossierHistoryResponse,
    DossierLegacyProfileField,
    DossierReadResponse,
    DossierStateField,
    DossierTemplateAuthorResponse,
    DossierTemplateAuthorUpsert,
    DossierTemplateField,
    DossierTemplateHistoryResponse,
    DossierTemplateResponse,
    DossierTemplateUpsert,
    DossierValidity,
)
from modules.world.services.core.entity_types import SUPPORTED_ENTITY_TYPES
from modules.world.services.entity_profile_registry import PROFILE_REGISTRY
from modules.world.validity import validate_scene_validity
from modules.world.validity_policy import exact_story_field_observation
from shared.utils import parse_uuid

CORE_FACINGS: dict[str, dict[str, str]] = {
    "character": {
        "appearance": "外貌",
        "expression": "表达方式",
        "personality": "性格",
        "speech_style": "说话方式",
        "likes_dislikes": "喜好与厌恶",
        "habits": "习惯",
        "abilities_limits": "能力与限制",
        "identity_position": "身份与社会位置",
        "values_boundaries": "价值观与底线",
        "desire_fear": "欲望与恐惧",
        "secret": "秘密",
        "history": "前史",
        "relationship_summary": "关系摘要",
    },
    "location": {
        "geography": "地理与空间",
        "sensory_details": "感官细节",
        "appearance_people": "风貌与人群",
        "resources": "资源",
        "dangers": "危险",
        "rules_taboo": "规矩与禁忌",
        "history": "历史",
    },
    "item": {
        "form_appearance": "形制与外观",
        "sensory_details": "感官细节",
        "abilities_limits": "能力与限制",
        "cost_side_effects": "代价与副作用",
        "origin": "来历",
        "meaning": "意义",
    },
    "faction": {
        "form": "形态",
        "ideology": "理念",
        "structure_positions": "架构与职位",
        "resources": "资源",
        "rules": "规矩",
        "external_relations": "对外关系",
        "history": "历史",
    },
    "species": {
        "appearance": "外观特征",
        "physiology_lifespan": "生理与寿命",
        "culture_customs": "文化与习俗",
        "language": "语言",
        "abilities_weaknesses": "能力与弱点",
        "history": "历史",
    },
    "rule": {
        "principle": "原理",
        "constraints": "约束",
        "exceptions": "例外",
        "costs": "代价",
        "consequences": "后果",
        "known_scope": "已知范围",
    },
    "secret": {
        "truth": "真相",
        "knowledge_scope": "知情范围",
        "reveal_plan": "揭示计划",
        "risk": "风险",
    },
    "event": {"overview": "事件概述", "history": "事件经过"},
}

LEGACY_CHARACTER_FACINGS: dict[str, tuple[str, str]] = {
    "role": ("identity_position", "角色定位"),
    "appearance": ("appearance", "外貌"),
    "personality": ("personality", "性格"),
    "desire": ("desire_fear", "渴望／长期目标"),
    "fear": ("desire_fear", "恐惧／软肋"),
    "secret": ("secret", "作者秘密"),
    "weakness": ("abilities_limits", "能力限制"),
    "stance": ("values_boundaries", "价值观与立场"),
    "voice_style": ("speech_style", "说话方式"),
    "behavior_rules": ("habits", "习惯"),
    "relationship_summary": ("relationship_summary", "关系摘要"),
}
LEGACY_CORE_ENTITY_FACINGS = {
    "summary": ("overview", "概要", "public"),
    "public_info": ("public_info", "公开信息", "public"),
    "hidden_truth": ("truth", "隐藏真相", "secret"),
}
CORE_FACING_LABELS = {
    key: value
    for profile_fields in CORE_FACINGS.values()
    for key, value in profile_fields.items()
}
CORE_FACING_LABELS.update(
    {value[0]: value[1] for value in LEGACY_CORE_ENTITY_FACINGS.values()}
)
_BORROWED_FACING_PREFIX = "borrowed:"
_ENTITY_TYPE_LABELS = {
    "character": "人物",
    "location": "地点",
    "item": "物件",
    "faction": "势力",
    "species": "种族",
    "rule": "规则",
    "secret": "秘密",
    "event": "事件",
}


def _stored_core_facing_key(source_entity_type: str, key: str) -> str:
    return f"{_BORROWED_FACING_PREFIX}{source_entity_type}:{key}"


def _borrowed_core_facing_parts(key: str) -> tuple[str, str] | None:
    if not key.startswith(_BORROWED_FACING_PREFIX):
        return None
    source_type, separator, core_key = key[len(_BORROWED_FACING_PREFIX) :].partition(":")
    if not separator or not source_type or not core_key:
        return None
    return source_type, core_key


def _core_facing_from_storage(key: str) -> tuple[DossierFacingRef, str]:
    borrowed = _borrowed_core_facing_parts(key)
    if borrowed is not None:
        source_type, core_key = borrowed
        if core_key in CORE_FACINGS.get(source_type, {}):
            label = CORE_FACINGS[source_type][core_key]
            return DossierFacingRef(kind="core", key=key), (
                f"{label} · 借用{_ENTITY_TYPE_LABELS.get(source_type, source_type)}"
            )
    return (
        DossierFacingRef(kind="core", key=key),
        CORE_FACING_LABELS.get(key, key),
    )


def _facing_identity(facing: DossierFacingRef, _entity_type: str) -> tuple[str, str]:
    if facing.kind == "project":
        return "project", str(facing.term_id)
    return "core", str(facing.key)


def _validate_borrowed_facing_refs(
    profile_type: str, facings: list[DossierFacingRef]
) -> set[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()
    if facings and (profile_type in SUPPORTED_ENTITY_TYPES):
        raise ValidationError("内置对象类型不能声明借用内核面向")
    for facing in facings:
        borrowed = _borrowed_core_facing_parts(str(facing.key or ""))
        if facing.kind != "core" or borrowed is None:
            raise ValidationError("借用面向必须使用明确的内置来源类型与内核键")
        source_type, core_key = borrowed
        if source_type == profile_type or core_key not in CORE_FACINGS.get(
            source_type, {}
        ):
            raise ValidationError("借用面向必须明确选择其他内置类型的有效内核面向")
        if borrowed in identities:
            raise ValidationError("模板不能重复登记同一借用面向")
        identities.add(borrowed)
    return identities


DOSSIER_SOURCES = frozenset(
    {
        "author",
        "author_assistant",
        "evolution_adoption",
        "spreadsheet_migration",
        "legacy_import",
        "object_completion",
    }
)
_UNSET = object()
GENERIC_PROFILE_FIELD_PREFIX = "generic_profile:"
GENERIC_UNKNOWN_FACING_KEY = "legacy_unmapped"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _display_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                label = item.get("label") or item.get("name") or item.get("title")
                description = item.get("description") or item.get("content")
                parts.append(
                    "：".join(str(part) for part in (label, description) if part)
                    or "；".join(f"{key}：{part}" for key, part in item.items())
                )
            else:
                parts.append(str(item))
        return "；".join(part for part in parts if part)
    if isinstance(value, dict):
        return "；".join(f"{key}：{part}" for key, part in value.items())
    return str(value)


def _validity_values(
    validity: DossierValidity | None,
) -> dict[str, Any]:
    return {
        "start_anchor_kind": validity.start.kind if validity and validity.start else None,
        "start_anchor_id": validity.start.id if validity and validity.start else None,
        "end_anchor_kind": validity.end.kind if validity and validity.end else None,
        "end_anchor_id": validity.end.id if validity and validity.end else None,
    }


def _validity_from_row(row: WorldObjectDossierEntry) -> DossierValidity | None:
    if not any(
        (
            row.start_anchor_id,
            row.end_anchor_id,
            row.start_anchor_kind,
            row.end_anchor_kind,
        )
    ):
        return None
    return DossierValidity(
        start=(
            DossierAnchor(kind=row.start_anchor_kind, id=row.start_anchor_id)
            if row.start_anchor_kind and row.start_anchor_id
            else None
        ),
        end=(
            DossierAnchor(kind=row.end_anchor_kind, id=row.end_anchor_id)
            if row.end_anchor_kind and row.end_anchor_id
            else None
        ),
    )


def _entry_response(
    row: WorldObjectDossierEntry,
    *,
    facing_label: str,
    source_metadata: dict[str, Any] | None = None,
    anchor_problem: str | None = None,
    effective_at_cutoff: bool | None = None,
    validity_conflict: bool = False,
    story_override_applied: bool = False,
    validity_gap: str | None = None,
    story_observation: dict[str, Any] | None = None,
) -> DossierEntryResponse:
    facing = (
        _core_facing_from_storage(row.facing_key)[0]
        if row.facing_kind == "core"
        else DossierFacingRef(kind="project", term_id=row.vocabulary_term_id)
    )


    evidence = [
        DossierEvidenceRef.model_validate(item) for item in row.source_refs_json or []
    ]
    return DossierEntryResponse(
        id=row.id,
        entry_group_id=row.entry_group_id,
        revision_number=row.revision_number,
        previous_revision_id=row.previous_revision_id,
        entity_id=row.entity_id,
        facing=facing,
        facing_label=facing_label,
        legacy_field_key=row.legacy_field_key,
        story_field_key=row.story_field_key,
        content=row.content,
        tags=row.tags_json or [],
        evidence=evidence,
        legacy_value=row.legacy_value_json,
        source_metadata=(
            row.metadata_json or {} if source_metadata is None else source_metadata
        ),
        quote_text=row.quote_text,
        source=row.source,
        visibility=row.visibility,
        status=row.status,
        validity=_validity_from_row(row),
        anchor_problem=anchor_problem,
        effective_at_cutoff=effective_at_cutoff,
        validity_conflict=validity_conflict,
        story_override_applied=story_override_applied,
        validity_gap=validity_gap,
        story_observation=story_observation,
        revision_reason=row.revision_reason,
        restored_from_id=row.restored_from_id,
        created_at=row.created_at,
    )


def _generic_profile_value(row: WorldObjectDossierEntry) -> Any:
    if (row.metadata_json or {}).get("generic_profile_legacy_value_is_null") is True:
        return None
    return row.legacy_value_json if row.legacy_value_json is not None else row.content


class WorldObjectDossierService:
    repo = WorldObjectDossierRepository()

    async def _entity(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        *,
        lock: bool = False,
        require_canonical: bool = False,
    ) -> CoreEntity:
        if lock:
            await require_active_project(db, novel_id, allow_demo_readonly=False)
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        statement = select(CoreEntity).where(
            CoreEntity.novel_id == nid,
            CoreEntity.id == eid,
        )
        if lock:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        entity = (await db.execute(statement)).scalar_one_or_none()
        if entity is None:
            raise NotFoundError("World object not found in this project")
        if require_canonical and entity.status != "canonical":
            raise ValidationError("仅已采用对象可以编辑档案")
        return entity

    async def _validate_facing(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_type: str,
        facing: DossierFacingRef,
        *,
        declared_borrowed: set[tuple[str, str]] | None = None,
        lock_template: bool = False,
    ) -> tuple[str, str]:
        if facing.kind == "core":
            key = str(facing.key)
            borrowed_facing = _borrowed_core_facing_parts(key)
            if borrowed_facing is None:
                if key not in CORE_FACINGS.get(entity_type, {}):
                    raise ValidationError("该对象类型不支持此内核面向")
                return key, CORE_FACINGS[entity_type][key]
            source_type, core_key = borrowed_facing
            if (
                core_key not in CORE_FACINGS.get(source_type, {})
                or source_type == entity_type
                or entity_type in SUPPORTED_ENTITY_TYPES
            ):
                raise ValidationError("借用面向的来源类型或内核键无效")
            borrowed = (
                declared_borrowed
                if declared_borrowed is not None
                else await self._template_borrowed_facings(
                    db, novel_id, entity_type, lock=lock_template
                )
            )
            if (source_type, core_key) not in borrowed:
                raise ValidationError("请先在当前对象类型模板中明确借用该内核面向")
            label = CORE_FACINGS[source_type][core_key]
            return key, (
                f"{label} · 借用{_ENTITY_TYPE_LABELS.get(source_type, source_type)}"
            )
        record = await self._vocabulary_record(db, novel_id, facing.term_id)
        term, revision = record
        if term.kind != "dossier_facing" or term.status != "active":
            raise ValidationError("档案面向未启用，不能用于正式档案")
        preset_profile_type = preset_item_profile_type(
            term.preset_id, term.preset_version, term.preset_item_key
        )
        if preset_profile_type and preset_profile_type != entity_type:
            raise ValidationError("该题材面向只适用于对应对象类型")
        return str(term.id), str(revision.snapshot_json["name"])

    async def _template_borrowed_facings(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        profile_type: str,
        *,
        lock: bool = False,
    ) -> set[tuple[str, str]]:
        statement = select(EntityProfileTemplate).where(
            EntityProfileTemplate.novel_id == novel_id,
            EntityProfileTemplate.profile_type == profile_type,
            EntityProfileTemplate.status == "active",
        )
        if lock:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        template = await db.scalar(statement)
        if template is None:
            return set()
        revision = await db.scalar(
            select(EntityProfileTemplateRevision).where(
                EntityProfileTemplateRevision.novel_id == novel_id,
                EntityProfileTemplateRevision.template_id == template.id,
                EntityProfileTemplateRevision.version_number == template.version_number,
            )
        )
        if revision is None:
            return set()
        result = set()
        for raw in (revision.snapshot_json or {}).get("borrowed_facings", []):
            try:
                if isinstance(raw, dict) and raw.get("source_entity_type"):
                    if raw.get("kind") != "core":
                        continue
                    source_type = str(raw["source_entity_type"])
                    key = _stored_core_facing_key(source_type, str(raw.get("key", "")))
                else:
                    facing = DossierFacingRef.model_validate(raw)
                    key = str(facing.key)
                    parsed = _borrowed_core_facing_parts(key)
                    source_type = parsed[0] if parsed else ""
            except (PydanticValidationError, TypeError, ValueError):
                continue
            parsed = _borrowed_core_facing_parts(key)
            if (
                parsed is not None
                and parsed[0] == source_type
                and parsed[1] in CORE_FACINGS.get(source_type, {})
                and source_type != profile_type
                and profile_type not in SUPPORTED_ENTITY_TYPES
            ):
                result.add(parsed)
        return result

    @staticmethod
    def _validate_legacy_content(field: str | None, content: str | None) -> None:
        if field == "role" and content is not None and len(content) > 64:
            raise ValidationError(
                "人物角色字段最多 64 个字符", code="dossier_role_too_long"
            )

    @staticmethod
    def _validate_legacy_field(
        entity: CoreEntity,
        facing: DossierFacingRef,
        legacy_field_key: str | None,
    ) -> None:
        if legacy_field_key is None:
            return
        mapping = LEGACY_CHARACTER_FACINGS.get(legacy_field_key)
        if entity.entity_type == "character" and mapping is not None:
            if facing.kind == "core" and facing.key == mapping[0]:
                return
            raise ValidationError("旧人物字段只能映射到对应的人物内核面向")
        binding = PROFILE_REGISTRY.get(entity.entity_type)
        table_name, separator, field = legacy_field_key.partition(".")
        expected = binding.dossier_fields.get(field) if binding else None
        if (
            binding is None
            or not separator
            or table_name != binding.model.__tablename__
            or expected is None
            or facing.kind != "core"
            or facing.key != expected[0]
        ):
            raise ValidationError("旧档案字段只能映射到冻结登记的稳定面向")

    @staticmethod
    def _validate_strong_legacy_value(
        entity: CoreEntity,
        field: str | None,
        content: str,
        value: Any,
        *,
        supplied: bool,
    ) -> None:
        binding = PROFILE_REGISTRY.get(entity.entity_type)
        if entity.entity_type == "character" and field in LEGACY_CHARACTER_FACINGS:
            if field == "behavior_rules":
                if not isinstance(value, list) or any(
                    not isinstance(item, dict) for item in value
                ):
                    raise ValidationError("人物行为规则旧值必须是对象数组")
            elif supplied and (not isinstance(value, str) or value != content):
                raise ValidationError("人物文本旧值必须与档案内容一致")
            if field == "behavior_rules":
                try:
                    json.dumps(value, ensure_ascii=False, allow_nan=False)
                except (TypeError, ValueError) as exc:
                    raise ValidationError("人物结构化旧值不是有效 JSON") from exc
                if _display_value(value) != content:
                    raise ValidationError("人物结构化旧值需要与展示内容一致")
            return
        if binding is None or not field:
            if supplied:
                raise ValidationError("结构化旧值仅支持登记的强档案字段")
            return
        table_name, separator, name = field.partition(".")
        if not separator or table_name != binding.model.__tablename__:
            if supplied:
                raise ValidationError("结构化旧值仅支持登记的强档案字段")
            return
        if name not in binding.dossier_fields:
            if supplied:
                raise ValidationError("结构化旧值仅支持冻结登记的稳定字段")
            return
        if name.endswith("_json"):
            if value is None and not content.strip():
                return
            if not isinstance(value, list):
                raise ValidationError("结构化旧字段需要与展示内容一致的数组值")
            valid_shape = (
                all(isinstance(item, str) for item in value)
                if name.endswith("_entity_ids_json")
                else all(isinstance(item, dict) for item in value)
            )
            try:
                json.dumps(value, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise ValidationError("结构化旧值不是有效 JSON") from exc
            if not valid_shape or _display_value(value) != content:
                raise ValidationError("结构化旧字段需要与展示内容一致的数组值")
        elif supplied and (not isinstance(value, str) or value != content):
            raise ValidationError("文本旧字段的结构化值必须与档案内容一致")

    @staticmethod
    def _strong_legacy_binding(entity: CoreEntity, field: str | None):
        binding = PROFILE_REGISTRY.get(entity.entity_type)
        if binding is None or not field:
            return None
        table_name, separator, name = field.partition(".")
        if not separator or table_name != binding.model.__tablename__:
            return None
        facing = binding.dossier_fields.get(name)
        return (binding, name, facing) if facing is not None else None

    def _validate_legacy_visibility(
        self,
        entity: CoreEntity,
        field: str | None,
        visibility: str,
    ) -> None:
        strong = self._strong_legacy_binding(entity, field)
        if strong is not None and strong[2][1] != visibility:
            raise ValidationError("旧档案字段可见性不能偏离冻结映射")

    @staticmethod
    def validate_strong_profile_payload(
        entity: CoreEntity,
        payload: dict[str, Any],
    ) -> None:
        binding = PROFILE_REGISTRY.get(entity.entity_type)
        if binding is None:
            return
        for field in binding.dossier_fields.keys() & payload.keys():
            value = payload[field]
            if value is None:
                continue
            column = binding.model.__table__.columns[field]
            if isinstance(value, str):
                if column.type.length and len(value) > column.type.length:
                    raise ValidationError(f"{field} 超过旧档案字段长度限制")
                display = value
            elif isinstance(value, list):
                valid_shape = (
                    all(isinstance(item, str) for item in value)
                    if field.endswith("_entity_ids_json")
                    else all(isinstance(item, dict) for item in value)
                )
                if not valid_shape:
                    raise ValidationError(f"{field} 类型不符合旧档案结构")
                try:
                    json.dumps(value, ensure_ascii=False, allow_nan=False)
                except (TypeError, ValueError) as exc:
                    raise ValidationError(f"{field} 不是有效 JSON") from exc
                display = _display_value(value)
            else:
                display = str(value)
            if len(display) > 20000:
                raise ValidationError("旧档案字段展示长度最多 20000 个字符")

    async def sync_strong_profile_field(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        field: str,
        value: Any,
        *,
        profile_type: str | None = None,
        profile_metadata: dict[str, Any] | None = None,
    ) -> None:
        binding = PROFILE_REGISTRY.get(profile_type or entity.entity_type)
        facing = binding.dossier_fields.get(field) if binding else None
        if binding is None or facing is None:
            return
        key = f"{binding.model.__tablename__}.{field}"
        text = _display_value(value) if value is not None else ""
        await self._sync_profile_field(
            db,
            entity,
            key,
            facing[0],
            facing[1],
            text,
            value,
            profile_metadata=profile_metadata,
        )

    async def _sync_profile_field(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        legacy_field_key: str,
        facing_key: str,
        visibility: str,
        content: str | None,
        legacy_value: Any,
        *,
        profile_metadata: dict[str, Any] | None = None,
    ) -> None:
        active_rows = await self.repo.list_active_legacy_field(
            db, entity.novel_id, entity.id, legacy_field_key, for_update=True
        )
        current = active_rows[-1].legacy_value_json if active_rows else None
        if active_rows and current is None:
            current = active_rows[-1].content
        value = legacy_value if legacy_value is not None else content
        cleared = value is None or value == "" or value == [] or value == {}
        revision_status = (
            "active"
            if (profile_metadata or {}).get("status") in {"canonical", "confirmed"}
            and entity.status == "canonical"
            else "needs_review"
        )
        latest = active_rows[-1] if active_rows else await self.repo.latest_legacy_field(
            db, entity.novel_id, entity.id, legacy_field_key, for_update=True
        )
        if (active_rows and current == value) or (
            not active_rows
            and latest is not None
            and latest.status == "cleared"
            and cleared
        ):
            return
        for active in active_rows:
            active.status = "superseded"
        await self._make_revision(
            db,
            latest,
            novel_id=entity.novel_id,
            entity_id=entity.id,
            entry_group_id=latest.entry_group_id if latest else uuid.uuid4(),
            revision_number=latest.revision_number + 1 if latest else 1,
            facing_kind="core",
            facing_key=facing_key,
            vocabulary_term_id=None,
            legacy_field_key=legacy_field_key,
            content="" if cleared else content or "",
            tags=[],
            evidence=[],
            quote_text=None,
            visibility=visibility,
            validity=None,
            source="author",
            reason="legacy_profile_writeback",
            status="cleared" if cleared else revision_status,
            legacy_value_json=(
                None
                if cleared or not legacy_field_key.endswith("_json")
                else legacy_value
            ),
            metadata_json={"strong_profile": profile_metadata or {}}
            if profile_metadata
            else None,
        )

    async def sync_strong_profile_status(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        status: str,
    ) -> None:
        binding = PROFILE_REGISTRY.get(entity.entity_type)
        if binding is None:
            return
        target_status = (
            "active"
            if status in {"canonical", "confirmed"} and entity.status == "canonical"
            else "needs_review"
        )
        for field in binding.dossier_fields:
            key = f"{binding.model.__tablename__}.{field}"
            latest = await self.repo.latest_legacy_field(
                db, entity.novel_id, entity.id, key, for_update=True
            )
            if latest is None or latest.status in {"cleared", target_status}:
                continue
            if latest.status not in {"active", "needs_review"}:
                continue
            latest.status = "superseded"
            await self._make_revision(
                db,
                latest,
                novel_id=entity.novel_id,
                entity_id=entity.id,
                entry_group_id=latest.entry_group_id,
                revision_number=latest.revision_number + 1,
                facing_kind=latest.facing_kind,
                facing_key=latest.facing_key,
                vocabulary_term_id=latest.vocabulary_term_id,
                legacy_field_key=key,
                content=latest.content,
                tags=latest.tags_json or [],
                evidence=latest.source_refs_json or [],
                quote_text=latest.quote_text,
                visibility=latest.visibility,
                validity=_validity_from_row(latest),
                source="author",
                reason="strong_profile_status_change",
                status=target_status,
                legacy_value_json=latest.legacy_value_json,
                metadata_json=latest.metadata_json,
            )

    async def _vocabulary_record(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        term_id: uuid.UUID | None,
    ) -> tuple[ProjectVocabularyTerm, ProjectVocabularyRevision]:
        if term_id is None:
            raise ValidationError("项目面向缺少词条 ID")
        statement = (
            select(ProjectVocabularyTerm, ProjectVocabularyRevision)
            .join(
                ProjectVocabularyRevision,
                ProjectVocabularyRevision.id == ProjectVocabularyTerm.current_revision_id,
            )
            .where(
                ProjectVocabularyTerm.novel_id == novel_id,
                ProjectVocabularyTerm.id == term_id,
                ProjectVocabularyRevision.novel_id == novel_id,
                ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id,
            )
        )
        row = (await db.execute(statement)).one_or_none()
        if row is None:
            raise NotFoundError("项目面向不存在")
        return row

    async def _labels(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entries: list[WorldObjectDossierEntry],
    ) -> dict[uuid.UUID, str]:
        ids = {row.vocabulary_term_id for row in entries if row.vocabulary_term_id}
        if not ids:
            return {}
        records = await db.execute(
            select(ProjectVocabularyTerm, ProjectVocabularyRevision)
            .join(
                ProjectVocabularyRevision,
                ProjectVocabularyRevision.id == ProjectVocabularyTerm.current_revision_id,
            )
            .where(
                ProjectVocabularyTerm.novel_id == novel_id,
                ProjectVocabularyTerm.id.in_(ids),
                ProjectVocabularyRevision.novel_id == novel_id,
                ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id,
            )
        )
        return {
            term.id: revision.snapshot_json.get("name", "未知面向")
            for term, revision in records
        }

    async def _anchor_scenes(
        self, db: AsyncSession, novel_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        return await get(STORY_SCENE_SOURCE).read_temporal_anchor_scenes(
            db, str(novel_id)
        )

    async def _validate_validity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        validity: DossierValidity | None,
    ) -> None:
        await validate_scene_validity(db, novel_id, validity)

    async def _validate_story_field_key(
        self, db: AsyncSession, entity: CoreEntity, field_key: str | None
    ) -> None:
        if field_key is None:
            return
        if entity.entity_type in SUPPORTED_ENTITY_TYPES:
            raise ValidationError("仅自定义对象类型可以绑定自定义 Story 状态字段")
        template = await db.scalar(
            select(EntityProfileTemplate).where(
                EntityProfileTemplate.novel_id == entity.novel_id,
                EntityProfileTemplate.profile_type == entity.entity_type,
                EntityProfileTemplate.status == "active",
            )
        )
        if template is None:
            raise ValidationError("请先为该对象类型声明文字状态字段")
        revision = await db.scalar(
            select(EntityProfileTemplateRevision).where(
                EntityProfileTemplateRevision.novel_id == entity.novel_id,
                EntityProfileTemplateRevision.template_id == template.id,
                EntityProfileTemplateRevision.version_number == template.version_number,
            )
        )
        state_fields = [
            DossierStateField.model_validate(item)
            for item in (
                (revision.snapshot_json or {}).get("state_fields", []) if revision else []
            )
        ]
        if not any(item.key == field_key for item in state_fields):
            raise ValidationError("关联的 Story 状态字段未在当前对象类型模板中声明")

    async def list_facets(
        self, db: AsyncSession, novel_id: str, entity_type: str
    ) -> DossierFacetCatalog:
        nid = parse_uuid(novel_id, "novel_id")
        options = [
            DossierFacetOption(
                facing=DossierFacingRef(kind="core", key=key),
                label=label,
                source="core",
            )
            for key, label in CORE_FACINGS.get(entity_type, {}).items()
        ]
        options.extend(
            DossierFacetOption(
                facing=DossierFacingRef(
                    kind="core", key=_stored_core_facing_key(source_type, key)
                ),
                label=(
                    f"{CORE_FACINGS[source_type][key]} · 借用"
                    f"{_ENTITY_TYPE_LABELS.get(source_type, source_type)}"
                ),
                source="core",
            )
            for source_type, key in sorted(
                await self._template_borrowed_facings(db, nid, entity_type)
            )
        )
        rows = await db.execute(
            select(ProjectVocabularyTerm, ProjectVocabularyRevision)
            .join(
                ProjectVocabularyRevision,
                ProjectVocabularyRevision.id == ProjectVocabularyTerm.current_revision_id,
            )
            .where(
                ProjectVocabularyTerm.novel_id == nid,
                ProjectVocabularyTerm.kind == "dossier_facing",
                ProjectVocabularyTerm.status == "active",
                ProjectVocabularyRevision.novel_id == nid,
            )
        )
        project_options = []
        for term, revision in rows:
            snapshot = revision.snapshot_json
            preset_profile_type = preset_item_profile_type(
                term.preset_id, term.preset_version, term.preset_item_key
            )
            if preset_profile_type and preset_profile_type != entity_type:
                continue
            project_options.append(
                DossierFacetOption(
                    facing=DossierFacingRef(kind="project", term_id=term.id),
                    label=snapshot.get("name", "未命名面向"),
                    description=snapshot.get("description", ""),
                    source="project",
                )
            )
        options.extend(
            sorted(
                project_options, key=lambda item: (item.label, str(item.facing.term_id))
            )
        )
        return DossierFacetCatalog(
            entity_type=entity_type,
            items=options,
            total_count=len(options),
        )

    async def list_facets_for_entity(
        self, db: AsyncSession, novel_id: str, entity_id: str
    ) -> DossierFacetCatalog:
        entity = await self._entity(db, novel_id, entity_id)
        return await self.list_facets(db, novel_id, entity.entity_type)

    async def read(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        *,
        as_of_scene_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        visibility_filter: str | None = None,
        visible_contents: list[str] | None = None,
        visible_fields: dict[str, list[str]] | None = None,
        story_viewpoint: dict[str, Any] | None = None,
    ) -> DossierReadResponse:
        if visibility_filter not in {None, "public"}:
            raise ValidationError("档案可见性筛选仅支持 public")
        if (
            visible_contents is not None or visible_fields is not None
        ) and visibility_filter != "public":
            raise ValidationError("内容证明筛选只能用于公开档案读取")
        entity = await self._entity(db, novel_id, entity_id)
        nid = parse_uuid(novel_id, "novel_id")
        active_entries = await self.repo.list_active_for_entity(
            db, nid, entity.id, visibility_filter=visibility_filter
        )
        has_generic_bridge = any(
            isinstance((row.metadata_json or {}).get("generic_profile_field_key"), str)
            for row in active_entries
        )
        generic_profile = (
            await db.scalar(
                select(GenericEntityProfile).where(
                    GenericEntityProfile.novel_id == entity.novel_id,
                    GenericEntityProfile.entity_id == entity.id,
                    GenericEntityProfile.profile_type == entity.entity_type,
                )
            )
            if has_generic_bridge
            else None
        )
        generic_profile_metadata = (
            {
                "profile_type": generic_profile.profile_type,
                "profile_status": generic_profile.status,
                "source": generic_profile.source,
                "confidence": generic_profile.confidence,
                "evidence_refs_json": generic_profile.evidence_refs_json or [],
            }
            if generic_profile is not None
            else None
        )
        generic_unknown = [
            row
            for row in active_entries
            if row.facing_key == GENERIC_UNKNOWN_FACING_KEY
            and (row.legacy_field_key or "").startswith(GENERIC_PROFILE_FIELD_PREFIX)
        ]
        entries = [row for row in active_entries if row not in generic_unknown]
        if visible_contents is not None:
            allowed = set(visible_contents)
            entries = [row for row in entries if row.content in allowed]
        if visible_fields is not None:

            def field_is_visible(row):
                keys = {
                    row.story_field_key,
                    row.legacy_field_key,
                    (row.metadata_json or {}).get("generic_profile_field_key"),
                } - {None, ""}
                return any(row.content in visible_fields.get(key, []) for key in keys)

            entries = [row for row in entries if field_is_visible(row)]
        labels = await self._labels(db, nid, entries)
        legacy_profile_fields = (
            await self._legacy_profile_fields(db, entity, generic_unknown)
            if visibility_filter is None
            else []
        )
        cutoff_index = None
        cutoff_error = None
        story_view = None
        allow_story_override = False
        author_full = visibility_filter is None and (
            story_viewpoint is None or story_viewpoint.get("kind") == "author"
        )
        if as_of_scene_id is not None:
            scenes = await self._anchor_scenes(db, nid)
            cutoff_index, cutoff_error = resolve_anchor(
                DossierAnchor(kind="scene", id=parse_uuid(as_of_scene_id, "scene_id")),
                scenes,
                endpoint="start",
            )
            if cutoff_error or cutoff_index is None:
                raise ValidationError("截止 Scene 锚点无效，无法读取该时点档案")
            if author_full:
                settings = await read_object_dossier_settings(db, str(nid))
                allow_story_override = bool(settings["allow_story_override"])
            if author_full and any(
                _validity_from_row(row) is not None and row.story_field_key
                for row in entries
            ):
                story_view = await get(STORY_SCENE_SOURCE).get_scene_state_view(
                    db,
                    str(nid),
                    as_of_scene_id,
                    viewpoint=story_viewpoint or {"kind": "author"},
                    include_dimensions=["entities"],
                )
        result = []
        for row in entries:
            validity = _validity_from_row(row)
            anchor_problem = cutoff_error
            effective: bool | None = True if validity is None else None
            validity_conflict = False
            story_override_applied = False
            validity_gap = anchor_problem
            story_observation = None
            if validity and as_of_scene_id is not None:
                resolved = resolve_validity(validity, scenes)
                if not resolved.valid:
                    anchor_problem = resolved.reason
                    validity_gap = resolved.reason or "author_interval_anchor_invalid"
                    effective = False
                elif cutoff_index is None:
                    effective = False
                else:
                    effective = (
                        resolved.start_scene_index is None
                        or resolved.start_scene_index <= cutoff_index
                    ) and (
                        resolved.end_scene_index is None
                        or cutoff_index <= resolved.end_scene_index
                    )
                if validity and author_full and anchor_problem is None:
                    if not row.story_field_key:
                        validity_gap = "story_field_alignment_not_declared"
                    elif story_view is None:
                        validity_gap = "story_state_unavailable"
                    else:
                        observation = exact_story_field_observation(
                            story_view,
                            novel_id=str(nid),
                            cutoff_scene_id=as_of_scene_id,
                            entity_id=str(entity.id),
                            entity_type=entity.entity_type,
                            field_key=row.story_field_key,
                            cutoff_scene_index=int(cutoff_index),
                        )
                        validity_gap = observation.gap
                        if (
                            observation.gap is None
                            and (observation.value == row.content) != effective
                        ):
                            validity_conflict = True
                            story_observation = {
                                "event_id": observation.event_id,
                                "scene_index": observation.scene_index,
                                "source_refs": observation.source_refs or [],
                                "author_confirmed": observation.author_confirmed,
                            }
                            if allow_story_override:
                                effective = observation.value == row.content
                                story_override_applied = True
                                validity_gap = None
                if (
                    not effective
                    and anchor_problem is None
                    and not story_override_applied
                ):
                    continue
            result.append(
                _entry_response(
                    row,
                    facing_label=(
                        _core_facing_from_storage(row.facing_key)[1]
                        if row.facing_kind == "core"
                        else labels.get(row.vocabulary_term_id, "未知面向")
                    ),
                    source_metadata=(
                        {
                            **(row.metadata_json or {}),
                            "generic_profile_metadata": generic_profile_metadata,
                        }
                        if generic_profile_metadata is not None
                        and isinstance(
                            (row.metadata_json or {}).get("generic_profile_field_key"),
                            str,
                        )
                        else None
                    ),
                    anchor_problem=anchor_problem,
                    effective_at_cutoff=effective,
                    validity_conflict=validity_conflict,
                    story_override_applied=story_override_applied,
                    validity_gap=validity_gap,
                    story_observation=story_observation,
                )
            )
        total_count = len(result)
        page_limit = min(max(limit, 1), 250)
        page_offset = max(offset, 0)
        result = result[page_offset : page_offset + page_limit]
        omitted_count = max(0, total_count - len(result))
        payload = {
            "entries": [item.model_dump(mode="json") for item in result],
            "legacy_profile_fields": [
                item.model_dump(mode="json") for item in legacy_profile_fields
            ],
        }
        fingerprint = hashlib.sha256(
            _canonical_json(
                {
                    "entity_id": str(entity.id),
                    "entity_status": entity.status,
                    "visibility_filter": visibility_filter,
                    "as_of_scene_id": as_of_scene_id,
                    "allow_story_override": allow_story_override,
                    "offset": page_offset,
                    "limit": page_limit,
                    "entries": payload,
                    "omitted_count": omitted_count,
                }
            ).encode("utf-8")
        ).hexdigest()
        return DossierReadResponse(
            entity_id=entity.id,
            entity_type=entity.entity_type,
            entity_status=entity.status,
            visibility_filter=visibility_filter,
            as_of_scene_id=parse_uuid(as_of_scene_id, "scene_id")
            if as_of_scene_id
            else None,
            allow_story_override=allow_story_override,
            offset=page_offset,
            limit=page_limit,
            entries=result,
            legacy_profile_fields=legacy_profile_fields,
            total_count=total_count,
            omitted_count=omitted_count,
            dossier_fingerprint=fingerprint,
            layers=["world"],
            unavailable_layers=["continuity", "evolution"],
            unknown=total_count == 0
            and not any(item.mapped for item in legacy_profile_fields),
        )

    async def _legacy_profile_fields(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        generic_unknown: list[WorldObjectDossierEntry] | None = None,
    ) -> list[DossierLegacyProfileField]:
        """Project generic legacy data only through an explicitly linked template.

        Unmapped keys stay in the response with their original JSON values. This is
        a read projection; it never deletes or rewrites ``data_json``.
        """
        profile = await db.scalar(
            select(GenericEntityProfile).where(
                GenericEntityProfile.novel_id == entity.novel_id,
                GenericEntityProfile.entity_id == entity.id,
                GenericEntityProfile.profile_type == entity.entity_type,
                GenericEntityProfile.status != "migrated",
            )
        )
        if profile is None:
            return []
        generic_rows = await self._generic_profile_rows(db, entity)
        shadowed_keys = {key for key, _row in generic_rows.items()}
        template = None
        if profile.template_id is not None:
            template = await db.scalar(
                select(EntityProfileTemplate).where(
                    EntityProfileTemplate.novel_id == entity.novel_id,
                    EntityProfileTemplate.id == profile.template_id,
                    EntityProfileTemplate.profile_type == entity.entity_type,
                )
            )
        template_fields = (
            (template.template_schema_json or {}).get("fields", [])
            if template is not None and template.status == "active"
            else []
        )
        definitions: dict[str, list[dict[str, Any]]] = {}
        for raw in template_fields:
            if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
                continue
            definitions.setdefault(raw["key"], []).append(raw)

        project_ids: set[uuid.UUID] = set()
        for candidates in definitions.values():
            if len(candidates) != 1:
                continue
            facing = candidates[0].get("facing")
            if not isinstance(facing, dict) or facing.get("kind") != "project":
                continue
            try:
                project_ids.add(uuid.UUID(str(facing.get("term_id"))))
            except (TypeError, ValueError):
                continue
        active_project_facings: dict[uuid.UUID, str] = {}
        if project_ids:
            rows = await db.execute(
                select(ProjectVocabularyTerm, ProjectVocabularyRevision)
                .join(
                    ProjectVocabularyRevision,
                    ProjectVocabularyRevision.id
                    == ProjectVocabularyTerm.current_revision_id,
                )
                .where(
                    ProjectVocabularyTerm.novel_id == entity.novel_id,
                    ProjectVocabularyTerm.id.in_(project_ids),
                    ProjectVocabularyTerm.kind == "dossier_facing",
                    ProjectVocabularyTerm.status == "active",
                    ProjectVocabularyRevision.novel_id == entity.novel_id,
                )
            )
            active_project_facings = {
                term.id: str(revision.snapshot_json.get("name") or "未知面向")
                for term, revision in rows
            }

        borrowed_core_keys = (
            {
                _facing_identity(
                    DossierFacingRef.model_validate(raw), entity.entity_type
                )[1]
                for raw in (template.template_schema_json or {}).get(
                    "borrowed_facings", []
                )
                if isinstance(raw, dict)
            }
            if template is not None
            else set()
        )

        template_revision = None
        if template is not None:
            template_revision = await db.scalar(
                select(EntityProfileTemplateRevision).where(
                    EntityProfileTemplateRevision.novel_id == entity.novel_id,
                    EntityProfileTemplateRevision.template_id == template.id,
                    EntityProfileTemplateRevision.version_number
                    == template.version_number,
                )
            )
        metadata = {
            "profile_source": profile.source,
            "profile_confidence": profile.confidence,
            "profile_evidence_refs": profile.evidence_refs_json or [],
            "profile_extra": profile.extra_json or {},
            "profile_updated_at": (
                profile.updated_at.isoformat() if profile.updated_at else None
            ),
            "template_revision_id": (
                str(template_revision.id) if template_revision is not None else None
            ),
        }
        projected: list[DossierLegacyProfileField] = []
        legacy_values = {
            **(profile.data_json if isinstance(profile.data_json, dict) else {}),
            **(
                profile.extra_json.get("unmapped_generic", {})
                if isinstance(profile.extra_json, dict)
                and isinstance(profile.extra_json.get("unmapped_generic"), dict)
                else {}
            ),
        }
        for key, value in sorted(legacy_values.items(), key=lambda item: str(item[0])):
            if str(key) in shadowed_keys:
                continue
            field_definitions = definitions.get(str(key), [])
            raw = field_definitions[0] if len(field_definitions) == 1 else {}
            facing = None
            label = str(raw.get("label") or key)
            if raw:
                try:
                    candidate = DossierFacingRef.model_validate(raw.get("facing"))
                except (PydanticValidationError, TypeError, ValueError):
                    candidate = None
                if candidate is not None:
                    if candidate.kind == "core" and (
                        candidate.key in CORE_FACINGS.get(entity.entity_type, {})
                        or _facing_identity(candidate, entity.entity_type)[1]
                        in borrowed_core_keys
                    ):
                        facing = candidate
                        label = _core_facing_from_storage(
                            _facing_identity(candidate, entity.entity_type)[1]
                        )[1]
                    elif (
                        candidate.kind == "project"
                        and candidate.term_id in active_project_facings
                    ):
                        facing = candidate
                        label = active_project_facings[candidate.term_id]
            projected.append(
                DossierLegacyProfileField(
                    profile_id=profile.id,
                    profile_type=profile.profile_type,
                    profile_status=profile.status,
                    template_id=profile.template_id,
                    template_version_number=(
                        template.version_number if template is not None else None
                    ),
                    field_key=str(key),
                    label=label,
                    facing=facing,
                    value=value,
                    mapped=facing is not None,
                    source_metadata=metadata,
                )
            )
        for row in generic_unknown or []:
            field_key = (row.metadata_json or {}).get("generic_profile_field_key")
            if not isinstance(field_key, str) or not field_key:
                continue
            projected.append(
                DossierLegacyProfileField(
                    profile_id=profile.id,
                    profile_type=profile.profile_type,
                    profile_status=profile.status,
                    template_id=profile.template_id,
                    template_version_number=(
                        template.version_number if template is not None else None
                    ),
                    field_key=field_key,
                    label="未映射的旧档案字段",
                    value=_generic_profile_value(row),
                    mapped=False,
                    source_metadata={
                        **metadata,
                        "entry_id": str(row.id),
                        "revision_id": str(row.id),
                    },
                )
            )
        return projected

    async def _generic_profile_rows(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        *,
        lock: bool = False,
    ) -> dict[str, WorldObjectDossierEntry]:
        statement = select(WorldObjectDossierEntry).where(
            WorldObjectDossierEntry.novel_id == entity.novel_id,
            WorldObjectDossierEntry.entity_id == entity.id,
            WorldObjectDossierEntry.legacy_field_key.like(
                f"{GENERIC_PROFILE_FIELD_PREFIX}%"
            ),
        )
        if lock:
            statement = statement.with_for_update()
        rows = list((await db.scalars(statement)).all())
        latest: dict[str, WorldObjectDossierEntry] = {}
        for row in rows:
            key = (row.metadata_json or {}).get("generic_profile_field_key")
            if not isinstance(key, str) or not key:
                continue
            current = latest.get(key)
            if current is None or (
                row.revision_number,
                row.created_at,
                str(row.id),
            ) > (
                current.revision_number,
                current.created_at,
                str(current.id),
            ):
                latest[key] = row
        return latest

    async def generic_profile_projection(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        profile: GenericEntityProfile | None,
        *,
        visibility_filter: str | None = None,
        lock: bool = False,
    ) -> dict[str, Any]:
        """Return current legacy-shaped values from dossier revisions and unknown JSON."""
        if profile is None:
            return {"data_json": {}, "expected_revision": None, "fields": []}
        current: dict[str, Any] = {}
        if isinstance(profile.data_json, dict):
            current.update(profile.data_json)
        extra_unknown = (profile.extra_json or {}).get("unmapped_generic")
        if isinstance(extra_unknown, dict):
            current.update(extra_unknown)
        latest = await self._generic_profile_rows(db, entity, lock=lock)
        for key, row in latest.items():
            if row.status == "active":
                current[key] = _generic_profile_value(row)
            else:
                current.pop(key, None)

        fields: list[DossierLegacyProfileField] = []
        for key, row in sorted(latest.items()):
            if row.status != "active" or (
                visibility_filter is not None and row.visibility != visibility_filter
            ):
                continue
            value = _generic_profile_value(row)
            mapped = row.facing_key != GENERIC_UNKNOWN_FACING_KEY
            fields.append(
                DossierLegacyProfileField(
                    profile_id=profile.id,
                    profile_type=profile.profile_type,
                    profile_status=profile.status,
                    template_id=profile.template_id,
                    field_key=key,
                    label=(
                        _core_facing_from_storage(row.facing_key)[1]
                        if row.facing_kind == "core"
                        else "项目档案面向"
                    ),
                    facing=(
                        _core_facing_from_storage(row.facing_key)[0]
                        if row.facing_kind == "core"
                        and row.facing_key != GENERIC_UNKNOWN_FACING_KEY
                        else DossierFacingRef(
                            kind="project", term_id=row.vocabulary_term_id
                        )
                        if row.facing_kind == "project" and row.vocabulary_term_id
                        else None
                    ),
                    value=value,
                    mapped=mapped,
                    source_metadata={
                        "profile_source": profile.source,
                        "profile_confidence": profile.confidence,
                        "profile_evidence_refs": profile.evidence_refs_json or [],
                        "entry_id": str(row.id),
                        "revision_id": str(row.id),
                    },
                )
            )
        revision_payload = {
            "profile_type": profile.profile_type,
            "status": profile.status,
            "source": profile.source,
            "confidence": profile.confidence,
            "evidence_refs_json": profile.evidence_refs_json or [],
            "extra_json": profile.extra_json or {},
            "template_id": str(profile.template_id) if profile.template_id else None,
            "data_json": current,
            "dossier_revisions": sorted(
                (
                    str(row.id),
                    row.status,
                    row.revision_number,
                    row.facing_kind,
                    row.facing_key,
                )
                for row in latest.values()
            ),
        }
        revision = hashlib.sha256(_canonical_json(revision_payload).encode()).hexdigest()
        if visibility_filter is not None:
            current = {item.field_key: item.value for item in fields}
        return {
            "data_json": current,
            "expected_revision": revision,
            "fields": fields,
            "has_dossier_revisions": bool(latest),
            "has_current_dossier_state": any(
                row.status in {"active", "cleared"} for row in latest.values()
            ),
            "cleared_fields": sorted(
                key for key, row in latest.items() if row.status == "cleared"
            ),
        }

    async def _generic_template_facing(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        profile: GenericEntityProfile,
        field_key: str,
    ) -> tuple[str, str, uuid.UUID | None, str] | None:
        if profile.template_id is None:
            return None
        template = await db.scalar(
            select(EntityProfileTemplate).where(
                EntityProfileTemplate.novel_id == entity.novel_id,
                EntityProfileTemplate.id == profile.template_id,
                EntityProfileTemplate.profile_type == entity.entity_type,
                EntityProfileTemplate.status == "active",
            )
        )
        raw_fields = (
            (template.template_schema_json or {}).get("fields", [])
            if template is not None
            else []
        )
        matches = [
            raw
            for raw in raw_fields
            if isinstance(raw, dict) and raw.get("key") == field_key
        ]
        if len(matches) != 1:
            return None
        raw = matches[0]
        try:
            facing = DossierFacingRef.model_validate(raw.get("facing"))
            facing_key, label = await self._validate_facing(
                db, entity.novel_id, entity.entity_type, facing
            )
        except (PydanticValidationError, ValidationError, TypeError, ValueError):
            return None
        return facing.kind, facing_key, facing.term_id, label

    async def replace_generic_profile_data(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        profile: GenericEntityProfile,
        data_json: dict[str, Any] | None,
        *,
        expected_revision: str | None = None,
    ) -> str:
        """Write a legacy JSON replacement as per-field dossier revisions."""
        await require_active_project(db, str(entity.novel_id), allow_demo_readonly=False)
        before = await self.generic_profile_projection(db, entity, profile, lock=True)
        if (
            expected_revision is not None
            and expected_revision != before["expected_revision"]
        ):
            raise ConflictError(
                "通用档案已变化，请刷新后重试",
                code="world_profile_revision_stale",
            )
        desired = (
            {}
            if data_json is None
            else {str(key): value for key, value in data_json.items()}
        )
        if any(not key for key in desired):
            raise ValidationError("通用档案字段名不能为空")
        latest = await self._generic_profile_rows(db, entity, lock=True)
        current = dict(before["data_json"])
        for key in sorted(set(current) | set(desired)):
            wanted = desired.get(key)
            wants_value = key in desired and wanted is not None
            has_value = key in current
            previous = latest.get(key)
            if (
                has_value
                and wants_value
                and _canonical_json(current[key]) == _canonical_json(wanted)
            ):
                if previous is not None:
                    continue
                await self._append_generic_profile_revision(
                    db, entity, profile, key, current[key], previous=None
                )
                continue
            if previous is None and has_value:
                previous = await self._append_generic_profile_revision(
                    db, entity, profile, key, current[key], previous=None
                )
            if wants_value:
                await self._append_generic_profile_revision(
                    db, entity, profile, key, wanted, previous=previous
                )
            elif previous is not None and previous.status == "active":
                await self._append_generic_profile_revision(
                    db, entity, profile, key, None, previous=previous, cleared=True
                )
        profile.data_json = {}
        profile.extra_json = dict(profile.extra_json or {})
        profile.extra_json.pop("unmapped_generic", None)
        await db.flush()
        after = await self.generic_profile_projection(db, entity, profile, lock=True)
        return str(after["expected_revision"])

    async def _append_generic_profile_revision(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        profile: GenericEntityProfile,
        field_key: str,
        value: Any,
        *,
        previous: WorldObjectDossierEntry | None,
        cleared: bool = False,
    ) -> WorldObjectDossierEntry:
        mapping = await self._generic_template_facing(db, entity, profile, field_key)
        if previous is not None:
            facing_kind = previous.facing_kind
            facing_key = previous.facing_key
            vocabulary_term_id = previous.vocabulary_term_id
            entry_group_id = previous.entry_group_id
            revision_number = previous.revision_number + 1
            visibility = previous.visibility
            previous.status = "superseded"
        elif mapping is None:
            facing_kind = "core"
            facing_key = GENERIC_UNKNOWN_FACING_KEY
            vocabulary_term_id = None
            entry_group_id = uuid.uuid4()
            revision_number = 1
            visibility = "secret"
        else:
            facing_kind, facing_key, vocabulary_term_id, _label = mapping
            entry_group_id = uuid.uuid4()
            revision_number = 1
            visibility = "secret"
        profile_metadata = {
            "profile_type": profile.profile_type,
            "profile_status": profile.status,
            "source": profile.source,
            "confidence": profile.confidence,
            "evidence_refs_json": profile.evidence_refs_json or [],
        }
        row = await self._make_revision(
            db,
            previous,
            novel_id=entity.novel_id,
            entity_id=entity.id,
            entry_group_id=entry_group_id,
            revision_number=revision_number,
            facing_kind=facing_kind,
            facing_key=facing_key,
            vocabulary_term_id=vocabulary_term_id,
            legacy_field_key=(
                f"{GENERIC_PROFILE_FIELD_PREFIX}{hashlib.sha256(field_key.encode()).hexdigest()}"
            ),
            content=_display_value(value) if value is not None else "",
            tags=[],
            evidence=[],
            quote_text=None,
            visibility=visibility,
            validity=None,
            source="legacy_import",
            reason="legacy_profile_writeback",
            status="cleared" if cleared else "active",
            legacy_value_json=value,
            metadata_json={
                **(previous.metadata_json or {} if previous else {}),
                "generic_profile_field_key": field_key,
                "generic_profile_metadata": profile_metadata,
                "generic_profile_mapped": mapping is not None
                or bool(previous and previous.facing_key != GENERIC_UNKNOWN_FACING_KEY),
            },
        )
        return row

    async def history(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        *,
        entry_group_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> DossierHistoryResponse:
        entity = await self._entity(db, novel_id, entity_id)
        nid = parse_uuid(novel_id, "novel_id")
        page_limit = min(max(limit, 1), 500)
        page_offset = max(offset, 0)
        rows, total_count = await self.repo.list_history(
            db,
            nid,
            entity.id,
            entry_group_id=(
                parse_uuid(entry_group_id, "entry_group_id") if entry_group_id else None
            ),
            offset=page_offset,
            limit=page_limit,
        )
        labels = await self._labels(db, nid, rows)
        items = [
            _entry_response(
                row,
                facing_label=(
                    _core_facing_from_storage(row.facing_key)[1]
                    if row.facing_kind == "core"
                    else labels.get(row.vocabulary_term_id, "未知面向")
                ),
            )
            for row in rows
        ]
        return DossierHistoryResponse(
            entity_id=entity.id,
            offset=page_offset,
            limit=page_limit,
            entries=items,
            total_count=int(total_count or 0),
            omitted_count=max(0, int(total_count or 0) - len(items)),
        )

    async def _make_revision(
        self,
        db: AsyncSession,
        previous: WorldObjectDossierEntry | None,
        *,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        entry_group_id: uuid.UUID,
        revision_number: int,
        facing_kind: str,
        facing_key: str,
        vocabulary_term_id: uuid.UUID | None,
        legacy_field_key: str | None,
        story_field_key: str | None | object = _UNSET,
        content: str,
        tags: list[str],
        evidence: list[dict[str, Any]],
        quote_text: str | None,
        visibility: str,
        validity: DossierValidity | None,
        source: str,
        reason: str,
        status: str = "active",
        legacy_value_json: Any = None,
        metadata_json: dict[str, Any] | None = None,
        restored_from_id: uuid.UUID | None = None,
    ) -> WorldObjectDossierEntry:
        self._validate_legacy_content(legacy_field_key, content)
        if source not in DOSSIER_SOURCES:
            raise ValidationError("档案来源不在支持的来源类型中")
        if metadata_json is not None:
            revision_metadata = dict(metadata_json)
        elif previous is not None:
            revision_metadata = dict(previous.metadata_json or {})
        else:
            revision_metadata = {}
        row = WorldObjectDossierEntry(
            id=uuid.uuid4(),
            novel_id=novel_id,
            entity_id=entity_id,
            entry_group_id=entry_group_id,
            revision_number=revision_number,
            previous_revision_id=previous.id if previous else None,
            facing_kind=facing_kind,
            facing_key=facing_key,
            vocabulary_term_id=vocabulary_term_id,
            legacy_field_key=legacy_field_key,
            story_field_key=(
                previous.story_field_key
                if story_field_key is _UNSET and previous is not None
                else None
                if story_field_key is _UNSET
                else story_field_key
            ),
            content=content,
            tags_json=tags,
            legacy_value_json=legacy_value_json,
            metadata_json=revision_metadata,
            source=source,
            source_refs_json=evidence,
            quote_text=quote_text,
            visibility=visibility,
            status=status,
            **_validity_values(validity),
            revision_reason=reason,
            restored_from_id=restored_from_id,
        )
        return await self.repo.add_revision(db, row)

    async def create_entry(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        data: DossierEntryCreate,
        *,
        source: str = "author",
        source_metadata: dict[str, Any] | None = None,
        reason: str = "author_created",
        entry_group_id: uuid.UUID | None = None,
    ) -> DossierEntryResponse:
        entity = await self._entity(
            db, novel_id, entity_id, lock=True, require_canonical=True
        )
        nid = entity.novel_id
        facing_key, facing_label = await self._validate_facing(
            db, nid, entity.entity_type, data.facing, lock_template=True
        )
        self._validate_legacy_field(entity, data.facing, data.legacy_field_key)
        self._validate_legacy_content(data.legacy_field_key, data.content)
        self._validate_strong_legacy_value(
            entity,
            data.legacy_field_key,
            data.content,
            data.legacy_value,
            supplied="legacy_value" in data.model_fields_set,
        )
        self._validate_legacy_visibility(entity, data.legacy_field_key, data.visibility)
        await self._validate_story_field_key(db, entity, data.story_field_key)
        if data.legacy_field_key == "secret" and data.visibility != "secret":
            raise ValidationError("人物秘密档案必须保持秘密可见性")
        await self._validate_validity(db, nid, data.validity)
        row = await self._make_revision(
            db,
            None,
            novel_id=nid,
            entity_id=entity.id,
            entry_group_id=entry_group_id or uuid.uuid4(),
            revision_number=1,
            facing_kind=data.facing.kind,
            facing_key=facing_key,
            vocabulary_term_id=data.facing.term_id,
            legacy_field_key=data.legacy_field_key,
            story_field_key=data.story_field_key,
            content=data.content,
            tags=data.tags,
            evidence=[ref.model_dump(mode="json") for ref in data.evidence],
            quote_text=data.quote_text,
            visibility=data.visibility,
            validity=data.validity,
            source=source,
            reason=reason,
            metadata_json=source_metadata,
            legacy_value_json=data.legacy_value,
        )
        if data.legacy_field_key:
            await self._sync_legacy_storage(
                db,
                entity,
                data.legacy_field_key,
                data.content,
                data.legacy_value,
            )
        if data.facing.kind == "project":
            term, revision = await self._vocabulary_record(db, nid, data.facing.term_id)
            facing_label = revision.snapshot_json.get("name", facing_label)
        return _entry_response(row, facing_label=facing_label)

    async def preview_create_entry(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        data: DossierEntryCreate,
    ) -> dict[str, Any]:
        """Validate an author-confirmed create without changing World state."""
        entity = await self._entity(db, novel_id, entity_id, require_canonical=True)
        _facing_key, facing_label = await self._validate_facing(
            db, entity.novel_id, entity.entity_type, data.facing
        )
        self._validate_legacy_field(entity, data.facing, data.legacy_field_key)
        self._validate_legacy_content(data.legacy_field_key, data.content)
        self._validate_strong_legacy_value(
            entity,
            data.legacy_field_key,
            data.content,
            data.legacy_value,
            supplied="legacy_value" in data.model_fields_set,
        )
        self._validate_legacy_visibility(entity, data.legacy_field_key, data.visibility)
        await self._validate_story_field_key(db, entity, data.story_field_key)
        if data.legacy_field_key == "secret" and data.visibility != "secret":
            raise ValidationError("人物秘密档案必须保持秘密可见性")
        await self._validate_validity(db, entity.novel_id, data.validity)
        return {
            "target_key": f"world_dossier:{entity.id}",
            "entity_id": str(entity.id),
            "facing_label": facing_label,
            "legacy_field_key": data.legacy_field_key,
            "story_field_key": data.story_field_key,
            "content": data.content,
            "visibility": data.visibility,
            "validity": data.validity.model_dump(mode="json") if data.validity else None,
            "effect": "作者确认后新增一条可恢复档案记录。",
        }

    async def _active_entry(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        revision_id: str,
        *,
        lock: bool = False,
    ) -> WorldObjectDossierEntry:
        row = await self.repo.get_revision(
            db,
            entity.novel_id,
            entity.id,
            parse_uuid(revision_id, "revision_id"),
            for_update=lock,
        )
        if row is None:
            raise NotFoundError("当前档案条目不存在")
        if row.status != "active":
            raise ConflictError("档案已变化，请刷新后重试", code="dossier_revision_stale")
        return row

    async def preview_update_entry(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        revision_id: str,
        data: DossierEntryUpdate,
    ) -> dict[str, Any]:
        """Validate a revision CAS and return a write preview without mutation."""
        entity = await self._entity(db, novel_id, entity_id, require_canonical=True)
        row = await self._active_entry(db, entity, revision_id)
        if row.id != data.expected_revision_id:
            raise ConflictError("档案已变化，请刷新后重试", code="dossier_revision_stale")
        if row.facing_kind == "core":
            await self._validate_facing(
                db,
                entity.novel_id,
                entity.entity_type,
                DossierFacingRef(kind="core", key=row.facing_key),
            )
        values = self._updated_values(row, data)
        self._validate_legacy_content(row.legacy_field_key, values["content"])
        self._validate_strong_legacy_value(
            entity,
            row.legacy_field_key,
            values["content"],
            values["legacy_value"],
            supplied="legacy_value" in data.model_fields_set,
        )
        self._validate_legacy_visibility(
            entity, row.legacy_field_key, values["visibility"]
        )
        await self._validate_validity(db, entity.novel_id, values["validity"])
        await self._validate_story_field_key(db, entity, values["story_field_key"])
        return {
            "target_key": f"world_dossier:{entity.id}:{row.entry_group_id}",
            "entity_id": str(entity.id),
            "entry_group_id": str(row.entry_group_id),
            "revision_id": str(row.id),
            "before": {"content": row.content, "visibility": row.visibility},
            "after": {
                "content": values["content"],
                "tags": values["tags"],
                "visibility": values["visibility"],
                "story_field_key": values["story_field_key"],
            },
            "effect": "作者确认后追加修订；旧版本保留，可从历史恢复。",
        }

    @staticmethod
    def _updated_values(
        row: WorldObjectDossierEntry, data: DossierEntryUpdate
    ) -> dict[str, Any]:
        fields_set = data.model_fields_set
        content = row.content
        if "content" in fields_set:
            content = data.content or ""
            if not content.strip():
                content = ""
        tags = row.tags_json or []
        if "tags" in fields_set:
            tags = data.tags or []
        evidence = row.source_refs_json or []
        if "evidence" in fields_set:
            evidence = [item.model_dump(mode="json") for item in data.evidence or []]
        quote_text = row.quote_text
        if "quote_text" in fields_set:
            quote_text = data.quote_text
        visibility = row.visibility
        if "visibility" in fields_set:
            if data.visibility is None:
                raise ValidationError("档案可见性不能清空")
            visibility = data.visibility
        validity = data.validity if "validity" in fields_set else _validity_from_row(row)
        story_field_key = (
            data.story_field_key
            if "story_field_key" in fields_set
            else row.story_field_key
        )
        legacy_value = (
            data.legacy_value
            if "legacy_value" in fields_set
            else None
            if "content" in fields_set and content != row.content
            else row.legacy_value_json
        )
        if "legacy_value" in fields_set and data.legacy_value is not None:
            value_content = _display_value(data.legacy_value)
            if "content" in fields_set and content != value_content:
                raise ValidationError("结构化旧值与展示内容不一致")
            content = value_content
        return {
            "content": content,
            "tags": tags,
            "evidence": evidence,
            "quote_text": quote_text,
            "visibility": visibility,
            "validity": validity,
            "story_field_key": story_field_key,
            "legacy_value": legacy_value,
        }

    async def update_entry(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        revision_id: str,
        data: DossierEntryUpdate,
        *,
        source: str = "author",
        source_metadata: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> DossierEntryResponse:
        entity = await self._entity(
            db, novel_id, entity_id, lock=True, require_canonical=True
        )
        nid = entity.novel_id
        row = await self._active_entry(db, entity, revision_id, lock=True)
        if row.id != data.expected_revision_id:
            raise ConflictError("档案已变化，请刷新后重试", code="dossier_revision_stale")
        if row.facing_kind == "core":
            await self._validate_facing(
                db,
                entity.novel_id,
                entity.entity_type,
                DossierFacingRef(kind="core", key=row.facing_key),
                lock_template=True,
            )
        values = self._updated_values(row, data)
        self._validate_legacy_content(row.legacy_field_key, values["content"])
        self._validate_strong_legacy_value(
            entity,
            row.legacy_field_key,
            values["content"],
            values["legacy_value"],
            supplied="legacy_value" in data.model_fields_set,
        )
        self._validate_legacy_visibility(
            entity, row.legacy_field_key, values["visibility"]
        )
        clearing = not values["content"].strip()
        if clearing:
            values.update(
                content="",
                tags=[],
                evidence=[],
                quote_text=None,
            )
        if (
            values["content"] == row.content
            and values["tags"] == (row.tags_json or [])
            and values["evidence"] == (row.source_refs_json or [])
            and values["quote_text"] == row.quote_text
            and values["visibility"] == row.visibility
            and values["validity"] == _validity_from_row(row)
            and values["story_field_key"] == row.story_field_key
            and values["legacy_value"] == row.legacy_value_json
        ):
            if row.facing_kind == "project":
                _term, revision = await self._vocabulary_record(
                    db, nid, row.vocabulary_term_id
                )
                label = revision.snapshot_json.get("name", "未知面向")
            else:
                label = _core_facing_from_storage(row.facing_key)[1]
            return _entry_response(row, facing_label=label)
        await self._validate_validity(db, nid, values["validity"])
        await self._validate_story_field_key(db, entity, values["story_field_key"])
        if row.legacy_field_key == "secret" and values["visibility"] != "secret":
            raise ValidationError("人物秘密档案必须保持秘密可见性")
        if row.facing_kind == "project":
            term, vocabulary_revision = await self._vocabulary_record(
                db, nid, row.vocabulary_term_id
            )
            if term.status != "active" or term.kind != "dossier_facing":
                raise ConflictError("档案面向已停用，请刷新后重试")
            facing_label = vocabulary_revision.snapshot_json["name"]
        else:
            facing_label = _core_facing_from_storage(row.facing_key)[1]
        row.status = "superseded"
        new_row = await self._make_revision(
            db,
            row,
            novel_id=nid,
            entity_id=entity.id,
            entry_group_id=row.entry_group_id,
            revision_number=row.revision_number + 1,
            facing_kind=row.facing_kind,
            facing_key=row.facing_key,
            vocabulary_term_id=row.vocabulary_term_id,
            legacy_field_key=row.legacy_field_key,
            story_field_key=values["story_field_key"],
            content=values["content"],
            tags=values["tags"],
            evidence=values["evidence"],
            quote_text=values["quote_text"],
            visibility=values["visibility"],
            validity=values["validity"],
            source=source,
            reason=reason or ("author_cleared" if clearing else "author_edit"),
            status="cleared" if clearing else "active",
            legacy_value_json=values["legacy_value"],
            metadata_json=source_metadata,
        )
        await self._sync_legacy_storage(
            db,
            entity,
            row.legacy_field_key,
            None if clearing else new_row.content,
            new_row.legacy_value_json,
        )
        return _entry_response(new_row, facing_label=facing_label)

    async def preview_restore_entry(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        entry_group_id: str,
        data: DossierEntryRestore,
    ) -> dict[str, Any]:
        entity = await self._entity(db, novel_id, entity_id, require_canonical=True)
        group = parse_uuid(entry_group_id, "entry_group_id")
        rows = await self.repo.list_group(db, entity.novel_id, entity.id, group)
        selected = next((item for item in rows if item.id == data.revision_id), None)
        if selected is None:
            raise NotFoundError("档案历史版本不存在")
        if not selected.content.strip() or selected.status == "cleared":
            raise ValidationError("清除版本没有可恢复的档案内容")
        if selected.facing_kind == "core":
            await self._validate_facing(
                db,
                entity.novel_id,
                entity.entity_type,
                DossierFacingRef(kind="core", key=selected.facing_key),
            )
        if selected.facing_kind == "project":
            term, _revision = await self._vocabulary_record(
                db, entity.novel_id, selected.vocabulary_term_id
            )
            if term.status != "active" or term.kind != "dossier_facing":
                raise ConflictError("档案面向已停用，请刷新后重试")
        current = next((item for item in rows if item.status == "active"), None)
        if (current.id if current else None) != data.expected_current_revision_id:
            raise ConflictError("档案已变化，请刷新后重试", code="dossier_revision_stale")
        await self._validate_validity(db, entity.novel_id, _validity_from_row(selected))
        return {
            "target_key": f"world_dossier:{entity.id}:{group}",
            "entity_id": str(entity.id),
            "entry_group_id": str(group),
            "restore_revision_id": str(selected.id),
            "expected_current_revision_id": (
                str(data.expected_current_revision_id)
                if data.expected_current_revision_id
                else None
            ),
            "content": selected.content,
            "effect": "作者确认后追加恢复修订，原历史全部保留。",
        }

    async def restore_entry(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        entry_group_id: str,
        data: DossierEntryRestore,
        *,
        source: str = "author",
    ) -> DossierEntryResponse:
        entity = await self._entity(
            db, novel_id, entity_id, lock=True, require_canonical=True
        )
        nid = entity.novel_id
        group = parse_uuid(entry_group_id, "entry_group_id")
        rows = await self.repo.list_group(db, nid, entity.id, group, for_update=True)
        selected = next((item for item in rows if item.id == data.revision_id), None)
        if selected is None:
            raise NotFoundError("档案历史版本不存在")
        if not selected.content.strip() or selected.status == "cleared":
            raise ValidationError("清除版本没有可恢复的档案内容")
        if selected.facing_kind == "core":
            await self._validate_facing(
                db,
                nid,
                entity.entity_type,
                DossierFacingRef(kind="core", key=selected.facing_key),
                lock_template=True,
            )
        await self._validate_validity(db, nid, _validity_from_row(selected))
        if selected.facing_kind == "project":
            term, _revision = await self._vocabulary_record(
                db, nid, selected.vocabulary_term_id
            )
            if term.status != "active" or term.kind != "dossier_facing":
                raise ConflictError("档案面向已停用，请刷新后重试")
        current = next((item for item in rows if item.status == "active"), None)
        actual_current = current.id if current else None
        if actual_current != data.expected_current_revision_id:
            raise ConflictError("档案已变化，请刷新后重试", code="dossier_revision_stale")
        previous = current or rows[-1]
        if current:
            current.status = "superseded"
        restored = await self._make_revision(
            db,
            previous,
            novel_id=nid,
            entity_id=entity.id,
            entry_group_id=group,
            revision_number=previous.revision_number + 1,
            facing_kind=selected.facing_kind,
            facing_key=selected.facing_key,
            vocabulary_term_id=selected.vocabulary_term_id,
            legacy_field_key=selected.legacy_field_key,
            story_field_key=selected.story_field_key,
            content=selected.content,
            tags=selected.tags_json or [],
            evidence=selected.source_refs_json or [],
            quote_text=selected.quote_text,
            visibility=selected.visibility,
            validity=_validity_from_row(selected),
            source=source,
            reason="author_restore",
            legacy_value_json=selected.legacy_value_json,
            metadata_json=dict(selected.metadata_json or {}),
            restored_from_id=selected.id,
        )
        await self._sync_legacy_storage(
            db,
            entity,
            restored.legacy_field_key,
            restored.content,
            restored.legacy_value_json,
        )
        if restored.facing_kind == "project":
            _term, revision = await self._vocabulary_record(
                db, nid, restored.vocabulary_term_id
            )
            label = revision.snapshot_json["name"]
        else:
            label = _core_facing_from_storage(restored.facing_key)[1]
        return _entry_response(restored, facing_label=label)

    async def sync_character_legacy_field(
        self,
        db: AsyncSession,
        character: Character,
        field: str,
        value: Any,
        *,
        force_create: bool = False,
    ) -> None:
        mapping = LEGACY_CHARACTER_FACINGS.get(field)
        if mapping is None:
            return
        value_text = _display_value(value) if value is not None else None
        active_rows = await self.repo.list_active_legacy_field(
            db,
            character.novel_id,
            character.entity_id,
            field,
            for_update=True,
        )
        current = (
            self._legacy_value(field, active_rows)
            if active_rows
            else getattr(character, field)
        )
        if current == value and (active_rows or not force_create):
            return
        latest = active_rows[-1] if active_rows else None
        if latest is None:
            latest = await self.repo.latest_legacy_field(
                db,
                character.novel_id,
                character.entity_id,
                field,
                for_update=True,
            )
        for active in active_rows:
            active.status = "superseded"
        if value is None or value == "":
            if latest is not None or current is not None:
                await self._make_revision(
                    db,
                    latest,
                    novel_id=character.novel_id,
                    entity_id=character.entity_id,
                    entry_group_id=latest.entry_group_id if latest else uuid.uuid4(),
                    revision_number=latest.revision_number + 1 if latest else 1,
                    facing_kind="core",
                    facing_key=mapping[0],
                    vocabulary_term_id=None,
                    legacy_field_key=field,
                    content="",
                    tags=[],
                    evidence=[],
                    quote_text=None,
                    visibility="secret" if field == "secret" else "public",
                    validity=None,
                    source="author",
                    reason="legacy_field_cleared",
                    status="cleared",
                    legacy_value_json=None,
                )
            return
        group = latest.entry_group_id if latest else uuid.uuid4()
        await self._make_revision(
            db,
            latest,
            novel_id=character.novel_id,
            entity_id=character.entity_id,
            entry_group_id=group,
            revision_number=latest.revision_number + 1 if latest else 1,
            facing_kind="core",
            facing_key=mapping[0],
            vocabulary_term_id=None,
            legacy_field_key=field,
            content=value_text,
            tags=[],
            evidence=[],
            quote_text=None,
            visibility="secret" if field == "secret" else "public",
            validity=None,
            source="author",
            reason="legacy_api_writeback",
            legacy_value_json=value if isinstance(value, (list, dict)) else None,
        )

    @staticmethod
    def _legacy_value(field: str, rows: list[WorldObjectDossierEntry]) -> Any:
        values = [
            row.legacy_value_json if row.legacy_value_json is not None else row.content
            for row in rows
        ]
        if field == "behavior_rules":
            merged: list[dict] = []
            for value in values:
                if isinstance(value, list):
                    merged.extend(item for item in value if isinstance(item, dict))
                elif isinstance(value, dict):
                    merged.append(value)
                elif value:
                    merged.append({"description": _display_value(value)})
            return merged
        if len(values) == 1:
            return values[0]
        return "\n".join(
            display for value in values if (display := _display_value(value)).strip()
        )

    async def legacy_character_values(
        self,
        db: AsyncSession,
        novel_id: str,
        characters: list[Character],
    ) -> dict[uuid.UUID, dict[str, Any]]:
        if not characters:
            return {}
        ids = {item.entity_id for item in characters}
        rows = await self.repo.list_active_legacy_character_fields(
            db,
            parse_uuid(novel_id, "novel_id"),
            ids,
            set(LEGACY_CHARACTER_FACINGS),
        )
        result = {item.entity_id: {} for item in characters}
        grouped: dict[tuple[uuid.UUID, str], list[WorldObjectDossierEntry]] = {}
        for row in rows:
            if row.legacy_field_key:
                grouped.setdefault((row.entity_id, row.legacy_field_key), []).append(row)
        for (entity_id, field), field_rows in grouped.items():
            result[entity_id][field] = self._legacy_value(field, field_rows)
        return result

    async def _sync_legacy_storage(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        legacy_field_key: str | None,
        content: str | None,
        legacy_value: Any,
    ) -> None:
        if not legacy_field_key:
            return
        value = legacy_value if legacy_value is not None else content
        self._validate_legacy_content(legacy_field_key, value)
        strong = self._strong_legacy_binding(entity, legacy_field_key)
        if strong is not None:
            binding, field, _facing = strong
            is_json = field.endswith("_json")
            if is_json:
                if content and not isinstance(legacy_value, list):
                    raise ValidationError("结构化旧字段必须提供原类型数组值")
                stored_value = legacy_value if isinstance(legacy_value, list) else []
            elif field == "risk_level":
                stored_value = content or "medium"
            else:
                stored_value = content or None
            profile = await db.scalar(
                select(binding.model)
                .where(
                    binding.model.novel_id == entity.novel_id,
                    binding.model.entity_id == entity.id,
                )
                .with_for_update()
            )
            if profile is None:
                profile = binding.model(
                    novel_id=entity.novel_id,
                    entity_id=entity.id,
                    status="canonical",
                    source="author",
                )
                db.add(profile)
            setattr(profile, field, stored_value)
            profile.updated_at = datetime.now(UTC)
            return
        if (
            entity.entity_type == "character"
            and legacy_field_key in LEGACY_CHARACTER_FACINGS
        ):
            character = (
                await db.execute(
                    select(Character)
                    .where(
                        Character.novel_id == entity.novel_id,
                        Character.entity_id == entity.id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if character is None:
                raise NotFoundError("Character profile not found")
            setattr(character, legacy_field_key, value)
            character.updated_at = datetime.now(UTC)
            return
        entity_field = next(
            (
                field
                for field, (
                    _facing,
                    _label,
                    _visibility,
                ) in LEGACY_CORE_ENTITY_FACINGS.items()
                if field == legacy_field_key
            ),
            None,
        )
        if entity_field:
            setattr(entity, entity_field, value)
            entity.updated_at = datetime.now(UTC)

    async def upsert_template(
        self,
        db: AsyncSession,
        novel_id: str,
        profile_type: str,
        data: DossierTemplateUpsert | DossierTemplateAuthorUpsert,
        *,
        source: str = "author",
    ) -> DossierTemplateResponse | DossierTemplateAuthorResponse:
        await require_active_project(db, novel_id, allow_demo_readonly=False)
        if source not in DOSSIER_SOURCES:
            raise ValidationError("档案模板来源不在支持的来源类型中")
        nid = parse_uuid(novel_id, "novel_id")
        normalized_type = profile_type.strip().lower()
        if not normalized_type or len(normalized_type) > 64:
            raise ValidationError("对象类型不能为空")
        template = (
            await db.execute(
                select(EntityProfileTemplate)
                .where(
                    EntityProfileTemplate.novel_id == nid,
                    EntityProfileTemplate.profile_type == normalized_type,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        is_author_request = isinstance(data, DossierTemplateAuthorUpsert)
        if is_author_request:
            borrowed_facings = list(data.borrowed_facings)
            borrowed_identities = _validate_borrowed_facing_refs(
                normalized_type, borrowed_facings
            )
        else:
            borrowed_identities = (
                await self._template_borrowed_facings(db, nid, normalized_type)
                if template is not None
                else set()
            )
            borrowed_facings = [
                DossierFacingRef(
                    kind="core", key=_stored_core_facing_key(source_type, key)
                )
                for source_type, key in sorted(borrowed_identities)
            ]
        if template is not None:
            current_borrowed = await self._template_borrowed_facings(
                db, nid, normalized_type
            )
            removed_borrowed = current_borrowed - borrowed_identities
            if removed_borrowed:
                removed_keys = [
                    _stored_core_facing_key(source_type, key)
                    for source_type, key in removed_borrowed
                ]
                active_count = await db.scalar(
                    select(func.count(WorldObjectDossierEntry.id))
                    .join(
                        CoreEntity,
                        (CoreEntity.novel_id == WorldObjectDossierEntry.novel_id)
                        & (CoreEntity.id == WorldObjectDossierEntry.entity_id),
                    )
                    .where(
                        WorldObjectDossierEntry.novel_id == nid,
                        WorldObjectDossierEntry.facing_kind == "core",
                        WorldObjectDossierEntry.facing_key.in_(removed_keys),
                        WorldObjectDossierEntry.status == "active",
                        CoreEntity.entity_type == normalized_type,
                    )
                )
                if active_count:
                    raise ValidationError(
                        "模板仍有活动档案使用该借用面向；请先清除或改写条目"
                    )
        seen = set()
        seen_keys = set()
        submitted_key_facings: dict[str, tuple[str, str]] = {}
        for item in data.fields:
            facing_key, _label = await self._validate_facing(
                db,
                nid,
                normalized_type,
                item.facing,
                declared_borrowed=borrowed_identities,
            )
            identity = (item.facing.kind, facing_key)
            if identity in seen:
                raise ValidationError("模板不能重复登记同一面向")
            seen.add(identity)
            if item.key is not None:
                if item.key in seen_keys:
                    raise ValidationError("模板字段 key 不能重复")
                seen_keys.add(item.key)
                submitted_key_facings[item.key] = identity
        if normalized_type in SUPPORTED_ENTITY_TYPES and data.state_fields:
            raise ValidationError("内置对象类型不能声明自定义文字状态字段")
        state_field_keys = [item.key for item in data.state_fields]
        if len(state_field_keys) != len(set(state_field_keys)):
            raise ValidationError("文字状态字段 key 不能重复")
        snapshot = {
            "format_version": 2 if borrowed_facings else 1,
            "fields": [field.model_dump(mode="json") for field in data.fields],
            "borrowed_facings": [
                field.model_dump(mode="json") for field in borrowed_facings
            ],
            "state_fields": [
                field.model_dump(mode="json") for field in data.state_fields
            ],
            "display_schema": data.display_schema,
        }

        def response(
            revision_id: uuid.UUID,
            version_number: int,
            display_schema: dict[str, Any],
            updated_at: datetime | None,
        ) -> DossierTemplateResponse | DossierTemplateAuthorResponse:
            values = {
                "profile_type": normalized_type,
                "template_id": template.id,
                "revision_id": revision_id,
                "version_number": version_number,
                "fields": data.fields,
                "state_fields": data.state_fields,
                "display_schema": display_schema,
                "updated_at": updated_at,
            }
            if is_author_request:
                return DossierTemplateAuthorResponse(
                    **values, borrowed_facings=borrowed_facings
                )
            return DossierTemplateResponse(**values)

        if template is not None and submitted_key_facings:
            revisions = (
                await db.scalars(
                    select(EntityProfileTemplateRevision).where(
                        EntityProfileTemplateRevision.novel_id == nid,
                        EntityProfileTemplateRevision.template_id == template.id,
                    )
                )
            ).all()
            history_fields = [
                *(template.template_schema_json or {}).get("fields", []),
                *(
                    field
                    for revision in revisions
                    for field in (revision.snapshot_json or {}).get("fields", [])
                ),
            ]
            historical_key_facings: dict[str, tuple[str, str]] = {}
            for raw in history_fields:
                if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
                    continue
                try:
                    previous_facing = DossierFacingRef.model_validate(raw.get("facing"))
                except (PydanticValidationError, TypeError, ValueError):
                    continue
                previous_key = _facing_identity(previous_facing, normalized_type)[1]
                historical_key_facings.setdefault(
                    raw["key"], (previous_facing.kind, previous_key)
                )
            for field_key, identity in submitted_key_facings.items():
                previous = historical_key_facings.get(field_key)
                if previous is not None and previous != identity:
                    raise ValidationError(
                        "模板字段 key 已绑定其他面向；请使用新 key 保留旧数据映射"
                    )
        if template is None:
            if data.expected_version_number is not None:
                raise ConflictError("模板不存在，请刷新后重试")
            template = EntityProfileTemplate(
                novel_id=nid,
                profile_type=normalized_type,
                template_schema_json={
                    "format_version": snapshot["format_version"],
                    "fields": snapshot["fields"],
                    "borrowed_facings": snapshot["borrowed_facings"],
                    "state_fields": snapshot["state_fields"],
                },
                display_schema_json=data.display_schema,
                version_number=1,
                status="active",
            )
            db.add(template)
            await db.flush()
            revision_number = 1
        else:
            if data.expected_version_number != template.version_number:
                raise ConflictError(
                    "模板已变化，请刷新后重试", code="dossier_template_stale"
                )
            current = await db.scalar(
                select(EntityProfileTemplateRevision).where(
                    EntityProfileTemplateRevision.novel_id == nid,
                    EntityProfileTemplateRevision.template_id == template.id,
                    EntityProfileTemplateRevision.version_number
                    == template.version_number,
                )
            )
            if (
                template.template_schema_json.get("fields", []) == snapshot["fields"]
                and template.template_schema_json.get("state_fields", [])
                == snapshot["state_fields"]
                and template.template_schema_json.get("borrowed_facings", [])
                == snapshot["borrowed_facings"]
                and template.display_schema_json == data.display_schema
            ):
                if current is None:
                    raise ConflictError("模板当前修订缺失，请核对数据")
                return response(
                    current.id,
                    template.version_number,
                    template.display_schema_json or {},
                    template.updated_at,
                )
            revision_number = template.version_number + 1
            template.template_schema_json = {
                "format_version": snapshot["format_version"],
                "fields": snapshot["fields"],
                "borrowed_facings": snapshot["borrowed_facings"],
                "state_fields": snapshot["state_fields"],
            }
            template.display_schema_json = data.display_schema
            template.version_number = revision_number
            template.updated_at = datetime.now(UTC)
        digest = hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()
        revision = EntityProfileTemplateRevision(
            id=uuid.uuid4(),
            novel_id=nid,
            template_id=template.id,
            version_number=revision_number,
            snapshot_json=snapshot,
            revision_digest=digest,
            revision_reason="author_edit",
            created_by=source,
        )
        db.add(revision)
        await db.flush()
        return response(
            revision.id, revision_number, data.display_schema, template.updated_at
        )

    async def preview_template_upsert(
        self,
        db: AsyncSession,
        novel_id: str,
        profile_type: str,
        data: DossierTemplateUpsert | DossierTemplateAuthorUpsert,
    ) -> dict[str, Any]:
        """Validate a template edit and return a preview without changing it."""
        nid = parse_uuid(novel_id, "novel_id")
        normalized_type = profile_type.strip().lower()
        if not normalized_type or len(normalized_type) > 64:
            raise ValidationError("对象类型不能为空")
        template = await db.scalar(
            select(EntityProfileTemplate).where(
                EntityProfileTemplate.novel_id == nid,
                EntityProfileTemplate.profile_type == normalized_type,
            )
        )
        is_author_request = isinstance(data, DossierTemplateAuthorUpsert)
        if is_author_request:
            borrowed_facings = list(data.borrowed_facings)
            borrowed_identities = _validate_borrowed_facing_refs(
                normalized_type, borrowed_facings
            )
        else:
            borrowed_identities = (
                await self._template_borrowed_facings(db, nid, normalized_type)
                if template is not None
                else set()
            )
            borrowed_facings = [
                DossierFacingRef(
                    kind="core", key=_stored_core_facing_key(source_type, key)
                )
                for source_type, key in sorted(borrowed_identities)
            ]
        identities = set()
        for item in data.fields:
            facing_key, _label = await self._validate_facing(
                db,
                nid,
                normalized_type,
                item.facing,
                declared_borrowed=borrowed_identities,
            )
            identity = (item.facing.kind, facing_key)
            if identity in identities:
                raise ValidationError("模板不能重复登记同一面向")
            identities.add(identity)
        state_field_keys = [item.key for item in data.state_fields]
        if len(state_field_keys) != len(set(state_field_keys)):
            raise ValidationError("文字状态字段 key 不能重复")
        if normalized_type in SUPPORTED_ENTITY_TYPES and data.state_fields:
            raise ValidationError("内置对象类型不能声明自定义文字状态字段")
        if template is None:
            if data.expected_version_number is not None:
                raise ConflictError("模板不存在，请刷新后重试")
            current_version = None
        else:
            if data.expected_version_number != template.version_number:
                raise ConflictError(
                    "模板已变化，请刷新后重试", code="dossier_template_stale"
                )
            current_version = template.version_number
        after = {
            "fields": [item.model_dump(mode="json") for item in data.fields],
            "borrowed_facings": [
                item.model_dump(mode="json") for item in borrowed_facings
            ],
            "state_fields": [item.model_dump(mode="json") for item in data.state_fields],
            "display_schema": data.display_schema,
        }
        current_snapshot = (
            {
                "fields": (template.template_schema_json or {}).get("fields", []),
                "state_fields": (template.template_schema_json or {}).get(
                    "state_fields", []
                ),
                "borrowed_facings": (template.template_schema_json or {}).get(
                    "borrowed_facings", []
                ),
                "display_schema": template.display_schema_json or {},
            }
            if template is not None
            else None
        )
        return {
            "target_key": f"world_dossier_template:{nid}:{normalized_type}",
            "profile_type": normalized_type,
            "expected_version_number": current_version,
            "before": current_snapshot,
            "after": after,
            "effect": "作者确认后追加模板修订；相同内容不新增版本。",
        }

    async def get_template(
        self,
        db: AsyncSession,
        novel_id: str,
        profile_type: str,
        *,
        include_author_fields: bool = False,
    ) -> DossierTemplateResponse | DossierTemplateAuthorResponse:
        nid = parse_uuid(novel_id, "novel_id")
        normalized_type = profile_type.strip().lower()
        template = (
            await db.execute(
                select(EntityProfileTemplate).where(
                    EntityProfileTemplate.novel_id == nid,
                    EntityProfileTemplate.profile_type == normalized_type,
                )
            )
        ).scalar_one_or_none()
        if template is None:
            raise NotFoundError("档案模板不存在")
        revision = await db.scalar(
            select(EntityProfileTemplateRevision).where(
                EntityProfileTemplateRevision.novel_id == nid,
                EntityProfileTemplateRevision.template_id == template.id,
                EntityProfileTemplateRevision.version_number == template.version_number,
            )
        )
        if revision is None:
            raise ConflictError("模板当前修订缺失，请核对数据")
        fields = [
            DossierTemplateField.model_validate(item)
            for item in (revision.snapshot_json.get("fields") or [])
        ]
        state_fields = [
            DossierStateField.model_validate(item)
            for item in (revision.snapshot_json.get("state_fields") or [])
        ]
        borrowed_facings = [
            DossierFacingRef.model_validate(item)
            for item in (revision.snapshot_json.get("borrowed_facings") or [])
        ]
        values = {
            "profile_type": normalized_type,
            "template_id": template.id,
            "revision_id": revision.id,
            "version_number": revision.version_number,
            "fields": fields,
            "state_fields": state_fields,
            "display_schema": revision.snapshot_json.get("display_schema", {}),
            "updated_at": template.updated_at,
        }
        if include_author_fields:
            return DossierTemplateAuthorResponse(
                **values, borrowed_facings=borrowed_facings
            )
        return DossierTemplateResponse(**values)

    async def require_custom_text_state_field(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        field_key: str,
        expected_version_number: int,
    ) -> dict[str, Any]:
        """Resolve an author write against the current World declaration.

        Story owns the resulting value. World only verifies that the canonical
        custom object and the exact field declaration still match the author's
        submitted template revision.
        """
        entity = await self._entity(
            db, novel_id, entity_id, lock=True, require_canonical=True
        )
        if entity.entity_type in SUPPORTED_ENTITY_TYPES:
            raise ValidationError("内置对象类型不接受自定义文字状态字段")
        template = await db.scalar(
            select(EntityProfileTemplate).where(
                EntityProfileTemplate.novel_id == entity.novel_id,
                EntityProfileTemplate.profile_type == entity.entity_type,
                EntityProfileTemplate.status == "active",
            )
        )
        if template is None:
            raise NotFoundError("该自定义对象类型尚未声明文字状态字段")
        if template.version_number != expected_version_number:
            raise ConflictError(
                "对象类型模板已变化，请重新读取后核对状态字段",
                code="dossier_template_stale",
            )
        revision = await db.scalar(
            select(EntityProfileTemplateRevision).where(
                EntityProfileTemplateRevision.novel_id == entity.novel_id,
                EntityProfileTemplateRevision.template_id == template.id,
                EntityProfileTemplateRevision.version_number == template.version_number,
            )
        )
        if revision is None:
            raise ConflictError("对象类型模板当前修订缺失，请核对数据")
        fields = [
            DossierStateField.model_validate(item)
            for item in (revision.snapshot_json or {}).get("state_fields", [])
        ]
        field = next((item for item in fields if item.key == field_key), None)
        if field is None:
            raise ValidationError("该文字状态字段已从对象类型模板移除")
        return {
            "entity_id": str(entity.id),
            "entity_type": entity.entity_type,
            "entity_name": entity.name,
            "template_id": str(template.id),
            "template_version_number": template.version_number,
            "field": field.model_dump(mode="json"),
        }

    async def template_history(
        self, db: AsyncSession, novel_id: str, profile_type: str
    ) -> DossierTemplateHistoryResponse:
        template = await db.scalar(
            select(EntityProfileTemplate).where(
                EntityProfileTemplate.novel_id == parse_uuid(novel_id, "novel_id"),
                EntityProfileTemplate.profile_type == profile_type.strip().lower(),
            )
        )
        if template is None:
            raise NotFoundError("档案模板不存在")
        revisions = list(
            (
                await db.execute(
                    select(EntityProfileTemplateRevision)
                    .where(
                        EntityProfileTemplateRevision.novel_id == template.novel_id,
                        EntityProfileTemplateRevision.template_id == template.id,
                    )
                    .order_by(EntityProfileTemplateRevision.version_number.desc())
                )
            )
            .scalars()
            .all()
        )
        return DossierTemplateHistoryResponse(
            profile_type=template.profile_type,
            items=[
                {
                    "revision_id": str(row.id),
                    "version_number": row.version_number,
                    "revision_digest": row.revision_digest,
                    "revision_reason": row.revision_reason,
                    "snapshot": row.snapshot_json,
                    "created_at": row.created_at.isoformat(),
                }
                for row in revisions
            ],
            total_count=len(revisions),
        )


__all__ = [
    "CORE_FACINGS",
    "LEGACY_CHARACTER_FACINGS",
    "WorldObjectDossierService",
]
