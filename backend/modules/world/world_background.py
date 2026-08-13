"""Derived world-background aggregation used by context activation."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from infrastructure.llm.token_estimation import estimate_token_count
from modules.world.contracts import (
    WorldBackgroundBundleContract,
    WorldBackgroundEntryContract,
)
from modules.world.models import (
    CharacterKnowledge,
    CoreEntity,
    EntityRelation,
    Event,
    FactionProfile,
    GenericEntityProfile,
    ItemProfile,
    LocationProfile,
    RuleProfile,
    SecretProfile,
    SpeciesProfile,
    WorldBiblePage,
    WorldBiblePageProjection,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from shared.utils import parse_uuid


class WorldBackgroundAggregation:
    """Keep world-data selection local to the world module implementation."""

    async def build(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        context_mode: str = "canonical",
        reveal_mode: str = "author_safe",
        limit: int = 160,
    ) -> WorldBackgroundBundleContract:
        if context_mode not in {"canonical", "working"}:
            raise ValueError("context_mode must be canonical or working")
        if reveal_mode not in {"author_safe", "author_full"}:
            raise ValueError("reveal_mode must be author_safe or author_full")
        nid = parse_uuid(novel_id, "novel_id")
        statuses = ["canonical"]
        if context_mode == "working":
            statuses.append("draft")
        entries: list[WorldBackgroundEntryContract] = []

        profile_summaries = await self._profile_summaries(db, nid)
        event_summaries = await self._event_summaries(db, nid)

        entities = await db.execute(
            select(CoreEntity)
            .where(CoreEntity.novel_id == nid, CoreEntity.status.in_(statuses))
            .order_by(CoreEntity.importance.desc(), CoreEntity.name.asc())
            .limit(limit)
        )
        for entity in entities.scalars().all():
            profile_summary = profile_summaries.get(entity.id)
            event_summary = event_summaries.get(entity.id)
            if reveal_mode == "author_full":
                parts = [
                    entity.summary or entity.name,
                    entity.public_info or "",
                    entity.hidden_truth or "",
                ]
            else:
                parts = [entity.summary or entity.public_info or entity.name]
                if profile_summary:
                    parts.append(profile_summary)
                if event_summary:
                    parts.append(event_summary)
            summary = "；".join(item for item in parts if item)
            entries.append(
                self._entry(
                    novel_id,
                    "entity",
                    str(entity.id),
                    entity.name,
                    summary,
                    f"{entity.entity_type}:{entity.name}",
                    float(
                        entity.importance
                        if entity.importance is not None
                        else 0.5
                    ),
                    entity.status,
                    entity.reveal_level,
                    self._keywords(entity.name, entity.content_json),
                )
            )
            if reveal_mode == "author_full" and profile_summary:
                entries.append(
                    self._entry(
                        novel_id,
                        "profile",
                        str(entity.id),
                        f"{entity.name}档案",
                        profile_summary,
                        f"profile:{entity.entity_type}",
                        float(
                            entity.importance
                            if entity.importance is not None
                            else 0.5
                        ),
                        entity.status,
                        entity.reveal_level,
                        [entity.name, entity.entity_type],
                    )
                )
            if reveal_mode == "author_full" and event_summary:
                entries.append(
                    self._entry(
                        novel_id,
                        "event",
                        str(entity.id),
                        entity.name,
                        event_summary,
                        "event:timeline",
                        float(
                            entity.importance
                            if entity.importance is not None
                            else 0.5
                        ),
                        entity.status,
                        entity.reveal_level,
                        [entity.name, "event"],
                    )
                )

        source_entity = aliased(CoreEntity)
        target_entity = aliased(CoreEntity)
        relations = await db.execute(
            select(EntityRelation, source_entity.name, target_entity.name)
            .outerjoin(
                source_entity,
                (source_entity.id == EntityRelation.source_id)
                & (source_entity.novel_id == EntityRelation.novel_id),
            )
            .outerjoin(
                target_entity,
                (target_entity.id == EntityRelation.target_id)
                & (target_entity.novel_id == EntityRelation.novel_id),
            )
            .where(EntityRelation.novel_id == nid, EntityRelation.status.in_(statuses))
            .order_by(EntityRelation.strength.desc())
            .limit(limit)
        )
        for relation, source_name, target_name in relations.all():
            title = relation.relation_type
            summary = (
                f"{source_name or relation.source_id}与"
                f"{target_name or relation.target_id}："
                f"{relation.description or relation.relation_type}"
            )
            entries.append(
                self._entry(
                    novel_id,
                    "relation",
                    str(relation.id),
                    title,
                    summary,
                    f"relation:{relation.relation_type}",
                    float(
                        relation.strength
                        if relation.strength is not None
                        else 0.5
                    ),
                    relation.status,
                    "author_safe",
                    [relation.relation_type],
                )
            )

        knowledge = await db.execute(
            select(CharacterKnowledge)
            .where(
                CharacterKnowledge.novel_id == nid,
                CharacterKnowledge.status.in_(statuses),
            )
            .limit(limit)
        )
        for item in knowledge.scalars().all():
            summary = item.known_content or item.misconception or item.knowledge_level
            entries.append(
                self._entry(
                    novel_id,
                    "character_knowledge",
                    str(item.id),
                    item.knowledge_level,
                    summary,
                    f"knowledge:{item.character_id}",
                    0.65,
                    item.status,
                    "author_only",
                    [item.knowledge_level],
                )
            )

        pages = await db.execute(
            select(WorldBiblePage, WorldBiblePageProjection)
            .outerjoin(
                WorldBiblePageProjection,
                (WorldBiblePageProjection.page_id == WorldBiblePage.id)
                & (WorldBiblePageProjection.novel_id == WorldBiblePage.novel_id)
                & (WorldBiblePageProjection.projection_type == "context_brief"),
            )
            .where(
                WorldBiblePage.novel_id == nid,
                WorldBiblePage.status.in_({"canonical", "confirmed"}),
            )
            .order_by(WorldBiblePage.sort_order, WorldBiblePage.title)
            .limit(limit)
        )
        for page, projection in pages.all():
            current_projection = bool(
                projection
                and not projection.stale
                and projection.source_page_version == page.version_number
                and projection.source_hash
                == WorldBibleLifecycleService.projection_source_hash(page)
            )
            summary = (
                projection.content
                if current_projection
                else (page.free_text or "")
            )
            if not summary:
                continue
            entries.append(
                self._entry(
                    novel_id,
                    "world_bible_page",
                    str(page.id),
                    page.title,
                    summary,
                    f"{page.page_type}:{page.title}",
                    0.7,
                    page.status,
                    "author_only",
                    [page.title, page.page_type],
                )
            )

        entries.sort(key=lambda item: (-item.importance, item.entry_id))
        return WorldBackgroundBundleContract(
            novel_id=novel_id,
            context_mode=context_mode,
            entries=entries[:limit],
        )

    @staticmethod
    def _entry(
        novel_id: str,
        asset_type: str,
        asset_id: str,
        title: str,
        summary: str,
        group: str,
        importance: float,
        status: str,
        sensitivity: str,
        keywords: list[str],
    ) -> WorldBackgroundEntryContract:
        full_summary = " ".join(str(summary or "").split())
        clean_summary = full_summary[:1000]
        source_hash = hashlib.sha256(
            json.dumps(
                {
                    "asset_id": asset_id,
                    "asset_type": asset_type,
                    "status": status,
                    "summary": full_summary,
                    "title": title,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return WorldBackgroundEntryContract(
            entry_id=f"{asset_type}:{asset_id}",
            novel_id=novel_id,
            asset_type=asset_type,
            asset_id=asset_id,
            title=title,
            summary=clean_summary,
            group=group,
            importance=importance,
            tier="P1" if importance >= 0.8 else "P2",
            status=status,
            sensitivity=sensitivity,
            keywords=[item for item in keywords if item][:12],
            source_ids=[
                {"type": asset_type, "id": asset_id, "source_hash": source_hash}
            ],
            source_hash=source_hash,
            token_count=estimate_token_count(f"{title} {clean_summary}"),
        )

    @staticmethod
    def _keywords(name: str, content: dict | None) -> list[str]:
        aliases = (content or {}).get("aliases") or []
        values = [name]
        for item in aliases:
            values.append(str(item.get("alias") if isinstance(item, dict) else item))
        return values

    @classmethod
    async def _profile_summaries(
        cls,
        db: AsyncSession,
        novel_id,
    ) -> dict:
        summaries: dict = {}
        for model in (
            SpeciesProfile,
            FactionProfile,
            LocationProfile,
            RuleProfile,
            ItemProfile,
            SecretProfile,
            GenericEntityProfile,
        ):
            result = await db.execute(
                select(model).where(
                    model.novel_id == novel_id,
                    model.status.in_({"canonical", "confirmed"}),
                )
            )
            for row in result.scalars().all():
                fields: list[str] = []
                for column in row.__table__.columns:
                    if column.name in {
                        "id",
                        "novel_id",
                        "entity_id",
                        "status",
                        "source",
                        "confidence",
                        "created_at",
                        "updated_at",
                        "evidence_refs_json",
                    }:
                        continue
                    value = getattr(row, column.name, None)
                    if value in (None, "", [], {}):
                        continue
                    fields.append(f"{column.name}={value}")
                if fields:
                    summaries[row.entity_id] = "；".join(fields)
        return summaries

    @staticmethod
    async def _event_summaries(db: AsyncSession, novel_id) -> dict:
        location = aliased(CoreEntity)
        result = await db.execute(
            select(Event, location.name)
            .outerjoin(
                location,
                (location.id == Event.location_entity_id)
                & (location.novel_id == Event.novel_id),
            )
            .where(Event.novel_id == novel_id)
        )
        return {
            row.entity_id: (
                f"timeline_order={row.timeline_order}；"
                f"occurrence_time={row.occurrence_time_label or ''}；"
                f"location_entity_id={row.location_entity_id}"
                + (f"；location={location_name}" if location_name else "")
            )
            for row, location_name in result.all()
        }
