"""地理地点加载器（修复 N+1 查询）"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class GeoLocationsLoader(Loader):
    """加载地理地点，使用批量查询避免 N+1"""

    @property
    def name(self) -> str:
        return "geo_locations"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        if not options.location_ids and not bundle.world_entities:
            return

        geo_limit = CONTEXT_BUDGET.get("geo_relations", 10)

        if options.location_ids:
            location_ids = options.location_ids[:geo_limit]
        else:
            location_ids = [
                e.get("entity_id", e.get("id", ""))
                for e in bundle.world_entities
                if e.get("entity_type") == "location"
            ][:geo_limit]

        if not location_ids:
            bundle.geo_locations = []
            bundle.budget_used["geo_relations"] = 0
            return

        # 批量查询地点（并行，避免 N+1）
        from modules.geo.facade import get_locations_context_batch

        results = await get_locations_context_batch(
            db, options.novel_id, location_ids, depth=1
        )
        locations = []
        for ctx in results:
            if ctx and ctx.location:
                loc_data = {
                    "location": ctx.location,
                    "parent_locations": [
                        p.model_dump() if hasattr(p, "model_dump") else p
                        for p in ctx.parent_locations
                    ],
                    "child_locations": [
                        c.model_dump() if hasattr(c, "model_dump") else c
                        for c in ctx.child_locations
                    ],
                    "edges": [
                        e.model_dump() if hasattr(e, "model_dump") else e
                        for e in ctx.edges
                    ],
                    "current_era": ctx.current_era,
                }
                locations.append(loc_data)
        bundle.geo_locations = locations
        bundle.budget_used["geo_relations"] = min(len(locations), geo_limit)
