"""Repair persisted deep-import display data.

This module fixes deterministic persistence/display gaps from older deep-import
runs. It does not call an LLM.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import container
from modules.imports.workflow_structure_phase import (
    ensure_minimum_structure_outputs,
    minimum_structure_category_targets,
)
from modules.outline.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
)
from modules.outline.repositories import SceneRepository
from modules.outline.services import (
    ForeshadowingPlanService,
    OutlineArcService,
    PlotThreadService,
    RevealPlanService,
)
from modules.world.entity_facade import list_entities
from modules.world.models import CoreEntity
from shared.utils import parse_uuid


@dataclass(slots=True)
class DeepImportDisplayRepairResult:
    scenes_reindexed: int = 0
    aliases_repaired: int = 0
    structure_before: dict[str, int] | None = None
    structure_after: dict[str, int] | None = None


class DeepImportDisplayRepairService:
    """Deterministic repair for already-persisted deep import outputs."""

    async def repair(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None = None,
        start_chapter: int = 1,
        end_chapter: int | None = None,
    ) -> DeepImportDisplayRepairResult:
        nid = parse_uuid(novel_id, "novel_id")
        scenes_reindexed = await self.reindex_scenes(db, nid)
        aliases_repaired = await self.repair_alias_metadata(db, nid)
        before = await self.structure_counts(db, nid)
        if end_chapter is None:
            end_chapter = max(start_chapter, await self._max_scene_chapter(db, nid))
        await self.ensure_structure_minimums(
            db,
            novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            workflow_id=workflow_id,
        )
        after = await self.structure_counts(db, nid)
        return DeepImportDisplayRepairResult(
            scenes_reindexed=scenes_reindexed,
            aliases_repaired=aliases_repaired,
            structure_before=before,
            structure_after=after,
        )

    async def reindex_scenes(self, db: AsyncSession, novel_id: uuid.UUID) -> int:
        scenes = await self._scenes(db, novel_id)
        ordered = sorted(
            scenes,
            key=lambda scene: (
                self._scene_chapter_sort_key(scene),
                scene.created_at,
                str(scene.id),
            ),
        )
        current_order = [scene.id for scene in scenes]
        desired_order = [scene.id for scene in ordered]
        already_indexed = all(
            scene.scene_index == index for index, scene in enumerate(ordered)
        )
        if current_order == desired_order and already_indexed:
            return 0
        return await SceneRepository().reorder(db, novel_id, desired_order)

    async def repair_alias_metadata(self, db: AsyncSession, novel_id: uuid.UUID) -> int:
        stmt = select(CoreEntity).where(CoreEntity.novel_id == novel_id)
        result = await db.execute(stmt)
        repaired = 0
        for entity in result.scalars().all():
            content = dict(entity.content_json or {})
            meta = content.get("_meta") or {}
            if meta.get("source") != "deep_import":
                continue
            aliases = content.get("aliases") or []
            if not isinstance(aliases, list):
                continue
            next_aliases: list[dict[str, Any]] = []
            changed = False
            for alias_item in aliases:
                normalized = self._normalize_alias(alias_item, meta)
                if normalized is None:
                    changed = True
                    continue
                if normalized != alias_item:
                    changed = True
                    repaired += 1
                next_aliases.append(normalized)
            if changed:
                content["aliases"] = next_aliases
                entity.content_json = content
        await db.flush()
        return repaired

    async def ensure_structure_minimums(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        start_chapter: int,
        end_chapter: int,
        workflow_id: str | None,
    ) -> dict[str, int]:
        self._ensure_structure_container()
        nid = parse_uuid(novel_id, "novel_id")
        result = await self._structure_result_payload(db, nid)
        updated = await ensure_minimum_structure_outputs(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            result,
            workflow_id=workflow_id,
        )
        return {
            key: int(value)
            for key, value in (updated.get("extra_sections") or {})
            .get("structure_counts", {})
            .items()
        }

    async def structure_counts(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> dict[str, int]:
        return {
            "threads": await self._count(db, PlotThread, novel_id),
            "arcs": await self._count(db, OutlineArc, novel_id),
            "foreshadowing": await self._count(db, ForeshadowingPlan, novel_id),
            "reveals": await self._count(db, RevealPlan, novel_id),
        }

    async def snapshot(self, db: AsyncSession, novel_id: str) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self._scenes(db, nid)
        alias_missing = 0
        alias_total = 0
        entity_result = await db.execute(
            select(CoreEntity).where(CoreEntity.novel_id == nid)
        )
        for entity in entity_result.scalars().all():
            content = entity.content_json or {}
            for alias_item in content.get("aliases") or []:
                alias_total += 1
                if not (
                    isinstance(alias_item, dict)
                    and alias_item.get("source")
                    and alias_item.get("status")
                ):
                    alias_missing += 1
        chapter_count = max(1, await self._max_scene_chapter(db, nid))
        return {
            "novel_id": novel_id,
            "scene_count": len(scenes),
            "scene_index_counts": self._scene_index_counts(scenes),
            "alias_total": alias_total,
            "alias_missing_metadata": alias_missing,
            "structure_counts": await self.structure_counts(db, nid),
            "structure_targets": minimum_structure_category_targets(chapter_count),
        }

    async def _structure_result_payload(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> dict[str, Any]:
        threads = (
            await db.execute(select(PlotThread).where(PlotThread.novel_id == novel_id))
        ).scalars().all()
        arcs = (
            await db.execute(select(OutlineArc).where(OutlineArc.novel_id == novel_id))
        ).scalars().all()
        foreshadowing = (
            await db.execute(
                select(ForeshadowingPlan).where(ForeshadowingPlan.novel_id == novel_id)
            )
        ).scalars().all()
        reveals = (
            await db.execute(select(RevealPlan).where(RevealPlan.novel_id == novel_id))
        ).scalars().all()
        return {
            "total_threads": len(threads),
            "total_arcs": len(arcs),
            "threads": [{"id": str(item.id), "name": item.name} for item in threads],
            "arcs": [
                {
                    "id": str(item.id),
                    "title": item.title,
                    "arc_index": item.arc_index,
                }
                for item in arcs
            ],
            "extra_sections": {
                "foreshadowing_plans": [
                    {"id": str(item.id), "name": item.name} for item in foreshadowing
                ],
                "reveal_plans": [
                    {"id": str(item.id), "target_id": str(item.target_id)}
                    for item in reveals
                ],
            },
        }

    def _ensure_structure_container(self) -> None:
        services = {
            "outline.thread_service": PlotThreadService(),
            "outline.arc_service": OutlineArcService(),
            "outline.foreshadowing_service": ForeshadowingPlanService(),
            "outline.reveal_service": RevealPlanService(),
            "world.list_entities": list_entities,
        }
        for name, service in services.items():
            try:
                container.get(name)
            except KeyError:
                container.register(name, service)

    async def _scenes(self, db: AsyncSession, novel_id: uuid.UUID) -> list[Scene]:
        result = await db.execute(select(Scene).where(Scene.novel_id == novel_id))
        return list(result.scalars().all())

    async def _max_scene_chapter(self, db: AsyncSession, novel_id: uuid.UUID) -> int:
        chapters = [
            self._scene_chapter_sort_key(scene)
            for scene in await self._scenes(db, novel_id)
        ]
        return max([chapter for chapter in chapters if chapter > 0], default=1)

    async def _count(self, db: AsyncSession, model, novel_id: uuid.UUID) -> int:
        result = await db.execute(select(model).where(model.novel_id == novel_id))
        return len(result.scalars().all())

    def _scene_chapter_sort_key(self, scene: Scene) -> int:
        chunks = scene.scene_chunks or []
        chapter_indices: list[int] = []
        for chunk in chunks:
            if isinstance(chunk, dict) and chunk.get("chapter_index") is not None:
                chapter_indices.append(int(chunk["chapter_index"]))
        if chapter_indices:
            return min(chapter_indices)
        for chapter_id in scene.chapter_ids or []:
            try:
                return int(chapter_id)
            except (TypeError, ValueError):
                continue
        return scene.scene_index

    def _normalize_alias(
        self,
        alias_item: Any,
        meta: dict[str, Any],
    ) -> dict[str, Any] | None:
        if isinstance(alias_item, dict):
            raw_alias = alias_item.get("alias") or alias_item.get("name") or ""
            alias_type = alias_item.get("type") or alias_item.get("alias_type") or "alias"
            quote = alias_item.get("quote")
            confidence = alias_item.get("confidence")
        else:
            raw_alias = alias_item
            alias_type = "alias"
            quote = None
            confidence = None
        alias_text = " ".join(str(raw_alias).strip().split())
        if not alias_text:
            return None
        return {
            "alias": alias_text,
            "type": alias_type,
            "status": "candidate",
            "source": "deep_import",
            "workflow_id": meta.get("workflow_id"),
            "scene_id": meta.get("scene_id"),
            "scene_index": meta.get("source_scene_index"),
            "confidence": (
                confidence if confidence is not None else meta.get("confidence")
            ),
            "quote": quote,
            "needs_review": True,
        }

    def _scene_index_counts(self, scenes: list[Scene]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for scene in scenes:
            key = str(scene.scene_index)
            counts[key] = counts.get(key, 0) + 1
        return counts
