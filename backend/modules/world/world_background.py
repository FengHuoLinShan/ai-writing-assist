"""Derived world-background aggregation used by context activation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.token_estimation import estimate_token_count
from modules.world.contracts import (
    WorldBackgroundBundleContract,
    WorldBackgroundEntryContract,
)
from modules.world.map_models import MapFact
from modules.world.models import CharacterKnowledge, CoreEntity, EntityRelation
from shared.utils import parse_uuid


class WorldBackgroundAggregation:
    """Keep world-data selection local to the world module implementation."""

    async def build(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        context_mode: str = "canonical",
        limit: int = 160,
    ) -> WorldBackgroundBundleContract:
        nid = parse_uuid(novel_id, "novel_id")
        statuses = ["canonical"]
        if context_mode == "working":
            statuses.append("draft")
        entries: list[WorldBackgroundEntryContract] = []

        entities = await db.execute(
            select(CoreEntity)
            .where(CoreEntity.novel_id == nid, CoreEntity.status.in_(statuses))
            .order_by(CoreEntity.importance.desc(), CoreEntity.name.asc())
            .limit(limit)
        )
        for entity in entities.scalars().all():
            summary = entity.summary or entity.public_info or entity.name
            entries.append(
                self._entry(
                    novel_id,
                    "entity",
                    str(entity.id),
                    entity.name,
                    summary,
                    f"{entity.entity_type}:{entity.name}",
                    float(entity.importance or 0.5),
                    entity.status,
                    entity.reveal_level,
                    self._keywords(entity.name, entity.content_json),
                )
            )

        relations = await db.execute(
            select(EntityRelation)
            .where(EntityRelation.novel_id == nid, EntityRelation.status.in_(statuses))
            .order_by(EntityRelation.strength.desc())
            .limit(limit)
        )
        for relation in relations.scalars().all():
            title = relation.relation_type
            summary = relation.description or relation.relation_type
            entries.append(
                self._entry(
                    novel_id,
                    "relation",
                    str(relation.id),
                    title,
                    summary,
                    f"relation:{relation.relation_type}",
                    float(relation.strength or 0.5),
                    relation.status,
                    "author_safe",
                    [relation.relation_type],
                )
            )

        facts = await db.execute(
            select(MapFact)
            .where(MapFact.novel_id == nid, MapFact.fact_status == "confirmed")
            .order_by(MapFact.confidence.desc())
            .limit(limit)
        )
        for fact in facts.scalars().all():
            title = fact.target_name or fact.dynamic_type
            summary = fact.evidence_text or str(
                fact.value_json or fact.spatial_anchor or ""
            )
            entries.append(
                self._entry(
                    novel_id,
                    "map_fact",
                    str(fact.id),
                    title,
                    summary,
                    f"map:{fact.dynamic_type}",
                    float(fact.confidence or 0.5),
                    fact.fact_status,
                    "author_safe",
                    [title, fact.dynamic_type],
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
        clean_summary = " ".join(str(summary or "").split())[:1000]
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
            source_ids=[{"type": asset_type, "id": asset_id}],
            token_count=estimate_token_count(f"{title} {clean_summary}"),
        )

    @staticmethod
    def _keywords(name: str, content: dict | None) -> list[str]:
        aliases = (content or {}).get("aliases") or []
        values = [name]
        for item in aliases:
            values.append(str(item.get("alias") if isinstance(item, dict) else item))
        return values
