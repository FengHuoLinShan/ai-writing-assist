"""Worldbuilding knowledge tag service."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.world.models import (
    Character,
    CharacterKnowledgeTag,
    CoreEntity,
    EntityRelation,
    KnowledgeTag,
    KnowledgeTagExclusion,
)
from modules.world.schemas import (
    KnowledgeTagExclusionResponse,
)
from modules.world.services.worldbuilding.shared import (
    CONFIRMED_STATUSES,
    normalize_profession_slug,
)
from shared.utils import parse_uuid


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

__all__ = ['KnowledgeTagService']
