"""Persistence queries for revisioned World object dossier entries."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import WorldObjectDossierEntry


class WorldObjectDossierRepository:
    """Keep dossier history and legacy-field queries behind one World seam."""

    async def list_active_for_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        *,
        visibility_filter: str | None = None,
    ) -> list[WorldObjectDossierEntry]:
        statement = (
            select(WorldObjectDossierEntry)
            .where(
                WorldObjectDossierEntry.novel_id == novel_id,
                WorldObjectDossierEntry.entity_id == entity_id,
                WorldObjectDossierEntry.status == "active",
            )
            .order_by(
                WorldObjectDossierEntry.facing_kind,
                WorldObjectDossierEntry.facing_key,
                WorldObjectDossierEntry.created_at,
                WorldObjectDossierEntry.id,
            )
        )
        if visibility_filter is not None:
            statement = statement.where(
                WorldObjectDossierEntry.visibility == visibility_filter
            )
        rows = await db.scalars(statement)
        return list(rows.all())

    async def list_history(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        *,
        entry_group_id: uuid.UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[WorldObjectDossierEntry], int]:
        statement = select(WorldObjectDossierEntry).where(
            WorldObjectDossierEntry.novel_id == novel_id,
            WorldObjectDossierEntry.entity_id == entity_id,
        )
        if entry_group_id is not None:
            statement = statement.where(
                WorldObjectDossierEntry.entry_group_id == entry_group_id
            )
        total = await db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = await db.scalars(
            statement.order_by(
                WorldObjectDossierEntry.created_at.desc(),
                WorldObjectDossierEntry.revision_number.desc(),
                WorldObjectDossierEntry.id,
            )
            .offset(offset)
            .limit(limit)
        )
        return list(rows.all()), int(total or 0)

    async def get_revision(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        revision_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> WorldObjectDossierEntry | None:
        statement = select(WorldObjectDossierEntry).where(
            WorldObjectDossierEntry.novel_id == novel_id,
            WorldObjectDossierEntry.entity_id == entity_id,
            WorldObjectDossierEntry.id == revision_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await db.scalar(statement)

    async def list_group(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        entry_group_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> list[WorldObjectDossierEntry]:
        statement = select(WorldObjectDossierEntry).where(
            WorldObjectDossierEntry.novel_id == novel_id,
            WorldObjectDossierEntry.entity_id == entity_id,
            WorldObjectDossierEntry.entry_group_id == entry_group_id,
        )
        if for_update:
            statement = statement.with_for_update()
        rows = await db.scalars(
            statement.order_by(WorldObjectDossierEntry.revision_number)
        )
        return list(rows.all())

    async def list_active_legacy_field(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        field: str,
        *,
        for_update: bool = False,
    ) -> list[WorldObjectDossierEntry]:
        statement = select(WorldObjectDossierEntry).where(
            WorldObjectDossierEntry.novel_id == novel_id,
            WorldObjectDossierEntry.entity_id == entity_id,
            WorldObjectDossierEntry.legacy_field_key == field,
            WorldObjectDossierEntry.status == "active",
            WorldObjectDossierEntry.start_anchor_id.is_(None),
            WorldObjectDossierEntry.end_anchor_id.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        rows = await db.scalars(
            statement.order_by(
                WorldObjectDossierEntry.created_at,
                WorldObjectDossierEntry.entry_group_id,
                WorldObjectDossierEntry.revision_number,
                WorldObjectDossierEntry.id,
            )
        )
        return list(rows.all())

    async def latest_legacy_field(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        field: str,
        *,
        for_update: bool = False,
    ) -> WorldObjectDossierEntry | None:
        statement = (
            select(WorldObjectDossierEntry)
            .where(
                WorldObjectDossierEntry.novel_id == novel_id,
                WorldObjectDossierEntry.entity_id == entity_id,
                WorldObjectDossierEntry.legacy_field_key == field,
            )
            .order_by(
                WorldObjectDossierEntry.created_at.desc(),
                WorldObjectDossierEntry.revision_number.desc(),
            )
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        return await db.scalar(statement)

    async def list_active_legacy_character_fields(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_ids: set[uuid.UUID],
        legacy_field_keys: set[str],
    ) -> list[WorldObjectDossierEntry]:
        if not entity_ids or not legacy_field_keys:
            return []
        rows = await db.scalars(
            select(WorldObjectDossierEntry)
            .where(
                WorldObjectDossierEntry.novel_id == novel_id,
                WorldObjectDossierEntry.entity_id.in_(entity_ids),
                WorldObjectDossierEntry.legacy_field_key.in_(legacy_field_keys),
                WorldObjectDossierEntry.status == "active",
                WorldObjectDossierEntry.start_anchor_id.is_(None),
                WorldObjectDossierEntry.end_anchor_id.is_(None),
            )
            .order_by(
                WorldObjectDossierEntry.entity_id,
                WorldObjectDossierEntry.legacy_field_key,
                WorldObjectDossierEntry.created_at,
                WorldObjectDossierEntry.entry_group_id,
                WorldObjectDossierEntry.revision_number,
                WorldObjectDossierEntry.id,
            )
        )
        return list(rows.all())

    async def add_revision(
        self,
        db: AsyncSession,
        row: WorldObjectDossierEntry,
    ) -> WorldObjectDossierEntry:
        db.add(row)
        await db.flush()
        return row


__all__ = ["WorldObjectDossierRepository"]
