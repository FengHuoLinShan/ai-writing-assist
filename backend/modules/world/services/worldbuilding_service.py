"""Worldbuilding Workspace v1 services."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from modules.world.models import (
    Character,
    CharacterKnowledgeTag,
    ConflictCheckQueueItem,
    CoreEntity,
    CreationSuggestion,
    EntityRelation,
    FactionProfile,
    GenericEntityProfile,
    ItemProfile,
    KnowledgeTag,
    KnowledgeTagExclusion,
    LocationProfile,
    ReaderRevealPolicy,
    RuleProfile,
    SecretProfile,
    SpeciesProfile,
    WorldBiblePage,
    WorldBiblePageProjection,
)
from modules.world.schemas import (
    ConflictQueueResponse,
    CreationSuggestionCreate,
    CreationSuggestionResponse,
    KnowledgeTagExclusionResponse,
    ReaderSafetyItem,
    ReaderSafetyResponse,
    TargetRefSchema,
    WorldBiblePageCreate,
    WorldBiblePageResponse,
    WorldBiblePageUpdate,
    WorldBibleProjectionResponse,
    WorldProfileResponse,
    WorldProfileUpsertRequest,
)
from shared.target_ref import TargetRef, normalize_target_ref
from shared.utils import parse_uuid

CONFIRMED_STATUSES = {"canonical", "confirmed"}
STRONG_PROFILE_TYPES = {"species", "faction", "location", "rule", "item", "secret"}
GENERIC_PROFILE_TYPES = {
    "group",
    "creature",
    "skill",
    "other",
    "concept",
    "resource",
    "legend",
    "power_system",
}

_PROFESSION_SLUG_RE = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True)
class ProfileBinding:
    model: type
    fields: tuple[str, ...]


PROFILE_REGISTRY: dict[str, ProfileBinding] = {
    "species": ProfileBinding(
        SpeciesProfile,
        (
            "origin_summary",
            "physiology_summary",
            "lifespan",
            "abilities_json",
            "weaknesses_json",
            "culture_summary",
            "language_summary",
            "public_baseline",
        ),
    ),
    "faction": ProfileBinding(
        FactionProfile,
        (
            "ideology_summary",
            "leader_entity_ids_json",
            "member_rules",
            "territory_refs_json",
            "resources_json",
            "public_baseline",
        ),
    ),
    "location": ProfileBinding(
        LocationProfile,
        (
            "map_refs_json",
            "climate",
            "population_summary",
            "resources_json",
            "hazards_json",
            "controlling_faction_ids_json",
        ),
    ),
    "rule": ProfileBinding(
        RuleProfile,
        (
            "rule_domain",
            "principle_summary",
            "constraints_json",
            "exceptions_json",
            "consequences_json",
        ),
    ),
    "item": ProfileBinding(
        ItemProfile,
        (
            "item_class",
            "powers_json",
            "limitations_json",
            "owner_entity_ids_json",
            "origin_summary",
        ),
    ),
    "secret": ProfileBinding(
        SecretProfile,
        (
            "truth_summary",
            "holder_entity_ids_json",
            "risk_level",
            "reveal_status",
            "linked_target_refs_json",
        ),
    ),
}


class ProjectionRefreshConflictError(Exception):
    def __init__(self, task_id: str, status: str) -> None:
        self.task_id = task_id
        self.status = status
        super().__init__(f"projection refresh already finished with status {status}")


class SuggestionAlreadyProcessedError(Exception):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"suggestion already processed: {status}")


def normalize_profession_slug(label: str) -> str:
    slug = _PROFESSION_SLUG_RE.sub("_", label.strip().lower()).strip("_")
    return slug[:128]


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
            await db.execute(
                select(func.count()).select_from(entities_stmt.subquery())
            )
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
        entity = await self._get_entity(db, novel_id, entity_id)
        if entity.entity_type in PROFILE_REGISTRY:
            await self._ensure_no_generic(db, entity)
            profile = await self._upsert_strong(db, entity, data)
        else:
            profile = await self._upsert_generic(db, entity, data)
        await db.flush()
        return self._profile_response(entity, profile)

    async def migrate_generic_to_strong(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
    ) -> WorldProfileResponse:
        entity = await self._get_entity(db, novel_id, entity_id)
        if entity.entity_type not in PROFILE_REGISTRY:
            raise ValidationError("Entity type has no strong profile table")
        generic = await self._get_generic(db, entity)
        if generic is None:
            raise NotFoundError("Generic profile not found")
        binding = PROFILE_REGISTRY[entity.entity_type]
        profile = await self._get_strong(db, entity, binding)
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
        return self._profile_response(entity, profile)

    async def _get_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
    ) -> CoreEntity:
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        result = await db.execute(
            select(CoreEntity).where(CoreEntity.id == eid, CoreEntity.novel_id == nid)
        )
        entity = result.scalar_one_or_none()
        if entity is None:
            raise NotFoundError("Entity not found in this novel")
        return entity

    async def _ensure_no_generic(self, db: AsyncSession, entity: CoreEntity) -> None:
        generic = await self._get_generic(db, entity)
        if generic and generic.status != "migrated":
            raise ValidationError(
                "Strong profile requires migrating existing generic profile first",
            )

    async def _get_generic(
        self,
        db: AsyncSession,
        entity: CoreEntity,
    ) -> GenericEntityProfile | None:
        result = await db.execute(
            select(GenericEntityProfile).where(
                GenericEntityProfile.novel_id == entity.novel_id,
                GenericEntityProfile.entity_id == entity.id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_strong(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        binding: ProfileBinding,
    ):
        result = await db.execute(
            select(binding.model).where(
                binding.model.novel_id == entity.novel_id,
                binding.model.entity_id == entity.id,
            )
        )
        return result.scalar_one_or_none()

    async def _upsert_strong(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        data: WorldProfileUpsertRequest,
    ):
        binding = PROFILE_REGISTRY[entity.entity_type]
        profile = await self._get_strong(db, entity, binding)
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
    ) -> GenericEntityProfile:
        if entity.entity_type in PROFILE_REGISTRY:
            raise ValidationError("Strong profile entity cannot create generic profile")
        profile = await self._get_generic(db, entity)
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


class WorldBibleService:
    async def list_pages(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        page_type: str | None = None,
    ) -> tuple[list[WorldBiblePageResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(WorldBiblePage).where(WorldBiblePage.novel_id == nid)
        if page_type:
            stmt = stmt.where(WorldBiblePage.page_type == page_type)
        result = await db.execute(
            stmt.order_by(WorldBiblePage.sort_order, WorldBiblePage.title)
        )
        pages = list(result.scalars().all())
        return [WorldBiblePageResponse.model_validate(page) for page in pages], len(pages)

    async def create_page(
        self,
        db: AsyncSession,
        data: WorldBiblePageCreate,
    ) -> WorldBiblePageResponse:
        nid = parse_uuid(data.novel_id, "novel_id")
        page_key = data.page_key or self._default_page_key(data.page_type, data.title)
        page = WorldBiblePage(
            novel_id=nid,
            page_type=data.page_type,
            page_key=page_key,
            title=data.title,
            status=data.status,
            page_meta_json=data.page_meta_json,
            free_text=data.free_text,
            linked_asset_refs_json=data.linked_asset_refs_json,
            activation_defaults_json=data.activation_defaults_json,
            template_key=data.template_key,
            sort_order=data.sort_order,
            created_by=data.created_by,
            updated_by=data.created_by,
        )
        db.add(page)
        await db.flush()
        return WorldBiblePageResponse.model_validate(page)

    async def get_page(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
    ) -> WorldBiblePageResponse:
        page = await self._get_page_model(db, novel_id, page_id)
        return WorldBiblePageResponse.model_validate(page)

    async def update_page(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        data: WorldBiblePageUpdate,
    ) -> WorldBiblePageResponse:
        page = await self._get_page_model(db, novel_id, page_id)
        payload = data.model_dump(exclude_unset=True)
        free_text_changed = (
            "free_text" in payload and payload["free_text"] != page.free_text
        )
        for key, value in payload.items():
            setattr(page, key, value)
        if free_text_changed:
            await self._mark_page_projections_stale(db, page)
        await db.flush()
        return WorldBiblePageResponse.model_validate(page)

    async def refresh_projection_task(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        *,
        projection_type: str = "context_brief",
        force: bool = False,
    ) -> tuple[str, str, bool]:
        page = await self._get_page_model(db, novel_id, page_id)
        existing = await self._find_projection_task(db, page, projection_type)
        if existing and existing.status in {"pending", "running"} and not force:
            return str(existing.id), existing.status, True
        if existing and existing.status in {"done", "failed"} and not force:
            raise ProjectionRefreshConflictError(str(existing.id), existing.status)
        task_id = enqueue_task(
            db,
            "world_bible_projection_refresh",
            meta={
                "novel_id": str(page.novel_id),
                "page_id": str(page.id),
                "projection_type": projection_type,
            },
        )
        await db.flush()
        return task_id, "pending", False

    async def refresh_projection_now(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        page_id: str,
        projection_type: str,
    ) -> WorldBibleProjectionResponse:
        page = await self._get_page_model(db, novel_id, page_id)
        projection = await self._get_projection_model(db, page, projection_type)
        if projection is None:
            projection = WorldBiblePageProjection(
                novel_id=page.novel_id,
                page_id=page.id,
                projection_type=projection_type,
            )
            db.add(projection)
        try:
            content = self._build_projection_content(page, projection_type)
            projection.content = content
            projection.token_estimate = len(content) // 4 + 1
            projection.source_spans_json = [
                {"start": 0, "end": len(page.free_text or "")}
            ]
            projection.omitted_reasons_json = []
            projection.status = "ready"
            projection.stale = False
            projection.stale_checked_at = datetime.now(UTC)
            projection.error_kind = None
            projection.error_summary = None
        except Exception as exc:
            projection.status = "failed"
            projection.stale = True
            projection.stale_checked_at = datetime.now(UTC)
            projection.error_kind = exc.__class__.__name__
            projection.error_summary = str(exc)[:500]
        await db.flush()
        return WorldBibleProjectionResponse.model_validate(projection)

    async def list_templates(self) -> list[dict[str, Any]]:
        return [
            {"key": "world_basic", "title": "世界基本背景", "page_type": "background"},
            {"key": "species_index", "title": "种族", "page_type": "species"},
            {"key": "factions_index", "title": "势力", "page_type": "faction"},
            {"key": "locations_index", "title": "地点与地图", "page_type": "location"},
            {"key": "rules_index", "title": "规则体系", "page_type": "rule"},
            {"key": "secrets_index", "title": "秘密与伏笔", "page_type": "secret"},
        ]

    async def _get_page_model(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
    ) -> WorldBiblePage:
        nid = parse_uuid(novel_id, "novel_id")
        pid = parse_uuid(page_id, "page_id")
        result = await db.execute(
            select(WorldBiblePage).where(
                WorldBiblePage.id == pid,
                WorldBiblePage.novel_id == nid,
            )
        )
        page = result.scalar_one_or_none()
        if page is None:
            raise NotFoundError("World Bible page not found")
        return page

    async def _mark_page_projections_stale(
        self,
        db: AsyncSession,
        page: WorldBiblePage,
    ) -> None:
        result = await db.execute(
            select(WorldBiblePageProjection).where(
                WorldBiblePageProjection.novel_id == page.novel_id,
                WorldBiblePageProjection.page_id == page.id,
            )
        )
        for projection in result.scalars().all():
            projection.stale = True
            projection.stale_checked_at = datetime.now(UTC)

    async def _get_projection_model(
        self,
        db: AsyncSession,
        page: WorldBiblePage,
        projection_type: str,
    ) -> WorldBiblePageProjection | None:
        result = await db.execute(
            select(WorldBiblePageProjection).where(
                WorldBiblePageProjection.novel_id == page.novel_id,
                WorldBiblePageProjection.page_id == page.id,
                WorldBiblePageProjection.projection_type == projection_type,
            )
        )
        return result.scalar_one_or_none()

    async def _find_projection_task(
        self,
        db: AsyncSession,
        page: WorldBiblePage,
        projection_type: str,
    ) -> AsyncTask | None:
        result = await db.execute(
            select(AsyncTask)
            .where(AsyncTask.task_type == "world_bible_projection_refresh")
            .order_by(AsyncTask.created_at.desc())
            .limit(50)
        )
        for task in result.scalars().all():
            meta = task.meta or {}
            if (
                str(meta.get("novel_id")) == str(page.novel_id)
                and str(meta.get("page_id")) == str(page.id)
                and str(meta.get("projection_type")) == projection_type
            ):
                return task
        return None

    def _build_projection_content(
        self,
        page: WorldBiblePage,
        projection_type: str,
    ) -> str:
        text = (page.free_text or "").strip()
        if not text:
            return ""
        if projection_type == "excerpt":
            return text[:4000]
        if projection_type == "style_notes":
            lines = (line.strip() for line in text.splitlines()[:20])
            return "\n".join(line for line in lines if line)
        if projection_type == "fact_candidates":
            lines = (line.strip() for line in text.splitlines())
            return "\n".join(line for line in lines if line)[:3000]
        return text[:2400]

    def _default_page_key(self, page_type: str, title: str) -> str:
        slug = _PROFESSION_SLUG_RE.sub("_", title.strip().lower()).strip("_") or "page"
        return f"{page_type}:{slug}:{uuid.uuid4().hex[:8]}"


class SuggestionQueueService:
    def __init__(self) -> None:
        self._profiles = WorldProfileService()

    async def create(
        self,
        db: AsyncSession,
        data: CreationSuggestionCreate,
    ) -> CreationSuggestionResponse:
        suggestion = CreationSuggestion(
            novel_id=parse_uuid(data.novel_id, "novel_id"),
            source_module=data.source_module,
            review_group=data.review_group,
            target_type=data.target_type,
            action_schema=data.action_schema,
            payload_json=data.payload_json,
            evidence_refs_json=data.evidence_refs_json,
            risk_level=data.risk_level,
            status=data.status,
        )
        db.add(suggestion)
        await db.flush()
        return CreationSuggestionResponse.model_validate(suggestion)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        source_module: str | None = None,
        review_group: str | None = None,
        risk_level: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[CreationSuggestionResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(CreationSuggestion).where(CreationSuggestion.novel_id == nid)
        if source_module:
            stmt = stmt.where(CreationSuggestion.source_module == source_module)
        if review_group:
            stmt = stmt.where(CreationSuggestion.review_group == review_group)
        if risk_level:
            stmt = stmt.where(CreationSuggestion.risk_level == risk_level)
        if status:
            stmt = stmt.where(CreationSuggestion.status == status)
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await db.execute(total_stmt)).scalar_one()
        result = await db.execute(
            stmt.order_by(CreationSuggestion.created_at.desc()).offset(skip).limit(limit)
        )
        return [
            CreationSuggestionResponse.model_validate(item)
            for item in result.scalars().all()
        ], total

    async def confirm(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
    ) -> CreationSuggestionResponse:
        suggestion = await self._get_pending(db, novel_id, suggestion_id)
        result_ref: dict[str, Any] = {}
        if suggestion.target_type == "profile_field":
            entity_id = str(suggestion.payload_json.get("entity_id") or "")
            profile_payload = suggestion.payload_json.get("profile") or {}
            profile_payload.setdefault(
                "evidence_refs_json",
                suggestion.evidence_refs_json,
            )
            profile = await self._profiles.upsert_profile(
                db,
                novel_id,
                entity_id,
                WorldProfileUpsertRequest.model_validate(profile_payload),
            )
            result_ref = {"type": "profile", "id": profile.entity_id}
        else:
            result_ref = {"type": suggestion.target_type, "accepted_payload": True}
        suggestion.status = "accepted"
        suggestion.result_ref_json = result_ref
        try:
            from modules.context import facade as context_facade

            await context_facade.mark_asset_context_changed(
                db,
                novel_id=novel_id,
                asset_type="worldbuilding",
                asset_id=str(result_ref.get("id") or suggestion.id),
                reason="suggestion_confirmed",
            )
        except Exception:
            # Context invalidation is advisory for v1; the accepted write remains valid.
            pass
        await db.flush()
        return CreationSuggestionResponse.model_validate(suggestion)

    async def reject(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
    ) -> CreationSuggestionResponse:
        suggestion = await self._get_pending(db, novel_id, suggestion_id)
        suggestion.status = "rejected"
        await db.flush()
        return CreationSuggestionResponse.model_validate(suggestion)

    async def _get_pending(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str,
    ) -> CreationSuggestion:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(suggestion_id, "suggestion_id")
        result = await db.execute(
            select(CreationSuggestion).where(
                CreationSuggestion.id == sid,
                CreationSuggestion.novel_id == nid,
            )
        )
        suggestion = result.scalar_one_or_none()
        if suggestion is None:
            raise NotFoundError("Suggestion not found")
        if suggestion.status != "pending":
            raise SuggestionAlreadyProcessedError(suggestion.status)
        return suggestion


class KnowledgeTagService:
    async def create_exclusion(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
        tag_id: str,
        *,
        reason: str | None = None,
    ) -> KnowledgeTagExclusionResponse:
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(character_id, "character_id")
        tid = parse_uuid(tag_id, "tag_id")
        existing = await self._get_exclusion(db, nid, cid, tid)
        if existing is None:
            existing = KnowledgeTagExclusion(
                novel_id=nid,
                character_id=cid,
                tag_id=tid,
                reason=reason,
            )
            db.add(existing)
        else:
            existing.reason = reason
        await db.flush()
        return KnowledgeTagExclusionResponse(
            character_id=str(cid),
            tag_id=str(tid),
            excluded=True,
            reason=reason,
        )

    async def delete_exclusion(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
        tag_id: str,
    ) -> KnowledgeTagExclusionResponse:
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(character_id, "character_id")
        tid = parse_uuid(tag_id, "tag_id")
        existing = await self._get_exclusion(db, nid, cid, tid)
        if existing is not None:
            await db.delete(existing)
        await db.flush()
        return KnowledgeTagExclusionResponse(
            character_id=str(cid),
            tag_id=str(tid),
            excluded=False,
        )

    async def lock_tag(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
        tag_id: str,
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(character_id, "character_id")
        tid = parse_uuid(tag_id, "tag_id")
        result = await db.execute(
            select(CharacterKnowledgeTag).where(
                CharacterKnowledgeTag.novel_id == nid,
                CharacterKnowledgeTag.character_id == cid,
                CharacterKnowledgeTag.tag_id == tid,
            )
        )
        grants = list(result.scalars().all())
        for grant in grants:
            grant.author_locked = True
        await db.flush()
        return {
            "character_id": str(cid),
            "tag_id": str(tid),
            "locked": len(grants),
        }

    async def sync_derived_tags(
        self,
        db: AsyncSession,
        novel_id: str,
        character_id: str,
    ) -> dict[str, int]:
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(character_id, "character_id")
        result = await db.execute(
            select(Character).where(Character.entity_id == cid, Character.novel_id == nid)
        )
        character = result.scalar_one_or_none()
        if character is None:
            raise NotFoundError("Character not found")
        desired = await self._desired_derived_tags(db, nid, character)
        exclusions = await self._excluded_tag_ids(db, nid, cid)
        desired = [tag for tag in desired if tag.id not in exclusions]
        existing_result = await db.execute(
            select(CharacterKnowledgeTag).where(
                CharacterKnowledgeTag.novel_id == nid,
                CharacterKnowledgeTag.character_id == cid,
                CharacterKnowledgeTag.grant_source == "derived",
            )
        )
        existing = list(existing_result.scalars().all())
        existing_by_tag = {item.tag_id: item for item in existing}
        added = 0
        for tag in desired:
            if tag.id not in existing_by_tag:
                db.add(
                    CharacterKnowledgeTag(
                        novel_id=nid,
                        character_id=cid,
                        tag_id=tag.id,
                        grant_source="derived",
                        status="canonical",
                    )
                )
                added += 1
        desired_ids = {tag.id for tag in desired}
        removed = 0
        for grant in existing:
            if grant.tag_id not in desired_ids and not grant.author_locked:
                await db.delete(grant)
                removed += 1
        await db.flush()
        return {"added": added, "removed": removed, "desired": len(desired)}

    async def _desired_derived_tags(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character: Character,
    ) -> list[KnowledgeTag]:
        tags: list[KnowledgeTag] = []
        worldbuilding = (character.meta or {}).get("worldbuilding") or {}
        species_id = worldbuilding.get("species_entity_id")
        if species_id:
            species_uuid = parse_uuid(species_id, "species_entity_id")
            species = await db.get(CoreEntity, species_uuid)
            if (
                species
                and species.novel_id == novel_id
                and species.status in CONFIRMED_STATUSES
            ):
                tags.append(
                    await self._get_or_create_tag(
                        db,
                        novel_id,
                        slug=f"species:{species.id}",
                        name=f"种族：{species.name}",
                        source="derived_species",
                    )
                )
        location_id = (
            worldbuilding.get("location_entity_id")
            or worldbuilding.get("current_location_entity_id")
        )
        if location_id:
            location_uuid = parse_uuid(location_id, "location_entity_id")
            location = await db.get(CoreEntity, location_uuid)
            if (
                location
                and location.novel_id == novel_id
                and location.status in CONFIRMED_STATUSES
            ):
                tags.append(
                    await self._get_or_create_tag(
                        db,
                        novel_id,
                        slug=f"location:{location.id}",
                        name=f"地点：{location.name}",
                        source="derived_location",
                    )
                )
        profession_label = str(worldbuilding.get("profession_label") or "").strip()
        if profession_label:
            slug = normalize_profession_slug(profession_label)
            if slug:
                tag = await self._get_tag_by_slug(db, novel_id, f"profession:{slug}")
                if tag and tag.source in {"system_profession", "confirmed_suggestion"}:
                    tags.append(tag)
        relation_result = await db.execute(
            select(EntityRelation).where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.source_id == character.entity_id,
                EntityRelation.relation_type == "member_of",
                EntityRelation.status == "canonical",
            )
        )
        for relation in relation_result.scalars().all():
            target = await db.get(CoreEntity, relation.target_id)
            if target and target.novel_id == novel_id:
                tags.append(
                    await self._get_or_create_tag(
                        db,
                        novel_id,
                        slug=f"faction:{target.id}",
                        name=f"势力：{target.name}",
                        source="derived_faction",
                    )
                )
        return tags

    async def _get_or_create_tag(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        slug: str,
        name: str,
        source: str,
    ) -> KnowledgeTag:
        tag = await self._get_tag_by_slug(db, novel_id, slug)
        if tag is None:
            tag = KnowledgeTag(novel_id=novel_id, slug=slug, name=name, source=source)
            db.add(tag)
            await db.flush()
        return tag

    async def _get_tag_by_slug(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        slug: str,
    ) -> KnowledgeTag | None:
        result = await db.execute(
            select(KnowledgeTag).where(
                KnowledgeTag.novel_id == novel_id,
                KnowledgeTag.slug == slug,
            )
        )
        return result.scalar_one_or_none()

    async def _get_exclusion(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
        tag_id: uuid.UUID,
    ) -> KnowledgeTagExclusion | None:
        result = await db.execute(
            select(KnowledgeTagExclusion).where(
                KnowledgeTagExclusion.novel_id == novel_id,
                KnowledgeTagExclusion.character_id == character_id,
                KnowledgeTagExclusion.tag_id == tag_id,
            )
        )
        return result.scalar_one_or_none()

    async def _excluded_tag_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
    ) -> set[uuid.UUID]:
        result = await db.execute(
            select(KnowledgeTagExclusion.tag_id).where(
                KnowledgeTagExclusion.novel_id == novel_id,
                KnowledgeTagExclusion.character_id == character_id,
            )
        )
        return set(result.scalars().all())


class ReaderSafetyService:
    async def check(
        self,
        db: AsyncSession,
        novel_id: str,
        targets: list[TargetRef | TargetRefSchema],
        *,
        effective_chapter_index: int | None = None,
        scene_id: str | None = None,
    ) -> ReaderSafetyResponse:
        nid = parse_uuid(novel_id, "novel_id")
        items: list[ReaderSafetyItem] = []
        for raw_target in targets:
            raw_value = (
                raw_target.model_dump()
                if hasattr(raw_target, "model_dump")
                else raw_target
            )
            target = normalize_target_ref(raw_value)
            result = await db.execute(
                select(ReaderRevealPolicy).where(
                    ReaderRevealPolicy.novel_id == nid,
                    ReaderRevealPolicy.target_hash == target.target_hash(),
                )
            )
            policy = result.scalar_one_or_none()
            diagnostics: list[str] = []
            reader_safe = False
            reveal_status = "unrevealed"
            public_baseline = False
            if policy is None:
                diagnostics.append("missing_reveal_policy")
            else:
                reveal_status = policy.status
                public_baseline = policy.public_baseline
                if policy.public_baseline:
                    reader_safe = True
                elif policy.reveal_chapter_index is None:
                    diagnostics.append("unrevealed_null_chapter")
                elif (
                    effective_chapter_index is not None
                    and policy.reveal_chapter_index <= effective_chapter_index
                ):
                    reader_safe = True
                if (
                    scene_id
                    and policy.reveal_scene_id
                    and str(policy.reveal_scene_id) == scene_id
                ):
                    reader_safe = True
            items.append(
                ReaderSafetyItem(
                    target=TargetRefSchema(**target.canonical_dict()),
                    target_hash=target.target_hash(),
                    reader_safe=reader_safe,
                    reveal_status=reveal_status,
                    public_baseline=public_baseline,
                    diagnostics=diagnostics,
                )
            )
        return ReaderSafetyResponse(items=items)


class ConflictQueueService:
    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status: str | None = None,
        conflict_type: str | None = None,
        ) -> tuple[list[ConflictQueueResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(ConflictCheckQueueItem).where(
            ConflictCheckQueueItem.novel_id == nid
        )
        if status:
            stmt = stmt.where(ConflictCheckQueueItem.status == status)
        if conflict_type:
            stmt = stmt.where(ConflictCheckQueueItem.conflict_type == conflict_type)
        result = await db.execute(
            stmt.order_by(ConflictCheckQueueItem.created_at.desc())
        )
        items = [
            ConflictQueueResponse.model_validate(item)
            for item in result.scalars().all()
        ]
        return items, len(items)

    async def resolve(
        self,
        db: AsyncSession,
        novel_id: str,
        item_id: str,
        *,
        status: str,
        resolution_json: dict[str, Any],
    ) -> ConflictQueueResponse:
        nid = parse_uuid(novel_id, "novel_id")
        iid = parse_uuid(item_id, "conflict_id")
        result = await db.execute(
            select(ConflictCheckQueueItem).where(
                ConflictCheckQueueItem.id == iid,
                ConflictCheckQueueItem.novel_id == nid,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise NotFoundError("Conflict item not found")
        item.status = status
        item.resolution_json = resolution_json
        await db.flush()
        return ConflictQueueResponse.model_validate(item)


class ActivationPreviewService:
    """Deterministic worldbuilding activation preview."""

    SOURCE_WEIGHTS = {
        "explicit": 10000,
        "scene_map_focus": 8000,
        "page_linked": 6000,
        "relation": 4000,
        "generic_related": 2000,
    }

    async def preview(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_ids: list[str] | None = None,
        map_id: str | None = None,
        scene_id: str | None = None,
        focus_entity_id: str | None = None,
        top_k: int = 64,
        depth: int = 2,
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")
        top_k = max(1, min(top_k, 256))
        depth = max(0, min(depth, 2))
        warnings: list[str] = []
        candidates: dict[str, dict[str, Any]] = {}
        explicit_ids = [*list(entity_ids or [])]
        if focus_entity_id:
            explicit_ids.append(focus_entity_id)
        for entity_id in explicit_ids:
            entity = await self._entity_or_none(db, nid, entity_id)
            if entity:
                self._add_entity(candidates, entity, "explicit", "request parameter")
        if map_id:
            warnings.append("map_focus_explicit")
        elif scene_id or focus_entity_id:
            warnings.append("map_focus_requires_confirmed_summary_or_explicit_map")
        if depth >= 1:
            await self._expand_relations(db, nid, candidates, source="relation")
        if depth >= 2:
            await self._expand_page_links(db, nid, candidates)
        ranked = sorted(
            candidates.values(),
            key=lambda item: (-item["score"], item["target_hash"]),
        )
        return {
            "novel_id": str(nid),
            "depth": depth,
            "top_k": top_k,
            "items": ranked[:top_k],
            "warnings": warnings,
        }

    async def _entity_or_none(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: str,
    ) -> CoreEntity | None:
        try:
            eid = parse_uuid(entity_id, "entity_id")
        except Exception:
            return None
        result = await db.execute(
            select(CoreEntity).where(
                CoreEntity.id == eid,
                CoreEntity.novel_id == novel_id,
            )
        )
        return result.scalar_one_or_none()

    async def _expand_relations(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        candidates: dict[str, dict[str, Any]],
        *,
        source: str,
    ) -> None:
        seed_ids = [
            parse_uuid(item["target"]["target_id"], "target_id")
            for item in candidates.values()
            if item["target"]["target_type"] == "core_entity"
        ]
        if not seed_ids:
            return
        result = await db.execute(
            select(CoreEntity)
            .join(
                EntityRelation,
                (EntityRelation.target_id == CoreEntity.id)
                | (EntityRelation.source_id == CoreEntity.id),
            )
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.status == "canonical",
                (EntityRelation.source_id.in_(seed_ids))
                | (EntityRelation.target_id.in_(seed_ids)),
                CoreEntity.novel_id == novel_id,
                CoreEntity.status == "canonical",
            )
            .limit(256)
        )
        for entity in result.scalars().unique().all():
            self._add_entity(candidates, entity, source, "canonical relation")

    async def _expand_page_links(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        candidates: dict[str, dict[str, Any]],
    ) -> None:
        result = await db.execute(
            select(WorldBiblePage).where(
                WorldBiblePage.novel_id == novel_id,
                WorldBiblePage.status.in_(list(CONFIRMED_STATUSES)),
            )
        )
        for page in result.scalars().all():
            for raw_target in page.linked_asset_refs_json or []:
                try:
                    target = normalize_target_ref(raw_target)
                except Exception:
                    continue
                key = target.target_hash()
                candidates.setdefault(
                    key,
                    {
                        "target": target.canonical_dict(),
                        "target_hash": key,
                        "score": self.SOURCE_WEIGHTS["page_linked"],
                        "source": "page_linked",
                        "reason": f"linked from page {page.title}",
                        "label": page.title,
                    },
                )

    def _add_entity(
        self,
        candidates: dict[str, dict[str, Any]],
        entity: CoreEntity,
        source: str,
        reason: str,
    ) -> None:
        target = TargetRef(target_type="core_entity", target_id=str(entity.id))
        weight = self.SOURCE_WEIGHTS.get(source, self.SOURCE_WEIGHTS["generic_related"])
        importance = int((entity.importance or 0) * 1000)
        score = weight + importance
        existing = candidates.get(target.target_hash())
        if existing and existing["score"] >= score:
            return
        candidates[target.target_hash()] = {
            "target": target.canonical_dict(),
            "target_hash": target.target_hash(),
            "score": score,
            "source": source,
            "reason": reason,
            "label": entity.name,
            "status": entity.status,
        }
