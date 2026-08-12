"""Author-facing attention summary owned by the World module."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.contracts import WorldAttentionSummaryContract
from modules.world.services.core.entity_alias_service import EntityAliasService
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.services.core.entity_service import WorldEntityService


class WorldAttentionSummaryService:
    """Aggregate existing World review queues without leaking their raw shapes."""

    def __init__(
        self,
        *,
        entity_service: WorldEntityService | None = None,
        alias_service: EntityAliasService | None = None,
        relation_service: EntityRelationService | None = None,
    ) -> None:
        self._entity_service = entity_service or WorldEntityService()
        self._alias_service = alias_service or EntityAliasService()
        self._relation_service = relation_service or EntityRelationService()

    async def get_summary(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> WorldAttentionSummaryContract:
        entities = await self._entity_service.list(
            db,
            novel_id,
            display_state="review",
            skip=0,
            limit=1,
        )
        aliases = await self._alias_service.list_review_groups(
            db,
            novel_id,
            skip=0,
            limit=1,
        )
        relations = await self._relation_service.list_review_groups(
            db,
            novel_id,
            skip=0,
            limit=1,
        )
        return WorldAttentionSummaryContract(
            novel_id=novel_id,
            world_objects=int(entities.total or 0),
            world_aliases=int(aliases.item_total or 0),
            world_relations=int(relations.item_total or 0),
        )
