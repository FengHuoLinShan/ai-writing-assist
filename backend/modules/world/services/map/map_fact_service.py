from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_schemas import (
    MapFactListResponse,
    MapFactResponse,
    MapFactStatusUpdate,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_dynamic_lifecycle import MapDynamicLifecycle


class MapFactService:
    """Delegated dynamic-map service."""

    def __init__(self, owner: MapDynamicLifecycle) -> None:
        self.owner = owner

    async def list_facts(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str | None = None,
        fact_status: str | None = "confirmed",
        skip: int = 0,
        limit: int = 100,
    ) -> MapFactListResponse:
        owner = self.owner
        mid = None
        if map_id:
            await owner._ctx.require_map(db, novel_id, map_id)
            mid = parse_uuid(map_id, "map_id")
        nid = parse_uuid(novel_id, "novel_id")
        items, total = await owner._fact_repo.list(
            db,
            nid,
            map_id=mid,
            fact_status=fact_status,
            skip=skip,
            limit=limit,
        )
        return MapFactListResponse(
            items=[MapFactResponse.model_validate(item) for item in items],
            total=total,
        )

    async def update_fact_status(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        fact_id: str,
        data: MapFactStatusUpdate,
    ) -> MapFactResponse:
        owner = self.owner
        await owner._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        fid = parse_uuid(fact_id, "fact_id")
        fact = await owner._fact_repo.get(db, fid)
        owner._assert_fact_access(fact, fact_id, nid, mid)
        updated = await owner._fact_repo.update_status(db, fact, data.fact_status)
        assert updated is not None
        from modules.world.services.worldbuilding.synopsis_invalidation import (
            mark_synopsis_source_changed,
        )

        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="map_fact",
            source_id=fact_id,
        )
        return MapFactResponse.model_validate(updated)
