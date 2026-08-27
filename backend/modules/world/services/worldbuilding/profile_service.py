"""Worldbuilding profile service."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from modules.world.models import (
    CoreEntity,
    GenericEntityProfile,
)
from modules.world.schemas import (
    WorldProfileResponse,
    WorldProfileUpsertRequest,
)
from modules.world.services.worldbuilding.shared import PROFILE_REGISTRY, ProfileBinding
from shared.utils import parse_uuid


class WorldProfileService:
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
        if profile is None:
            profile = GenericEntityProfile(
                novel_id=entity.novel_id,
                entity_id=entity.id,
                profile_type=entity.entity_type,
            )
            db.add(profile)
        payload = data.model_dump(exclude_unset=True)
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
