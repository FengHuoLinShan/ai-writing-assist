"""地理冲突检查"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.schemas import ReviewWarning
from modules.review.services.helpers import is_valid_uuid
from modules.review.services.protocol import CheckStrategy


class GeoCheck(CheckStrategy):
    """检查 6: 地理冲突检查 — 地点引用一致性和通行关系合理性"""

    @property
    def name(self) -> str:
        return "geo"

    async def check(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        warnings: list[ReviewWarning] = []

        location_ids: set[str] = set()

        entities = candidate_payload.get("world_entities", [])
        if isinstance(entities, dict):
            entities = [entities]

        for entity in entities if isinstance(entities, list) else []:
            if not isinstance(entity, dict):
                continue
            if entity.get("entity_type") == "location":
                eid = entity.get("id", "")
                if eid and isinstance(eid, str):
                    location_ids.add(eid)

        cards = candidate_payload.get("chapter_cards", [])
        if isinstance(cards, dict):
            cards = [cards]

        for card in cards if isinstance(cards, list) else []:
            if not isinstance(card, dict):
                continue
            for eid in card.get("involved_entity_ids", []):
                if isinstance(eid, str) and eid.strip():
                    location_ids.add(eid)

        if not location_ids:
            return warnings

        for lid in list(location_ids):
            if not is_valid_uuid(lid):
                continue
            try:
                from modules.geo.facade import get_location_context

                await get_location_context(db, novel_id, lid, depth=0)
            except Exception:
                warnings.append(
                    ReviewWarning(
                        type="geo_conflict",
                        message=f"引用的地理地点 {lid[:8]}... 在地理系统中不存在",
                        severity="medium",
                        location={"location_id": lid},
                    )
                )

        return warnings
