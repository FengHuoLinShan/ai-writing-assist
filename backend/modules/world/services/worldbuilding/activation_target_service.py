"""Resolve fixed activation TargetRefs behind the world facade boundary."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import deque
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.token_estimation import estimate_token_count
from modules.world.contracts import (
    WorldBibleActivationResolutionContract,
    WorldBibleActivationTargetContract,
)
from modules.world.models import (
    CoreEntity,
    EntityRelation,
    WorldBiblePage,
    WorldBiblePageProjection,
)
from modules.world.services.worldbuilding.shared import CONFIRMED_STATUSES
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from shared.target_ref import TargetRef, normalize_target_ref
from shared.utils import parse_uuid


class WorldBibleActivationTargetService:
    """Novel-scoped resolver for published pages and adopted world objects."""

    async def resolve(
        self,
        db: AsyncSession,
        novel_id: str,
        target_refs: list[dict[str, Any]],
        *,
        projection_type: str = "context_brief",
        expand_page_links: bool = False,
        relation_types: list[str] | None = None,
        max_depth: int = 0,
        reveal_mode: str = "author_safe",
    ) -> WorldBibleActivationResolutionContract:
        nid = parse_uuid(novel_id, "novel_id")
        relation_filter = set(relation_types or [])
        max_depth = max(0, min(int(max_depth), 2))
        queue: deque[tuple[TargetRef, int, dict[str, str] | None, str]] = deque()
        excluded: list[WorldBibleActivationTargetContract] = []
        for raw in target_refs[:256]:
            try:
                queue.append((normalize_target_ref(raw), 0, None, "explicit"))
            except Exception:
                excluded.append(self._excluded(novel_id, raw, reason="target_missing"))

        items: list[WorldBibleActivationTargetContract] = []
        visited: set[str] = set()
        while queue and len(visited) < 256:
            target, depth, expanded_from, source_kind = queue.popleft()
            target_hash = target.target_hash()
            if target_hash in visited:
                continue
            visited.add(target_hash)
            resolved = await self._resolve_one(
                db,
                nid,
                target,
                projection_type=projection_type,
                reveal_mode=reveal_mode,
                expanded_from=expanded_from,
                source_kind=source_kind,
            )
            if resolved.excluded_reason:
                excluded.append(resolved)
                continue
            items.append(resolved)
            if depth >= max_depth:
                continue
            if target.target_type == "world_bible_page" and expand_page_links:
                for raw_link in resolved.linked_target_refs:
                    try:
                        linked = normalize_target_ref(raw_link)
                    except Exception:
                        excluded.append(
                            self._excluded(
                                novel_id,
                                raw_link,
                                reason="target_missing",
                                expanded_from=target.canonical_dict(),
                            )
                        )
                        continue
                    queue.append(
                        (
                            linked,
                            depth + 1,
                            target.canonical_dict(),
                            "page_linked",
                        )
                    )
            if target.target_type == "core_entity" and relation_filter:
                related = await self._related_targets(
                    db,
                    nid,
                    target.target_id,
                    relation_filter,
                )
                queue.extend(
                    (
                        related_target,
                        depth + 1,
                        target.canonical_dict(),
                        "relation",
                    )
                    for related_target in related
                )
        return WorldBibleActivationResolutionContract(
            novel_id=str(nid),
            items=items,
            excluded_items=excluded,
        )

    async def page_source_manifest(
        self,
        db: AsyncSession,
        novel_id: str,
        page_ids: list[str],
    ) -> list[dict[str, Any]]:
        nid = parse_uuid(novel_id, "novel_id")
        parsed_ids: list[uuid.UUID] = []
        for page_id in page_ids[:256]:
            try:
                parsed_ids.append(parse_uuid(page_id, "page_id"))
            except Exception:
                continue
        if not parsed_ids:
            return []
        result = await db.execute(
            select(WorldBiblePage).where(
                WorldBiblePage.novel_id == nid,
                WorldBiblePage.id.in_(parsed_ids),
            )
        )
        return [
            {
                "page_id": str(page.id),
                "version_number": page.version_number,
                "template_key": page.template_key,
                "template_version": page.template_version,
                "source_hash": WorldBibleLifecycleService.projection_source_hash(page),
                "section_ids": [
                    str(item.get("section_id")) for item in page.sections_json or []
                ],
                "status": page.status,
            }
            for page in result.scalars().all()
        ]

    async def _resolve_one(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        target: TargetRef,
        *,
        projection_type: str,
        reveal_mode: str,
        expanded_from: dict[str, str] | None,
        source_kind: str,
    ) -> WorldBibleActivationTargetContract:
        if target.target_type == "core_entity":
            return await self._resolve_entity(
                db,
                novel_id,
                target,
                reveal_mode=reveal_mode,
                expanded_from=expanded_from,
                source_kind=source_kind,
            )
        if target.target_type == "world_bible_page":
            return await self._resolve_page(
                db,
                novel_id,
                target,
                projection_type=projection_type,
                reveal_mode=reveal_mode,
                expanded_from=expanded_from,
                source_kind=source_kind,
            )
        return self._excluded(
            str(novel_id),
            target.canonical_dict(),
            reason="target_missing",
            expanded_from=expanded_from,
        )

    async def _resolve_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        target: TargetRef,
        *,
        reveal_mode: str,
        expanded_from: dict[str, str] | None,
        source_kind: str,
    ) -> WorldBibleActivationTargetContract:
        try:
            target_id = parse_uuid(target.target_id, "target_id")
        except Exception:
            return self._excluded(
                str(novel_id),
                target.canonical_dict(),
                reason="target_missing",
                expanded_from=expanded_from,
            )
        entity = await db.scalar(
            select(CoreEntity).where(
                CoreEntity.novel_id == novel_id,
                CoreEntity.id == target_id,
            )
        )
        if entity is None:
            return self._excluded(
                str(novel_id),
                target.canonical_dict(),
                reason="target_missing",
                expanded_from=expanded_from,
            )
        if entity.status not in CONFIRMED_STATUSES:
            reason = (
                "target_archived"
                if entity.status in {"archived", "deprecated"}
                else "candidate_not_allowed"
            )
            return self._excluded(
                str(novel_id),
                target.canonical_dict(),
                reason=reason,
                label=entity.name,
                status=entity.status,
                expanded_from=expanded_from,
            )
        parts = [entity.name, entity.summary or "", entity.public_info or ""]
        if reveal_mode == "author_full":
            parts.append(entity.hidden_truth or "")
        content = "\n\n".join(part.strip() for part in parts if part.strip())
        source_hash = hashlib.sha256(
            json.dumps(
                {
                    "id": str(entity.id),
                    "status": entity.status,
                    "name": entity.name,
                    "summary": entity.summary,
                    "public_info": entity.public_info,
                    "hidden_truth": entity.hidden_truth,
                    "content_json": entity.content_json,
                    "updated_at": (
                        entity.updated_at.isoformat() if entity.updated_at else None
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return WorldBibleActivationTargetContract(
            novel_id=str(novel_id),
            target=target.canonical_dict(),
            target_hash=target.target_hash(),
            label=entity.name,
            status=entity.status,
            importance=float(
                entity.importance if entity.importance is not None else 0.0
            ),
            content=content,
            token_count=estimate_token_count(content),
            source_kind=source_kind,
            source_hash=source_hash,
            expanded_from=expanded_from,
        )

    async def _resolve_page(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        target: TargetRef,
        *,
        projection_type: str,
        reveal_mode: str,
        expanded_from: dict[str, str] | None,
        source_kind: str,
    ) -> WorldBibleActivationTargetContract:
        try:
            target_id = parse_uuid(target.target_id, "target_id")
        except Exception:
            return self._excluded(
                str(novel_id),
                target.canonical_dict(),
                reason="target_missing",
                expanded_from=expanded_from,
            )
        page = await db.scalar(
            select(WorldBiblePage).where(
                WorldBiblePage.novel_id == novel_id,
                WorldBiblePage.id == target_id,
            )
        )
        if page is None:
            return self._excluded(
                str(novel_id),
                target.canonical_dict(),
                reason="target_missing",
                expanded_from=expanded_from,
            )
        if page.status not in CONFIRMED_STATUSES:
            return self._excluded(
                str(novel_id),
                target.canonical_dict(),
                reason="target_archived",
                label=page.title,
                status=page.status,
                expanded_from=expanded_from,
            )
        source_hash = WorldBibleLifecycleService.projection_source_hash(page)
        projection = await db.scalar(
            select(WorldBiblePageProjection).where(
                WorldBiblePageProjection.novel_id == novel_id,
                WorldBiblePageProjection.page_id == page.id,
                WorldBiblePageProjection.projection_type == projection_type,
            )
        )
        ready = bool(
            projection
            and projection.status == "ready"
            and not projection.stale
            and projection.source_hash == source_hash
            and projection.content
        )
        if ready:
            content = str(projection.content)
            warnings: list[str] = []
        else:
            content = self._fallback_page_content(page, reveal_mode=reveal_mode)
            warnings = ["projection_stale"]
        linked_refs: list[dict[str, str]] = []
        for raw in page.linked_asset_refs_json or []:
            try:
                linked_refs.append(self._normalize_legacy_ref(raw).canonical_dict())
            except Exception:
                continue
        return WorldBibleActivationTargetContract(
            novel_id=str(novel_id),
            target=target.canonical_dict(),
            target_hash=target.target_hash(),
            label=page.title,
            status=page.status,
            content=content,
            token_count=estimate_token_count(content),
            source_kind=source_kind,
            source_version=page.version_number,
            source_hash=source_hash,
            linked_target_refs=linked_refs,
            expanded_from=expanded_from,
            fallback=not ready,
            warnings=warnings,
        )

    async def _related_targets(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: str,
        relation_types: set[str],
    ) -> list[TargetRef]:
        try:
            seed = parse_uuid(entity_id, "entity_id")
        except Exception:
            return []
        result = await db.execute(
            select(EntityRelation).where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.status.in_(list(CONFIRMED_STATUSES)),
                EntityRelation.relation_type.in_(sorted(relation_types)),
                or_(
                    EntityRelation.source_id == seed,
                    EntityRelation.target_id == seed,
                ),
            )
        )
        targets = {
            str(relation.target_id if relation.source_id == seed else relation.source_id)
            for relation in result.scalars().all()
        }
        return [
            TargetRef(target_type="core_entity", target_id=target_id)
            for target_id in sorted(targets)
        ]

    @staticmethod
    def _fallback_page_content(page: WorldBiblePage, *, reveal_mode: str) -> str:
        parts = [str(page.free_text or "").strip()]
        parts.extend(
            str(section.get("body_markdown") or "").strip()
            for section in sorted(
                page.sections_json or [],
                key=lambda item: (
                    item.get("sort_order", 0),
                    item.get("section_id", ""),
                ),
            )
            if section.get("projection_policy", "eligible") == "eligible"
            and (
                reveal_mode == "author_full"
                or section.get("sensitivity_hint", "author_safe") != "author_only"
            )
        )
        return "\n\n".join(part for part in parts if part)[:8000]

    @staticmethod
    def _normalize_legacy_ref(raw: dict[str, Any]) -> TargetRef:
        if "target_type" in raw or "target_id" in raw:
            return normalize_target_ref(raw)
        aliases = {
            "entity": "core_entity",
            "profile": "core_entity",
            "event": "core_entity",
            "page": "world_bible_page",
            "relation": "entity_relation",
        }
        target_type = str(raw.get("type") or raw.get("source_type") or "")
        return TargetRef(
            target_type=aliases.get(target_type, target_type),
            target_id=str(raw.get("id") or raw.get("source_id") or ""),
            target_path=str(raw.get("target_path") or ""),
        )

    @staticmethod
    def _excluded(
        novel_id: str,
        raw: dict[str, Any],
        *,
        reason: str,
        label: str = "",
        status: str = "missing",
        expanded_from: dict[str, str] | None = None,
    ) -> WorldBibleActivationTargetContract:
        try:
            target = normalize_target_ref(raw)
            canonical = target.canonical_dict()
            target_hash = target.target_hash()
        except Exception:
            canonical = {
                "target_type": "invalid",
                "target_id": "invalid",
                "target_path": "",
            }
            target_hash = ""
        return WorldBibleActivationTargetContract(
            novel_id=novel_id,
            target=canonical,
            target_hash=target_hash,
            label=label or canonical["target_id"],
            status=status,
            expanded_from=expanded_from,
            excluded_reason=reason,
        )


__all__ = ["WorldBibleActivationTargetService"]
