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
        excluded_items: list[dict[str, Any]] = []
        rule_evaluations: list[dict[str, Any]] = []
        explicit_ids = [*list(entity_ids or [])]
        if focus_entity_id:
            explicit_ids.append(focus_entity_id)
        explicit_matches = 0
        for entity_id in explicit_ids:
            entity = await self._entity_or_none(db, nid, entity_id)
            if entity:
                self._add_entity(candidates, entity, "explicit", "request parameter")
                explicit_matches += 1
            else:
                excluded_items.append(
                    self._excluded_target(
                        target_type="core_entity",
                        target_id=str(entity_id),
                        reason="target_missing",
                        activation_reason="explicit request parameter",
                    )
                )
        rule_evaluations.append(
            self._rule_evaluation(
                "legacy_explicit",
                matched=explicit_matches > 0,
                candidate_count=explicit_matches,
                matched_clauses=["explicit_target"] if explicit_matches else [],
                blocked_clauses=[] if explicit_matches else ["target_missing"],
            )
        )
        if map_id:
            warnings.append("map_focus_explicit")
        elif scene_id or focus_entity_id:
            warnings.append("map_focus_requires_confirmed_summary_or_explicit_map")
        if depth >= 1:
            before_relations = len(candidates)
            await self._expand_relations(db, nid, candidates, source="relation")
            relation_count = len(candidates) - before_relations
            rule_evaluations.append(
                self._rule_evaluation(
                    "canonical_relation_expand",
                    matched=relation_count > 0,
                    candidate_count=relation_count,
                    matched_clauses=["canonical_relation"] if relation_count else [],
                )
            )
        if depth >= 2:
            before_pages = len(candidates)
            await self._expand_page_links(
                db,
                nid,
                candidates,
                excluded_items=excluded_items,
            )
            page_count = len(candidates) - before_pages
            rule_evaluations.append(
                self._rule_evaluation(
                    "published_page_link_expand",
                    matched=page_count > 0,
                    candidate_count=page_count,
                    matched_clauses=["page_linked"] if page_count else [],
                )
            )
        ranked = sorted(
            candidates.values(),
            key=lambda item: (-item["score"], item["target_hash"]),
        )
        for item in ranked[top_k:]:
            excluded_items.append(
                {
                    **item,
                    "decision": "excluded",
                    "excluded_reason": "rule_top_k",
                }
            )
        return {
            "novel_id": str(nid),
            "depth": depth,
            "top_k": top_k,
            "items": ranked[:top_k],
            "excluded_items": excluded_items,
            "profile": None,
            "rule_evaluations": rule_evaluations,
            "budget_events": [],
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
        *,
        excluded_items: list[dict[str, Any]],
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
                    target = self._normalize_page_target(raw_target)
                except Exception:
                    excluded_items.append(
                        self._excluded_target(
                            target_type="invalid",
                            target_id="invalid",
                            reason="target_missing",
                            activation_reason=f"linked from page {page.title}",
                        )
                    )
                    continue
                if target.target_type == "core_entity":
                    entity = await self._entity_or_none(
                        db,
                        novel_id,
                        target.target_id,
                    )
                    if entity is None or entity.status not in CONFIRMED_STATUSES:
                        excluded_items.append(
                            self._excluded_target(
                                target_type=target.target_type,
                                target_id=target.target_id,
                                reason=(
                                    "target_archived"
                                    if entity is not None
                                    else "target_missing"
                                ),
                                activation_reason=f"linked from page {page.title}",
                            )
                        )
                        continue
                    self._add_entity(
                        candidates,
                        entity,
                        "page_linked",
                        f"linked from page {page.title}",
                    )
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
                        "decision": "included",
                        "activation_reason": f"linked from page {page.title}",
                        "token_before": 0,
                        "token_after": 0,
                        "expanded_from": {
                            "target_type": "world_bible_page",
                            "target_id": str(page.id),
                            "target_path": "",
                        },
                        "excluded_reason": None,
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
        importance = int(
            (entity.importance if entity.importance is not None else 0) * 1000
        )
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
            "decision": "included",
            "activation_reason": reason,
            "token_before": 0,
            "token_after": 0,
            "expanded_from": None,
            "excluded_reason": None,
        }

    @staticmethod
    def _normalize_page_target(raw_target: dict[str, Any]) -> TargetRef:
        if "target_type" in raw_target or "target_id" in raw_target:
            return normalize_target_ref(raw_target)
        target_type = str(raw_target.get("type") or raw_target.get("source_type") or "")
        target_id = str(raw_target.get("id") or raw_target.get("source_id") or "")
        aliases = {
            "entity": "core_entity",
            "profile": "core_entity",
            "event": "core_entity",
            "page": "world_bible_page",
            "relation": "entity_relation",
        }
        return TargetRef(
            target_type=aliases.get(target_type, target_type),
            target_id=target_id,
            target_path=str(raw_target.get("target_path") or ""),
            relation=str(raw_target.get("relation") or "informs"),
        )

    @staticmethod
    def _excluded_target(
        *,
        target_type: str,
        target_id: str,
        reason: str,
        activation_reason: str,
    ) -> dict[str, Any]:
        try:
            target = TargetRef(target_type=target_type, target_id=target_id)
            target_dict = target.canonical_dict()
            target_hash = target.target_hash()
        except Exception:
            target_dict = {
                "target_type": "invalid",
                "target_id": "invalid",
                "target_path": "",
            }
            target_hash = ""
        return {
            "target": target_dict,
            "target_hash": target_hash,
            "score": 0,
            "source": "excluded",
            "reason": activation_reason,
            "label": target_id,
            "decision": "excluded",
            "activation_reason": activation_reason,
            "token_before": 0,
            "token_after": 0,
            "expanded_from": None,
            "excluded_reason": reason,
        }

    @staticmethod
    def _rule_evaluation(
        rule_id: str,
        *,
        matched: bool,
        candidate_count: int,
        matched_clauses: list[str] | None = None,
        blocked_clauses: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "rule_id": rule_id,
            "matched": matched,
            "matched_clauses": matched_clauses or [],
            "blocked_clauses": blocked_clauses or [],
            "candidate_count": candidate_count,
        }


__all__ = ["ActivationPreviewService"]
