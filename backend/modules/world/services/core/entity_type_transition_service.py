"""CoreEntity 类型转换、Profile 迁移与硬依赖门禁。"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
from modules.world.map_models import (
    MapConfig,
    MapLocationBinding,
    MapLocationLayout,
    MapMarker,
    MapTerrainBinding,
    MapTerritoryTile,
)
from modules.world.models import (
    AssetKnowledgeTag,
    Character,
    CharacterKnowledge,
    CharacterKnowledgeTag,
    ConflictCheckQueueItem,
    CoreEntity,
    CreationSuggestion,
    EntityRelation,
    Event,
    GenericEntityProfile,
    KnowledgeVisibilityPolicy,
    ReaderRevealPolicy,
    WorldBiblePage,
    WorldBiblePageDraft,
)
from modules.world.services.worldbuilding.shared import PROFILE_REGISTRY

_MIGRATION_KEY = "_type_migration_v1"
_ACTIVE_QUEUE_STATUSES = {"pending", "open", "draft", "active"}


class EntityTypeTransitionService:
    """唯一允许把既有 CoreEntity 从一种类型切换到另一种类型的入口。"""

    async def transition(
        self,
        db: AsyncSession,
        *,
        entity: CoreEntity,
        new_type: str,
        changed_by: str = "manual",
    ) -> None:
        locked = (
            await db.execute(
                select(CoreEntity)
                .where(
                    CoreEntity.id == entity.id,
                    CoreEntity.novel_id == entity.novel_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if locked is None:
            raise NotFoundError("Entity not found in this novel")
        old_type = locked.entity_type
        if old_type == new_type:
            return

        blockers = await self._collect_blockers(db, locked, old_type)
        if blockers:
            raise ConflictError(
                "对象仍有依赖当前类型的专属数据",
                code="entity_type_change_blocked",
                context={
                    "from_type": old_type,
                    "to_type": new_type,
                    "blockers": blockers,
                },
            )
        await self._migrate_profile(
            db,
            locked,
            old_type=old_type,
            new_type=new_type,
            changed_by=changed_by,
        )

    async def _collect_blockers(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        old_type: str,
    ) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}

        async def count(kind: str, model: type, *conditions: Any) -> None:
            value = (
                await db.execute(
                    select(func.count()).select_from(model).where(*conditions)
                )
            ).scalar_one()
            if value:
                counts[kind] = int(value)

        nid, eid = entity.novel_id, entity.id
        if old_type == "character":
            await count(
                "character_extension",
                Character,
                Character.novel_id == nid,
                Character.entity_id == eid,
            )
            await count(
                "character_knowledge",
                CharacterKnowledge,
                CharacterKnowledge.novel_id == nid,
                CharacterKnowledge.character_id == eid,
            )
            await count(
                "character_knowledge_tag",
                CharacterKnowledgeTag,
                CharacterKnowledgeTag.novel_id == nid,
                CharacterKnowledgeTag.character_id == eid,
            )
            await count(
                "map_character_marker",
                MapMarker,
                MapMarker.novel_id == nid,
                MapMarker.entity_id == eid,
                MapMarker.marker_type == "character",
            )
        elif old_type == "event":
            await count(
                "event_extension", Event, Event.novel_id == nid, Event.entity_id == eid
            )
            await count(
                "event_causal_reference",
                EntityRelation,
                EntityRelation.novel_id == nid,
                EntityRelation.caused_by_event_id == eid,
            )
            await count(
                "map_event_marker",
                MapMarker,
                MapMarker.novel_id == nid,
                MapMarker.entity_id == eid,
                MapMarker.marker_type == "event",
            )
        elif old_type == "location":
            await count(
                "event_location",
                Event,
                Event.novel_id == nid,
                Event.location_entity_id == eid,
            )
            await count(
                "map_parent_entity",
                MapConfig,
                MapConfig.novel_id == nid,
                MapConfig.parent_entity_id == eid,
            )
            await count(
                "map_location_binding",
                MapLocationBinding,
                MapLocationBinding.novel_id == nid,
                MapLocationBinding.location_entity_id == eid,
            )
            await count(
                "map_location_layout",
                MapLocationLayout,
                MapLocationLayout.novel_id == nid,
                MapLocationLayout.location_entity_id == eid,
            )
            await count(
                "map_terrain_binding",
                MapTerrainBinding,
                MapTerrainBinding.novel_id == nid,
                MapTerrainBinding.location_entity_id == eid,
            )
        elif old_type == "item":
            await count(
                "map_item_marker",
                MapMarker,
                MapMarker.novel_id == nid,
                MapMarker.entity_id == eid,
                MapMarker.marker_type == "item",
            )
        elif old_type == "organization":
            await count(
                "map_territory_tile",
                MapTerritoryTile,
                MapTerritoryTile.novel_id == nid,
                MapTerritoryTile.faction_entity_id == eid,
            )

        if old_type in {
            "character",
            "event",
            "location",
            "item",
            "organization",
            "species",
        }:
            await count(
                "typed_character_knowledge_reference",
                CharacterKnowledge,
                CharacterKnowledge.novel_id == nid,
                CharacterKnowledge.target_type == old_type,
                CharacterKnowledge.target_id == eid,
            )

        if old_type == "species":
            characters = list(
                (
                    await db.execute(
                        select(Character).where(
                            Character.novel_id == nid,
                            cast(Character.meta, String).contains(str(eid)),
                        )
                    )
                )
                .scalars()
                .all()
            )
            species_refs = sum(
                1
                for character in characters
                if str(
                    (character.meta or {})
                    .get("worldbuilding", {})
                    .get("species_entity_id")
                    or ""
                )
                == str(eid)
            )
            if species_refs:
                counts["character_species_reference"] = species_refs

        profile_refs = await self._count_active_profile_target_refs(db, entity, old_type)
        if profile_refs:
            counts["active_profile_target_ref"] = profile_refs
        return [{"kind": kind, "count": value} for kind, value in sorted(counts.items())]

    async def _count_active_profile_target_refs(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        old_type: str,
    ) -> int:
        target_ids = {
            str(entity.id),
            f"{old_type}:{entity.id}",
            f"{old_type}_profiles:{entity.id}",
        }
        generic = await self._get_generic(db, entity)
        if generic is not None:
            target_ids.update(
                {
                    f"generic_entity_profiles:{generic.id}",
                    f"generic:{old_type}:{entity.id}",
                }
            )

        def contains(value: Any) -> bool:
            if isinstance(value, dict):
                for type_key, id_key in (
                    ("type", "id"),
                    ("source_type", "source_id"),
                    ("target_type", "target_id"),
                ):
                    if (
                        value.get(type_key) == "profile"
                        and str(value.get(id_key)) in target_ids
                    ):
                        return True
                return any(contains(item) for item in value.values())
            if isinstance(value, list):
                return any(contains(item) for item in value)
            return False

        reference_needles = {str(entity.id)}
        if generic is not None:
            reference_needles.add(str(generic.id))

        def candidate_ref(model: type, fields: tuple[str, ...]):
            """Cheap necessary-condition filter; Python keeps exact semantics."""
            return or_(
                *(
                    cast(getattr(model, field), String).contains(needle)
                    for field in fields
                    for needle in reference_needles
                )
            )

        total = 0
        scans: tuple[tuple[type, tuple[str, ...], Any | None], ...] = (
            (
                WorldBiblePage,
                ("linked_asset_refs_json",),
                WorldBiblePage.status != "archived",
            ),
            (WorldBiblePageDraft, ("linked_asset_refs_json",), None),
            (AssetKnowledgeTag, ("target",), AssetKnowledgeTag.status != "archived"),
            (
                KnowledgeVisibilityPolicy,
                ("target", "policy_json"),
                KnowledgeVisibilityPolicy.status != "archived",
            ),
            (ReaderRevealPolicy, ("target",), ReaderRevealPolicy.status != "archived"),
            (
                ConflictCheckQueueItem,
                ("target", "evidence_refs_json"),
                ConflictCheckQueueItem.status.in_(tuple(_ACTIVE_QUEUE_STATUSES)),
            ),
            (
                CreationSuggestion,
                ("payload_json", "evidence_refs_json"),
                CreationSuggestion.status.in_(tuple(_ACTIVE_QUEUE_STATUSES)),
            ),
        )
        for model, fields, status_condition in scans:
            stmt = select(model).where(
                model.novel_id == entity.novel_id,
                candidate_ref(model, fields),
            )
            if status_condition is not None:
                stmt = stmt.where(status_condition)
            rows = list((await db.execute(stmt)).scalars().all())
            total += sum(
                1
                for row in rows
                if any(contains(getattr(row, field, None)) for field in fields)
            )

        for binding in PROFILE_REGISTRY.values():
            candidate_fields = ("extra_json", *binding.fields)
            rows = list(
                (
                    await db.execute(
                        select(binding.model).where(
                            binding.model.novel_id == entity.novel_id,
                            binding.model.status != "migrated",
                            candidate_ref(binding.model, candidate_fields),
                        )
                    )
                )
                .scalars()
                .all()
            )
            total += sum(
                1
                for row in rows
                if row.entity_id != entity.id
                and (
                    contains(row.extra_json)
                    or any(
                        contains(getattr(row, field, None)) for field in binding.fields
                    )
                )
            )
        generic_rows = list(
            (
                await db.execute(
                    select(GenericEntityProfile).where(
                        GenericEntityProfile.novel_id == entity.novel_id,
                        GenericEntityProfile.status != "migrated",
                        GenericEntityProfile.entity_id != entity.id,
                        candidate_ref(
                            GenericEntityProfile,
                            ("data_json", "extra_json"),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        total += sum(
            1
            for row in generic_rows
            if contains(row.data_json) or contains(row.extra_json)
        )
        return total

    async def _migrate_profile(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        *,
        old_type: str,
        new_type: str,
        changed_by: str,
    ) -> None:
        generic = await self._get_generic(db, entity, lock=True)
        strong_rows: dict[str, Any] = {}
        for profile_type, binding in PROFILE_REGISTRY.items():
            row = (
                await db.execute(
                    select(binding.model)
                    .where(
                        binding.model.novel_id == entity.novel_id,
                        binding.model.entity_id == entity.id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is not None:
                strong_rows[profile_type] = row

        active = [row for row in strong_rows.values() if row.status != "migrated"]
        if generic is not None and generic.status != "migrated":
            active.append(generic)
        source = strong_rows.get(old_type) if old_type in PROFILE_REGISTRY else generic
        active_source = (
            source
            if source is not None and getattr(source, "status", None) != "migrated"
            else None
        )
        if len(active) > 1 or (active and active[0] is not active_source):
            raise ConflictError(
                "对象的活跃档案与当前类型不一致，无法安全迁移",
                code="profile_state_conflict",
                context={"from_type": old_type, "to_type": new_type},
            )

        if source is None and not strong_rows and generic is None:
            return
        if generic is None:
            generic = GenericEntityProfile(
                novel_id=entity.novel_id,
                entity_id=entity.id,
                profile_type=new_type,
                status="migrated",
                data_json={},
                extra_json={},
                evidence_refs_json=[],
            )
            db.add(generic)

        extra = deepcopy(generic.extra_json or {})
        journal = deepcopy(extra.get(_MIGRATION_KEY) or {"snapshots": {}, "history": []})
        snapshots = journal.setdefault("snapshots", {})
        if source is not None and getattr(source, "status", None) != "migrated":
            snapshots[old_type] = self._snapshot(source, old_type)
        source_snapshot = snapshots.get(old_type)
        target_snapshot = snapshots.get(new_type)

        journal.setdefault("history", []).append(
            {
                "from_type": old_type,
                "to_type": new_type,
                "changed_at": datetime.now(UTC).isoformat(),
                "changed_by": changed_by,
            }
        )
        if new_type in PROFILE_REGISTRY:
            target = strong_rows.get(new_type)
            if target is None:
                target = PROFILE_REGISTRY[new_type].model(
                    novel_id=entity.novel_id,
                    entity_id=entity.id,
                )
                db.add(target)
            self._restore_strong(
                target,
                new_type,
                target_snapshot or source_snapshot,
                first_entry=target_snapshot is None,
            )
            if source is not None and source is not target:
                source.status = "migrated"
            generic.status = "migrated"
            generic.profile_type = new_type
        else:
            self._restore_generic(generic, new_type, target_snapshot or source_snapshot)
            if source is not None and source is not generic:
                source.status = "migrated"

        extra = deepcopy(generic.extra_json or {})
        extra[_MIGRATION_KEY] = journal
        generic.extra_json = extra
        await db.flush()

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
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _snapshot(profile: Any, profile_type: str) -> dict[str, Any]:
        is_strong = profile_type in PROFILE_REGISTRY and not isinstance(
            profile, GenericEntityProfile
        )
        data = (
            {
                field: deepcopy(getattr(profile, field, None))
                for field in PROFILE_REGISTRY[profile_type].fields
            }
            if is_strong
            else deepcopy(profile.data_json or {})
        )
        extra = deepcopy(profile.extra_json or {})
        extra.pop(_MIGRATION_KEY, None)
        return {
            "profile_kind": "strong" if is_strong else "generic",
            "status": profile.status,
            "source": getattr(profile, "source", "manual"),
            "confidence": getattr(profile, "confidence", None),
            "evidence_refs_json": deepcopy(
                getattr(profile, "evidence_refs_json", []) or []
            ),
            "data": data,
            "extra_json": extra,
        }

    @staticmethod
    def _restore_common(profile: Any, snapshot: dict[str, Any] | None) -> None:
        snapshot = snapshot or {}
        profile.status = snapshot.get("status") or "draft"
        if profile.status == "migrated":
            profile.status = "draft"
        profile.source = snapshot.get("source") or "manual"
        profile.confidence = snapshot.get("confidence")
        profile.evidence_refs_json = deepcopy(snapshot.get("evidence_refs_json") or [])

    def _restore_strong(
        self,
        profile: Any,
        profile_type: str,
        snapshot: dict[str, Any] | None,
        *,
        first_entry: bool,
    ) -> None:
        self._restore_common(profile, snapshot)
        snapshot = snapshot or {}
        data = deepcopy(snapshot.get("data") or {})
        fields = PROFILE_REGISTRY[profile_type].fields
        for field in fields:
            if field in data:
                setattr(profile, field, data[field])
        extra = deepcopy(snapshot.get("extra_json") or {})
        unmapped = {key: value for key, value in data.items() if key not in fields}
        if first_entry and unmapped:
            extra["unmapped_generic"] = unmapped
        profile.extra_json = extra

    def _restore_generic(
        self,
        profile: GenericEntityProfile,
        profile_type: str,
        snapshot: dict[str, Any] | None,
    ) -> None:
        self._restore_common(profile, snapshot)
        snapshot = snapshot or {}
        profile.profile_type = profile_type
        profile.data_json = deepcopy(snapshot.get("data") or {})
        profile.extra_json = deepcopy(snapshot.get("extra_json") or {})


__all__ = ["EntityTypeTransitionService"]
