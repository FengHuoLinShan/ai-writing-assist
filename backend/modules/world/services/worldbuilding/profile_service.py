"""Worldbuilding profile service."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from modules.world.authority_schemas import (
    EntityProfileFieldSchemaV1,
    EntityProfileRelationSchemaV1,
    EntityProfileTemplateAdoptRequest,
    EntityProfileTemplateCreateRequest,
    EntityProfileTemplateResponse,
    EntityProfileTemplateRevisionCreateRequest,
    TypedScalarStatementV1,
)
from modules.world.models import (
    CoreEntity,
    EntityProfileTemplate,
    EntityProfileTemplateRevision,
    GenericEntityProfile,
)
from modules.world.schemas import (
    WorldProfileResponse,
    WorldProfileUpsertRequest,
)
from modules.world.services.worldbuilding.shared import PROFILE_REGISTRY, ProfileBinding
from modules.world.services.worldbuilding.world_authority_service import (
    canonical_json_bytes,
)
from shared.utils import parse_uuid


class WorldProfileService:
    async def create_template(
        self,
        db: AsyncSession,
        data: EntityProfileTemplateCreateRequest,
    ) -> EntityProfileTemplateResponse:
        existing = await db.scalar(
            select(EntityProfileTemplate).where(
                EntityProfileTemplate.novel_id == data.novel_id,
                EntityProfileTemplate.profile_type == data.profile_type,
            )
        )
        if existing is not None:
            raise ValidationError("Profile template type already exists")
        schema, display = self._template_payload(data.fields, data.relations)
        template = EntityProfileTemplate(
            novel_id=data.novel_id,
            profile_type=data.profile_type,
            template_schema_json=schema,
            display_schema_json=display,
            status="draft",
        )
        db.add(template)
        await db.flush()
        revision = await self._seal_template_revision(db, template, version_number=1)
        return self._template_response(template, revision)

    async def add_template_revision(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
        data: EntityProfileTemplateRevisionCreateRequest,
    ) -> EntityProfileTemplateResponse:
        template = await self._get_template(db, novel_id, template_id, lock=True)
        version = (
            await db.scalar(
                select(func.max(EntityProfileTemplateRevision.version_number)).where(
                    EntityProfileTemplateRevision.template_id == template.id
                )
            )
            or 0
        ) + 1
        schema, display = self._template_payload(data.fields, data.relations)
        template.template_schema_json = schema
        template.display_schema_json = display
        template.status = "draft"
        revision = await self._seal_template_revision(
            db, template, version_number=version
        )
        return self._template_response(template, revision)

    async def adopt_template(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
        data: EntityProfileTemplateAdoptRequest,
    ) -> EntityProfileTemplateResponse:
        template = await self._get_template(db, novel_id, template_id, lock=True)
        revision = await db.get(EntityProfileTemplateRevision, data.revision_id)
        if (
            revision is None
            or revision.novel_id != template.novel_id
            or revision.template_id != template.id
        ):
            raise NotFoundError("Profile template revision not found")
        template.template_schema_json = revision.template_schema_json
        template.display_schema_json = revision.display_schema_json
        template.status = "canonical"
        await db.flush()
        return self._template_response(template, revision)

    async def list_profiles(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[WorldProfileResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        entities_stmt = select(CoreEntity).where(CoreEntity.novel_id == nid)
        if entity_type:
            entities_stmt = entities_stmt.where(CoreEntity.entity_type == entity_type)
        if status:
            entities_stmt = entities_stmt.where(CoreEntity.status == status)
        total = (
            await db.execute(select(func.count()).select_from(entities_stmt.subquery()))
        ).scalar_one()
        result = await db.execute(
            entities_stmt.order_by(CoreEntity.name).offset(skip).limit(limit)
        )
        entities = list(result.scalars().all())
        return [await self._profile_for_entity(db, entity) for entity in entities], total

    async def get_profile(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
    ) -> WorldProfileResponse:
        entity = await self._get_entity(db, novel_id, entity_id)
        return await self._profile_for_entity(db, entity)

    async def upsert_profile(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        data: WorldProfileUpsertRequest,
    ) -> WorldProfileResponse:
        entity = await self._get_entity(db, novel_id, entity_id, lock=True)
        if entity.entity_type in PROFILE_REGISTRY:
            await self._ensure_no_generic(db, entity, lock=True)
            profile = await self._upsert_strong(db, entity, data, lock=True)
        else:
            profile = await self._upsert_generic(db, entity, data, lock=True)
        await db.flush()
        from modules.world.services.worldbuilding.synopsis_invalidation import (
            mark_synopsis_source_changed,
        )

        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="profile",
            source_id=entity_id,
        )
        return self._profile_response(entity, profile)

    async def migrate_generic_to_strong(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
    ) -> WorldProfileResponse:
        entity = await self._get_entity(db, novel_id, entity_id, lock=True)
        if entity.entity_type not in PROFILE_REGISTRY:
            raise ValidationError("Entity type has no strong profile table")
        generic = await self._get_generic(db, entity, lock=True)
        if generic is None:
            raise NotFoundError("Generic profile not found")
        binding = PROFILE_REGISTRY[entity.entity_type]
        profile = await self._get_strong(db, entity, binding, lock=True)
        if profile is None:
            profile = binding.model(
                novel_id=entity.novel_id,
                entity_id=entity.id,
                status="draft",
                source=generic.source,
                confidence=generic.confidence,
                evidence_refs_json=generic.evidence_refs_json or [],
                extra_json={
                    **(generic.extra_json or {}),
                    "unmapped_generic": generic.data_json or {},
                },
            )
            db.add(profile)
        generic.status = "migrated"
        await db.flush()
        from modules.world.services.worldbuilding.synopsis_invalidation import (
            mark_synopsis_source_changed,
        )

        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="profile",
            source_id=entity_id,
        )
        return self._profile_response(entity, profile)

    async def _get_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        *,
        lock: bool = False,
    ) -> CoreEntity:
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        stmt = select(CoreEntity).where(
            CoreEntity.id == eid,
            CoreEntity.novel_id == nid,
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        result = await db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity is None:
            raise NotFoundError("Entity not found in this novel")
        return entity

    async def _ensure_no_generic(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        *,
        lock: bool = False,
    ) -> None:
        generic = await self._get_generic(db, entity, lock=lock)
        if generic and generic.status != "migrated":
            raise ValidationError(
                "Strong profile requires migrating existing generic profile first",
            )

    async def _get_generic(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        *,
        lock: bool = False,
    ) -> GenericEntityProfile | None:
        stmt = select(GenericEntityProfile).where(
            GenericEntityProfile.novel_id == entity.novel_id,
            GenericEntityProfile.entity_id == entity.id,
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_strong(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        binding: ProfileBinding,
        *,
        lock: bool = False,
    ):
        stmt = select(binding.model).where(
            binding.model.novel_id == entity.novel_id,
            binding.model.entity_id == entity.id,
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _upsert_strong(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        data: WorldProfileUpsertRequest,
        *,
        lock: bool = False,
    ):
        binding = PROFILE_REGISTRY[entity.entity_type]
        profile = await self._get_strong(db, entity, binding, lock=lock)
        if profile is None:
            profile = binding.model(novel_id=entity.novel_id, entity_id=entity.id)
            db.add(profile)
        payload = data.model_dump(exclude_unset=True)
        for field in (
            "status",
            "source",
            "confidence",
            "evidence_refs_json",
            "extra_json",
            *binding.fields,
        ):
            if field in payload and payload[field] is not None:
                setattr(profile, field, payload[field])
        return profile

    async def _upsert_generic(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        data: WorldProfileUpsertRequest,
        *,
        lock: bool = False,
    ) -> GenericEntityProfile:
        if entity.entity_type in PROFILE_REGISTRY:
            raise ValidationError("Strong profile entity cannot create generic profile")
        profile = await self._get_generic(db, entity, lock=lock)
        is_new = profile is None
        if profile is None:
            template_revision = await self._active_template_revision(db, entity)
            profile = GenericEntityProfile(
                novel_id=entity.novel_id,
                entity_id=entity.id,
                profile_type=entity.entity_type,
                template_id=(
                    template_revision.template_id if template_revision else None
                ),
            )
            if template_revision:
                profile.extra_json = {
                    "_schema_revision_ref_v1": {
                        "template_id": str(template_revision.template_id),
                        "revision_id": str(template_revision.id),
                    }
                }
            db.add(profile)
        payload = data.model_dump(exclude_unset=True)
        submitted_extra = payload.get("extra_json")
        if (
            isinstance(submitted_extra, dict)
            and "_schema_revision_ref_v1" in submitted_extra
        ):
            raise ValidationError("Reserved profile schema metadata cannot be edited")
        template_revision = await self._pinned_template_revision(db, profile)
        if template_revision and ("data_json" in payload or is_new):
            payload["data_json"] = self._validate_profile_data(
                template_revision,
                payload.get("data_json") or {},
                apply_defaults=is_new,
            )
        if template_revision and isinstance(submitted_extra, dict):
            payload["extra_json"] = {**profile.extra_json, **submitted_extra}
        for field in (
            "status",
            "source",
            "confidence",
            "evidence_refs_json",
            "extra_json",
            "data_json",
        ):
            if field in payload and payload[field] is not None:
                setattr(profile, field, payload[field])
        return profile

    async def _get_template(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
        *,
        lock: bool = False,
    ) -> EntityProfileTemplate:
        stmt = select(EntityProfileTemplate).where(
            EntityProfileTemplate.id == parse_uuid(template_id, "template_id"),
            EntityProfileTemplate.novel_id == parse_uuid(novel_id, "novel_id"),
        )
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        template = (await db.execute(stmt)).scalar_one_or_none()
        if template is None:
            raise NotFoundError("Profile template not found")
        return template

    async def _seal_template_revision(
        self,
        db: AsyncSession,
        template: EntityProfileTemplate,
        *,
        version_number: int,
    ) -> EntityProfileTemplateRevision:
        content_hash = hashlib.sha256(
            canonical_json_bytes(
                {
                    "profile_type": template.profile_type,
                    "template_schema_json": template.template_schema_json,
                    "display_schema_json": template.display_schema_json,
                }
            )
        ).hexdigest()
        revision = EntityProfileTemplateRevision(
            novel_id=template.novel_id,
            template_id=template.id,
            version_number=version_number,
            profile_type=template.profile_type,
            template_schema_json=template.template_schema_json,
            display_schema_json=template.display_schema_json,
            content_hash=content_hash,
        )
        db.add(revision)
        await db.flush()
        return revision

    async def _active_template_revision(
        self,
        db: AsyncSession,
        entity: CoreEntity,
    ) -> EntityProfileTemplateRevision | None:
        template = await db.scalar(
            select(EntityProfileTemplate).where(
                EntityProfileTemplate.novel_id == entity.novel_id,
                EntityProfileTemplate.profile_type == entity.entity_type,
                EntityProfileTemplate.status == "canonical",
            )
        )
        if template is None:
            return None
        revisions = await db.scalars(
            select(EntityProfileTemplateRevision)
            .where(EntityProfileTemplateRevision.template_id == template.id)
            .order_by(EntityProfileTemplateRevision.version_number.desc())
        )
        return next(
            (
                revision
                for revision in revisions
                if revision.template_schema_json == template.template_schema_json
                and revision.display_schema_json == template.display_schema_json
            ),
            None,
        )

    async def _pinned_template_revision(
        self,
        db: AsyncSession,
        profile: GenericEntityProfile,
    ) -> EntityProfileTemplateRevision | None:
        ref = (profile.extra_json or {}).get("_schema_revision_ref_v1")
        if ref is None:
            return None
        if not isinstance(ref, dict) or set(ref) != {"template_id", "revision_id"}:
            raise ValidationError("Invalid pinned profile schema revision")
        revision = await db.get(
            EntityProfileTemplateRevision,
            parse_uuid(ref["revision_id"], "revision_id"),
        )
        if (
            revision is None
            or revision.novel_id != profile.novel_id
            or revision.template_id != parse_uuid(ref["template_id"], "template_id")
        ):
            raise ValidationError("Pinned profile schema revision is unavailable")
        return revision

    @staticmethod
    def _template_payload(
        fields: list[EntityProfileFieldSchemaV1],
        relations: list[EntityProfileRelationSchemaV1],
    ) -> tuple[dict, dict]:
        field_payloads = [field.model_dump(mode="json") for field in fields]
        relation_payloads = [
            relation.model_dump(mode="json") for relation in relations
        ]
        return (
            {
                "schema_version": "entity_profile_schema.v1",
                "fields": field_payloads,
                "relations": relation_payloads,
            },
            {
                "schema_version": "entity_profile_display.v1",
                "field_order": [field.key for field in fields],
            },
        )

    @staticmethod
    def _validate_profile_data(
        revision: EntityProfileTemplateRevision,
        values: dict,
        *,
        apply_defaults: bool,
    ) -> dict:
        if not isinstance(values, dict):
            raise ValidationError("Profile data must be an object")
        fields = [
            EntityProfileFieldSchemaV1.model_validate(item)
            for item in revision.template_schema_json.get("fields", [])
        ]
        by_key = {field.key: field for field in fields}
        unknown = set(values) - set(by_key)
        if unknown:
            raise ValidationError("Profile data contains unknown template fields")
        result = dict(values)
        if apply_defaults:
            for field in fields:
                if field.key not in result and field.default is not None:
                    result[field.key] = field.default
        for key, value in result.items():
            field = by_key[key]
            scalar = TypedScalarStatementV1(
                subject_entity_id=revision.template_id,
                field_key=key,
                value_type=field.value_type,
                value=value,
                unit=field.unit,
            )
            if field.value_type == "enum" and scalar.value not in field.enum_values:
                raise ValidationError("Profile enum value is not allowed")
        return result

    @staticmethod
    def _template_response(
        template: EntityProfileTemplate,
        revision: EntityProfileTemplateRevision,
    ) -> EntityProfileTemplateResponse:
        return EntityProfileTemplateResponse(
            template_id=template.id,
            revision_id=revision.id,
            novel_id=template.novel_id,
            profile_type=template.profile_type,
            version_number=revision.version_number,
            status=template.status,
            fields=[
                EntityProfileFieldSchemaV1.model_validate(item)
                for item in revision.template_schema_json.get("fields", [])
            ],
            relations=[
                EntityProfileRelationSchemaV1.model_validate(item)
                for item in revision.template_schema_json.get("relations", [])
            ],
        )

    async def _profile_for_entity(
        self,
        db: AsyncSession,
        entity: CoreEntity,
    ) -> WorldProfileResponse:
        if entity.entity_type in PROFILE_REGISTRY:
            registry = PROFILE_REGISTRY[entity.entity_type]
            profile = await self._get_strong(db, entity, registry)
        else:
            profile = await self._get_generic(db, entity)
        return self._profile_response(entity, profile)

    def _profile_response(self, entity: CoreEntity, profile) -> WorldProfileResponse:
        if profile is None:
            return WorldProfileResponse(
                entity_id=str(entity.id),
                novel_id=str(entity.novel_id),
                entity_type=entity.entity_type,
                profile_kind="missing",
                status="missing",
            )
        fields: dict[str, Any] = {}
        data_json = None
        if entity.entity_type in PROFILE_REGISTRY:
            for field in PROFILE_REGISTRY[entity.entity_type].fields:
                fields[field] = getattr(profile, field, None)
            profile_kind = "strong"
        else:
            data_json = profile.data_json or {}
            profile_kind = "generic"
        return WorldProfileResponse(
            entity_id=str(entity.id),
            novel_id=str(entity.novel_id),
            entity_type=entity.entity_type,
            profile_kind=profile_kind,
            status=profile.status,
            source=getattr(profile, "source", "manual"),
            confidence=getattr(profile, "confidence", None),
            evidence_refs_json=getattr(profile, "evidence_refs_json", []) or [],
            extra_json=getattr(profile, "extra_json", {}) or {},
            data_json=data_json,
            fields=fields,
            created_at=getattr(profile, "created_at", None),
            updated_at=getattr(profile, "updated_at", None),
        )


__all__ = ["WorldProfileService"]
