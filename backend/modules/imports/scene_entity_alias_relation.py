"""Phase 2b alias and relation extraction strategy."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.scene_entity_config import PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class AliasRelationExtractor:
    """Runs alias/relation extraction against working world objects."""

    def __init__(self, service: Any) -> None:
        self.service = service

    async def run(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        service = self.service
        total_aliases = 0
        total_relations = 0
        completed_scenes = 0
        failed_scenes: list[int] = []
        error_kind: str | None = None
        error_message: str | None = None

        for scene in scenes:
            raw_scene_index = (
                scene.get("scene_index")
                if isinstance(scene, dict)
                else getattr(scene, "scene_index", 0)
            )
            try:
                scene_index = int(raw_scene_index or 0)
            except (TypeError, ValueError):
                scene_index = 0
            scene_id = service._scene_id(scene)

            snapshot_id: str | None = None
            result_refs: list[dict[str, str]] = []
            try:
                chapters_text = await service._load_scene_chapters(db, scene)
                if not chapters_text:
                    continue
                entity_index = await service._build_alias_relation_entity_index(
                    db,
                    str(nid),
                )
                snapshot = await service._create_phase2b_snapshot(
                    db,
                    nid,
                    scene,
                    chapters_text,
                    entity_index,
                    workflow_id=workflow_id,
                )
                snapshot_id = snapshot.id
                output = await asyncio.wait_for(
                    service._call_alias_relation_extraction(
                        chapters_text,
                        entity_index,
                    ),
                    timeout=PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS,
                )
                persisted = await service._persist_alias_relation_output(
                    db,
                    str(nid),
                    output,
                    scene_index=scene_index,
                    workflow_id=workflow_id,
                    scene_id=scene_id,
                    result_refs=result_refs,
                )
                total_aliases += persisted["aliases"]
                total_relations += persisted["relations"]
                completed_scenes += 1
                if snapshot_id is not None:
                    from modules.context.facade import mark_context_snapshot_succeeded

                    await mark_context_snapshot_succeeded(
                        db,
                        snapshot_id=snapshot_id,
                        result_refs=result_refs,
                    )
            except Exception as exc:
                error_kind = service._error_kind(exc)
                error_message = str(exc)[:300]
                failed_scenes.append(scene_index)
                logger.warning(
                    "Alias/relation extraction failed for scene %s: %s",
                    scene_index,
                    exc,
                )
                if snapshot_id is not None:
                    from modules.context.facade import mark_context_snapshot_failed

                    await mark_context_snapshot_failed(
                        db,
                        snapshot_id=snapshot_id,
                        error_kind=error_kind,
                        error_message=error_message,
                    )

        return {
            "total_aliases": total_aliases,
            "total_relations": total_relations,
            "alias_relation_scenes": completed_scenes,
            "alias_relation_failed_scenes": failed_scenes,
            "degraded": bool(failed_scenes),
            "error_kind": error_kind,
            "error_message": error_message,
        }

    async def build_entity_index(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> str:
        from modules.world.facade import list_entities

        entities = await list_entities(
            db,
            novel_id,
            statuses=("canonical", "draft", "candidate"),
            limit=10000,
        )
        if not entities:
            return "无可用对象"
        lines = ["## 可用对象索引"]
        for entity in entities:
            lines.append(
                "- "
                f"{entity.get('name')} ({entity.get('entity_type')}) "
                f"id={entity.get('id')}"
            )
        return "\n".join(lines)
