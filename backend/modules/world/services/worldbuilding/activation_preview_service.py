"""Worldbuilding activation preview service."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import (
    CoreEntity,
    EntityRelation,
    WorldBiblePage,
)
from modules.world.services.worldbuilding.shared import CONFIRMED_STATUSES
from shared.target_ref import TargetRef, normalize_target_ref
from shared.utils import parse_uuid


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

__all__ = ['ActivationPreviewService']
