"""Serial per-scene Phase 2a extraction."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _optional_lock(lock):
    if lock is None:
        yield
        return
    async with lock:
        yield


class SingleSceneEntityExtractionMixin:
    """Internal one-Scene Phase 2a implementation."""

    async def _process_scene(
        self,
        db: AsyncSession,
        nid,
        scene: dict[str, Any],
        scene_idx: int,
        existing_context: str,
        accumulated_memory: list[dict],
        seen_entity_keys: set[tuple[str, str]],
        workflow_id: str | None = None,
        authorization_snapshot: dict[str, Any] | None = None,
        persistence_stats: dict[str, Any] | None = None,
        db_lock=None,
    ) -> dict[str, Any]:
        service = self
        scene_index = scene["scene_index"]
        scene_id = service._scene_id(scene)
        scene_provenance_key = service._scene_provenance_key(workflow_id, scene)
        source_chapter_index = service._scene_source_chapter_index(scene)
        async with _optional_lock(db_lock):
            chapters_text = await service._load_scene_chapters(db, scene)
        input_fingerprint = service._scene_input_fingerprint(scene, chapters_text)
        if not chapters_text:
            return {
                "created": 0,
                "relations": 0,
                "deltas": 0,
                "created_entity_ids": [],
                "created_relation_ids": [],
                "created_delta_ids": [],
                "updated_context": existing_context,
                "updated_memory": accumulated_memory,
                "input_fingerprint": input_fingerprint,
            }

        memory_context = service._build_memory_context(accumulated_memory)
        snapshot_id: str | None = None
        format_diagnostics: list[dict[str, Any]] = []
        try:
            async with _optional_lock(db_lock):
                snapshot = await service._create_phase2_snapshot(
                    db,
                    nid,
                    scene,
                    source_chapter_index,
                    chapters_text,
                    existing_context,
                    memory_context,
                    accumulated_memory,
                    workflow_id=workflow_id,
                )
            snapshot_id = snapshot.id
            extraction = await asyncio.wait_for(
                service._call_llm_extraction(
                    chapters_text,
                    existing_context,
                    memory_context,
                    diagnostics=format_diagnostics,
                ),
                timeout=service._phase2_scene_llm_timeout_seconds(),
            )
        except Exception as exc:
            if snapshot_id is not None:
                from modules.context.facade import fail_context_snapshot

                async with _optional_lock(db_lock):
                    await fail_context_snapshot(
                        db,
                        novel_id=str(nid),
                        snapshot_id=snapshot_id,
                        error_kind=service._error_kind(exc),
                        error_message=redact_diagnostic(exc, limit=300),
                    )
            raise

        result_refs: list[dict[str, str]] = []
        context_snapshot_id = snapshot_id
        map_candidate_counts = {"created": 0, "reused": 0}
        try:
            async with _optional_lock(db_lock):
                created_count = await service._persist_entities(
                    db,
                    nid,
                    extraction.entities,
                    scene_index=scene_index,
                    source_chapter_index=source_chapter_index,
                    seen_entity_keys=seen_entity_keys,
                    workflow_id=workflow_id,
                    scene_id=scene_id,
                    scene_provenance_key=scene_provenance_key,
                    context_snapshot_id=context_snapshot_id,
                    result_refs=result_refs,
                    persistence_stats=persistence_stats,
                )
                relation_count = await service._persist_relations(
                    db,
                    nid,
                    extraction.relations,
                    scene_index=scene_index,
                    source_chapter_index=source_chapter_index,
                    workflow_id=workflow_id,
                    scene_id=scene_id,
                    context_snapshot_id=context_snapshot_id,
                    result_refs=result_refs,
                    persistence_stats=persistence_stats,
                )
                delta_count = await service._record_deltas(
                    db,
                    nid,
                    extraction.delta_events,
                    scene_index=scene_index,
                    source_chapter_index=source_chapter_index,
                    workflow_id=workflow_id,
                    scene_id=scene_id,
                    scene_provenance_key=scene_provenance_key,
                    context_snapshot_id=context_snapshot_id,
                    result_refs=result_refs,
                )
                proposals = getattr(extraction, "map_observation_proposals", None)
                if isinstance(proposals, list) and proposals:
                    map_candidate_counts = (
                        await service._record_map_observation_proposals(
                            db,
                            nid,
                            proposals,
                            scene_index=scene_index,
                            source_chapter_index=source_chapter_index,
                            workflow_id=workflow_id,
                            scene_id=scene_id,
                            scene_source_fingerprint=input_fingerprint,
                            authorization_snapshot=authorization_snapshot,
                            context_snapshot_id=context_snapshot_id,
                            result_refs=result_refs,
                        )
                    )
                if snapshot_id is not None:
                    from modules.context.facade import succeed_context_snapshot

                    await succeed_context_snapshot(
                        db,
                        novel_id=str(nid),
                        snapshot_id=snapshot_id,
                        result_refs=result_refs,
                    )
        except Exception as exc:
            if snapshot_id is not None:
                from modules.context.facade import fail_context_snapshot

                async with _optional_lock(db_lock):
                    await fail_context_snapshot(
                        db,
                        novel_id=str(nid),
                        snapshot_id=snapshot_id,
                        error_kind=service._error_kind(exc),
                        error_message=redact_diagnostic(exc, limit=300),
                    )
            raise

        new_names = [
            e.name for e in extraction.entities if e.suggested_action == "create_new"
        ]
        new_entities_text = "\n".join(
            f"- {n} ({e.entity_type})"
            for n, e in zip(new_names, extraction.entities)
            if e.suggested_action == "create_new"
        )
        updated_context = (
            existing_context + "\n" + new_entities_text
            if new_entities_text
            else existing_context
        )

        updated_memory = accumulated_memory + [
            {"scene_index": scene_index, "entities": len(extraction.entities)},
        ]

        # 每个 Scene 完成后更新 Scene 时间投影；失败会在 checkpoint 中显式呈现。
        try:
            from modules.memory.facade import ensure_scene_checkpoints

            async with _optional_lock(db_lock):
                await ensure_scene_checkpoints(
                    db,
                    str(nid),
                    scene_id,
                )
        except Exception as exc:
            logger.warning(
                "Memory snapshot after scene %d failed: %s",
                scene_index,
                redact_diagnostic(exc, limit=300),
            )

        return {
            "created": created_count,
            "relations": relation_count,
            "deltas": delta_count,
            "map_observation_candidates": map_candidate_counts,
            "created_entity_ids": service._result_ref_ids(result_refs, "core_entity"),
            "created_relation_ids": service._result_ref_ids(
                result_refs,
                "entity_relation",
            ),
            "created_delta_ids": service._result_ref_ids(result_refs, "delta_log"),
            "updated_context": updated_context,
            "updated_memory": updated_memory,
            "structured_format_diagnostics": format_diagnostics[:20],
            "input_fingerprint": input_fingerprint,
        }


class SingleSceneEntityExtractor(SingleSceneEntityExtractionMixin):
    """Compatibility adapter for the former helper class."""

    def __init__(self, service) -> None:
        self.service = service

    def __getattr__(self, name):
        return getattr(self.service, name)

    async def process(self, *args, **kwargs):
        return await SingleSceneEntityExtractionMixin._process_scene(
            self.service,
            *args,
            **kwargs,
        )
