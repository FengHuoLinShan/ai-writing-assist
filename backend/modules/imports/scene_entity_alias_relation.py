"""Phase 2b alias and relation extraction strategy."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.scene_entity_config import (
    PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS,
    phase2_alias_relation_concurrency,
    phase2_alias_relation_total_timeout_seconds,
    phase2_postprocess_timeout_seconds,
)

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
        started_at = time.monotonic()
        concurrency = phase2_alias_relation_concurrency()
        total_timeout_seconds = _effective_alias_relation_total_timeout_seconds(
            scene_count=len(scenes),
            concurrency=concurrency,
            configured_timeout_seconds=phase2_alias_relation_total_timeout_seconds(),
        )
        prepared: list[dict[str, Any]] = []
        entity_index: str | None = None

        for scene_position, scene in enumerate(scenes):
            scene_index = _scene_index_for_failure(
                scene,
                fallback=scene_position + 1,
            )
            scene_id = service._scene_id(scene)
            elapsed_s = time.monotonic() - started_at
            remaining_s = total_timeout_seconds - elapsed_s
            if remaining_s <= 0:
                error_kind = "timeout"
                error_message = (
                    "Phase 2b alias/relation extraction exceeded total timeout "
                    f"budget ({total_timeout_seconds}s)"
                )
                failed_scenes.extend(
                    _scene_indices_for_failure(
                        scenes[scene_position:],
                        start_position=scene_position,
                    )
                )
                break

            try:
                chapters_text = await service._load_scene_chapters(db, scene)
                if not chapters_text:
                    continue
                if entity_index is None:
                    entity_index = await _run_phase2b_preparation_step(
                        "entity_index",
                        service._build_alias_relation_entity_index(
                            db,
                            str(nid),
                        ),
                    )
                snapshot = await _run_phase2b_preparation_step(
                    "snapshot",
                    service._create_phase2b_snapshot(
                        db,
                        nid,
                        scene,
                        chapters_text,
                        entity_index,
                        workflow_id=workflow_id,
                    ),
                )
                prepared.append(
                    {
                        "position": scene_position,
                        "scene": scene,
                        "scene_index": scene_index,
                        "scene_id": scene_id,
                        "chapters_text": chapters_text,
                        "entity_index": entity_index,
                        "snapshot_id": getattr(snapshot, "id", None),
                    }
                )
            except Exception as exc:
                error_kind = service._error_kind(exc)
                error_message = str(exc)[:300]
                failed_scenes.append(scene_index)
                logger.warning(
                    "Alias/relation preparation failed for scene %s: %s",
                    scene_index,
                    exc,
                )

        llm_results = await _run_alias_relation_llm_calls(
            service,
            prepared,
            started_at=started_at,
            total_timeout_seconds=total_timeout_seconds,
            concurrency=concurrency,
        )
        for item, output, exc in llm_results:
            scene_index = int(item["scene_index"])
            snapshot_id = item.get("snapshot_id")
            result_refs: list[dict[str, str]] = []
            if exc is not None:
                error_kind = service._error_kind(exc)
                error_message = str(exc)[:300] or (
                    "Phase 2b alias/relation extraction exceeded total timeout "
                    f"budget ({total_timeout_seconds}s)"
                )
                failed_scenes.append(scene_index)
                logger.warning(
                    "Alias/relation extraction failed for scene %s: %s",
                    scene_index,
                    exc,
                )
                await _mark_phase2b_snapshot_failed(
                    db,
                    snapshot_id,
                    error_kind=error_kind,
                    error_message=error_message,
                )
                continue

            try:
                persisted = await service._persist_alias_relation_output(
                    db,
                    str(nid),
                    output,
                    scene_index=scene_index,
                    workflow_id=workflow_id,
                    scene_id=item["scene_id"],
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
                    "Alias/relation persistence failed for scene %s: %s",
                    scene_index,
                    exc,
                )
                await _mark_phase2b_snapshot_failed(
                    db,
                    snapshot_id,
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
            "alias_relation_elapsed_s": round(time.monotonic() - started_at, 2),
            "alias_relation_total_timeout_s": total_timeout_seconds,
            "alias_relation_concurrency": concurrency,
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


async def _run_phase2b_preparation_step(label: str, operation):
    timeout_seconds = phase2_postprocess_timeout_seconds()
    try:
        return await asyncio.wait_for(operation, timeout=timeout_seconds)
    except TimeoutError as exc:
        raise TimeoutError(
            f"Phase 2b {label} exceeded preparation timeout ({timeout_seconds}s)"
        ) from exc


def _scene_index_for_failure(scene: dict[str, Any], *, fallback: int) -> int:
    raw_scene_index = (
        scene.get("scene_index")
        if isinstance(scene, dict)
        else getattr(scene, "scene_index", 0)
    )
    try:
        scene_index = int(raw_scene_index or 0)
    except (TypeError, ValueError):
        scene_index = 0
    return scene_index if scene_index > 0 else fallback


def _effective_alias_relation_total_timeout_seconds(
    *,
    scene_count: int,
    concurrency: int,
    configured_timeout_seconds: float,
) -> float:
    if (
        os.getenv("PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS")
        or configured_timeout_seconds < 240
    ):
        return configured_timeout_seconds
    waves = max(1, math.ceil(max(scene_count, 1) / max(concurrency, 1)))
    dynamic_timeout = (
        waves * PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS
        + int(phase2_postprocess_timeout_seconds() * 2)
    )
    return max(configured_timeout_seconds, dynamic_timeout)


async def _run_alias_relation_llm_calls(
    service: Any,
    prepared: list[dict[str, Any]],
    *,
    started_at: float,
    total_timeout_seconds: int,
    concurrency: int,
) -> list[tuple[dict[str, Any], Any | None, Exception | None]]:
    if not prepared:
        return []

    remaining_s = total_timeout_seconds - (time.monotonic() - started_at)
    timeout_message = (
        "Phase 2b alias/relation extraction exceeded total timeout "
        f"budget ({total_timeout_seconds}s)"
    )
    if remaining_s <= 0:
        return [(item, None, TimeoutError(timeout_message)) for item in prepared]

    semaphore = asyncio.Semaphore(max(1, concurrency))
    task_items: dict[asyncio.Task, dict[str, Any]] = {}

    async def call(item: dict[str, Any]):
        async with semaphore:
            try:
                output = await asyncio.wait_for(
                    service._call_alias_relation_extraction(
                        item["chapters_text"],
                        item["entity_index"],
                    ),
                    timeout=PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                return item, None, exc
            return item, output, None

    for item in prepared:
        task = asyncio.create_task(call(item))
        task_items[task] = item

    done, pending = await asyncio.wait(task_items, timeout=remaining_s)
    results: list[tuple[dict[str, Any], Any | None, Exception | None]] = []
    for task in done:
        results.append(task.result())

    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
        timeout_error = TimeoutError(timeout_message)
        results.extend((task_items[task], None, timeout_error) for task in pending)

    return sorted(results, key=lambda item: int(item[0].get("position", 0)))


async def _mark_phase2b_snapshot_failed(
    db: AsyncSession,
    snapshot_id: str | None,
    *,
    error_kind: str,
    error_message: str,
) -> None:
    if snapshot_id is None:
        return
    from modules.context.facade import mark_context_snapshot_failed

    await mark_context_snapshot_failed(
        db,
        snapshot_id=snapshot_id,
        error_kind=error_kind,
        error_message=error_message,
    )


def _scene_indices_for_failure(
    scenes: list[dict[str, Any]],
    *,
    start_position: int,
) -> list[int]:
    indices: list[int] = []
    for offset, scene in enumerate(scenes):
        indices.append(
            _scene_index_for_failure(
                scene,
                fallback=start_position + offset + 1,
            )
        )
    return indices
