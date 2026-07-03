"""Phase 2b alias and relation extraction strategy."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.errors import LLMInvalidResponseError
from modules.imports.scene_entity_config import (
    phase2_alias_relation_concurrency,
    phase2_alias_relation_entity_index_char_limit,
    phase2_alias_relation_entity_index_fallback_limit,
    phase2_alias_relation_llm_timeout_seconds,
    phase2_alias_relation_scene_char_limit,
    phase2_alias_relation_total_timeout_seconds,
    phase2_postprocess_timeout_seconds,
)
from modules.imports.scene_entity_runtime import SceneEntityExtractionRuntime

logger = logging.getLogger(__name__)


class AliasRelationExtractor:
    """Runs alias/relation extraction against working world objects."""

    def __init__(self, service: SceneEntityExtractionRuntime) -> None:
        self.service = service

    async def run(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        workflow_id: str | None = None,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None = None,
        existing_checkpoints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        service = self.service
        total_aliases = 0
        total_relations = 0
        completed_scenes = 0
        skipped_scenes = 0
        rerun_scenes = 0
        failed_scenes: list[int] = []
        fallback_scenes: list[int] = []
        scene_checkpoints: list[dict[str, Any]] = []
        error_kind: str | None = None
        error_message: str | None = None
        started_at = time.monotonic()
        concurrency = phase2_alias_relation_concurrency()
        total_timeout_seconds = _effective_alias_relation_total_timeout_seconds(
            scene_count=len(scenes),
            concurrency=concurrency,
            configured_timeout_seconds=phase2_alias_relation_total_timeout_seconds(),
        )
        llm_timeout_seconds = phase2_alias_relation_llm_timeout_seconds()
        prepared: list[dict[str, Any]] = []
        entity_index: str | None = None
        checkpoint_by_scene = _phase2b_checkpoint_by_scene(existing_checkpoints)
        progress_completed = 0
        total_scenes = len(scenes)

        if on_scene_progress is not None:
            await on_scene_progress(0, total_scenes)

        for scene_position, scene in enumerate(scenes):
            scene_index = _scene_index_for_failure(
                scene,
                fallback=scene_position + 1,
            )
            scene_id = service._scene_id(scene)
            existing_checkpoint = checkpoint_by_scene.get(scene_id)
            existing_status = (
                existing_checkpoint.get("status") if existing_checkpoint else None
            )
            retry_count = _checkpoint_retry_count(existing_checkpoint)
            if existing_status in {"done", "skipped"}:
                skipped_scenes += 1
                progress_completed += 1
                scene_checkpoints.append(
                    _build_phase2b_checkpoint(
                        scene,
                        scene_id=scene_id,
                        scene_index=scene_index,
                        status="skipped",
                        retry_count=retry_count,
                        aliases=existing_checkpoint.get("aliases", 0),
                        relations=existing_checkpoint.get("relations", 0),
                    )
                )
                if on_scene_progress is not None:
                    await on_scene_progress(progress_completed, total_scenes)
                continue
            if existing_status == "failed":
                rerun_scenes += 1
                retry_count += 1

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
                for failed_scene in scenes[scene_position:]:
                    failed_index = _scene_index_for_failure(
                        failed_scene,
                        fallback=progress_completed + 1,
                    )
                    scene_checkpoints.append(
                        _build_phase2b_checkpoint(
                            failed_scene,
                            scene_id=service._scene_id(failed_scene),
                            scene_index=failed_index,
                            status="failed",
                            retry_count=retry_count,
                            error=error_message,
                            error_kind=error_kind,
                        )
                    )
                break

            try:
                chapters_text = await service._load_scene_chapters(db, scene)
                if not chapters_text:
                    progress_completed += 1
                    scene_checkpoints.append(
                        _build_phase2b_checkpoint(
                            scene,
                            scene_id=scene_id,
                            scene_index=scene_index,
                            status="skipped",
                            retry_count=retry_count,
                            error="empty_scene_text",
                            error_kind="empty_scene_text",
                        )
                    )
                    if on_scene_progress is not None:
                        await on_scene_progress(progress_completed, total_scenes)
                    continue
                chapters_text = _trim_phase2b_scene_text(chapters_text)
                if entity_index is None:
                    entity_index = await _run_phase2b_preparation_step(
                        "entity_index",
                        service._build_alias_relation_entity_index(
                            db,
                            str(nid),
                        ),
                    )
                compact_entity_index = _compact_entity_index_for_scene(
                    entity_index,
                    chapters_text,
                )
                snapshot = await _run_phase2b_preparation_step(
                    "snapshot",
                    service._create_phase2b_snapshot(
                        db,
                        nid,
                        scene,
                        chapters_text,
                        compact_entity_index,
                        workflow_id=workflow_id,
                    ),
                )
                prepared.append(
                    {
                        "position": scene_position,
                        "scene": scene,
                        "scene_index": scene_index,
                        "scene_id": scene_id,
                        "retry_count": retry_count,
                        "chapters_text": chapters_text,
                        "entity_index": compact_entity_index,
                        "snapshot_id": getattr(snapshot, "id", None),
                    }
                )
            except Exception as exc:
                error_kind = service._error_kind(exc)
                error_message = str(exc)[:300]
                failed_scenes.append(scene_index)
                progress_completed += 1
                scene_checkpoints.append(
                    _build_phase2b_checkpoint(
                        scene,
                        scene_id=scene_id,
                        scene_index=scene_index,
                        status="failed",
                        retry_count=retry_count,
                        error=error_message,
                        error_kind=error_kind,
                    )
                )
                logger.warning(
                    "Alias/relation preparation failed for scene %s: %s",
                    scene_index,
                    exc,
                )
                if on_scene_progress is not None:
                    await on_scene_progress(progress_completed, total_scenes)

        async def _on_llm_result(_item: dict[str, Any]) -> None:
            nonlocal progress_completed
            progress_completed += 1
            if on_scene_progress is not None:
                await on_scene_progress(progress_completed, total_scenes)

        llm_results = await _run_alias_relation_llm_calls(
            service,
            prepared,
            started_at=started_at,
            total_timeout_seconds=total_timeout_seconds,
            concurrency=concurrency,
            llm_timeout_seconds=llm_timeout_seconds,
            on_result=_on_llm_result if on_scene_progress is not None else None,
        )
        for item, output, exc in llm_results:
            scene_index = int(item["scene_index"])
            snapshot_id = item.get("snapshot_id")
            result_refs: list[dict[str, str]] = []
            if exc is not None:
                current_error_kind = service._error_kind(exc)
                current_error_message = str(exc)[:300] or (
                    "Phase 2b alias/relation extraction exceeded total timeout "
                    f"budget ({total_timeout_seconds}s)"
                )
                if isinstance(exc, LLMInvalidResponseError):
                    fallback_scenes.append(scene_index)
                    completed_scenes += 1
                    scene_checkpoints.append(
                        _build_phase2b_checkpoint(
                            item["scene"],
                            scene_id=item["scene_id"],
                            scene_index=scene_index,
                            status="done",
                            retry_count=int(item.get("retry_count", 0) or 0),
                            aliases=0,
                            relations=0,
                            fallback=True,
                            error=current_error_message,
                            error_kind=current_error_kind,
                        )
                    )
                    logger.warning(
                        "Alias/relation extraction fell back to empty result "
                        "for scene %s: %s",
                        scene_index,
                        exc,
                    )
                    await _mark_phase2b_snapshot_failed(
                        db,
                        snapshot_id,
                        error_kind=current_error_kind,
                        error_message=current_error_message,
                    )
                    continue
                error_kind = current_error_kind
                error_message = current_error_message
                failed_scenes.append(scene_index)
                scene_checkpoints.append(
                    _build_phase2b_checkpoint(
                        item["scene"],
                        scene_id=item["scene_id"],
                        scene_index=scene_index,
                        status="failed",
                        retry_count=int(item.get("retry_count", 0) or 0),
                        error=error_message,
                        error_kind=error_kind,
                    )
                )
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
                scene_checkpoints.append(
                    _build_phase2b_checkpoint(
                        item["scene"],
                        scene_id=item["scene_id"],
                        scene_index=scene_index,
                        status="done",
                        retry_count=int(item.get("retry_count", 0) or 0),
                        aliases=persisted["aliases"],
                        relations=persisted["relations"],
                    )
                )
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
                scene_checkpoints.append(
                    _build_phase2b_checkpoint(
                        item["scene"],
                        scene_id=item["scene_id"],
                        scene_index=scene_index,
                        status="failed",
                        retry_count=int(item.get("retry_count", 0) or 0),
                        error=error_message,
                        error_kind=error_kind,
                    )
                )
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
            "alias_relation_skipped_scenes": skipped_scenes,
            "alias_relation_rerun_scenes": rerun_scenes,
            "alias_relation_fallback_scenes": fallback_scenes,
            "degraded": bool(failed_scenes),
            "error_kind": error_kind,
            "error_message": error_message,
            "alias_relation_elapsed_s": round(time.monotonic() - started_at, 2),
            "alias_relation_total_timeout_s": total_timeout_seconds,
            "alias_relation_concurrency": concurrency,
            "alias_relation_llm_timeout_s": llm_timeout_seconds,
            "alias_relation_checkpoints": {
                "phase2b": {
                    "scenes": sorted(
                        scene_checkpoints,
                        key=lambda checkpoint: int(
                            checkpoint.get("position")
                            or checkpoint.get("scene_index")
                            or 0
                        ),
                    )
                }
            },
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
            lines.append("- " f"{entity.get('name')} ({entity.get('entity_type')})")
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


def _trim_phase2b_scene_text(text: str) -> str:
    limit = phase2_alias_relation_scene_char_limit()
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    head_limit = max(1, int(limit * 0.7))
    tail_limit = max(1, limit - head_limit)
    return (
        value[:head_limit].rstrip()
        + "\n\n[...Scene 中段已压缩，仅保留首尾用于别名/关系判断...]\n\n"
        + value[-tail_limit:].lstrip()
    )


def _compact_entity_index_for_scene(entity_index: str, scene_text: str) -> str:
    lines = [
        line.strip()
        for line in str(entity_index or "").splitlines()
        if line.strip().startswith("- ")
    ]
    if not lines:
        return entity_index

    scene_text = str(scene_text or "")
    matched: list[str] = []
    fallback: list[str] = []
    for line in lines:
        name = _entity_index_line_name(line)
        terms = _entity_name_terms(name)
        if any(term and term in scene_text for term in terms):
            matched.append(line)
        elif len(fallback) < phase2_alias_relation_entity_index_fallback_limit():
            fallback.append(line)

    selected = matched + [line for line in fallback if line not in matched]
    if not selected:
        selected = lines[: phase2_alias_relation_entity_index_fallback_limit()]
    header = [
        "## 可用对象索引",
        f"- 全量对象 {len(lines)} 个；本 Scene 相关优先 {len(matched)} 个。",
        "- 若对象不在下方索引中，必须跳过，不要猜测或新建。",
    ]
    compact_lines = header + selected
    limit = phase2_alias_relation_entity_index_char_limit()
    compact = "\n".join(compact_lines)
    if len(compact) <= limit:
        return compact

    kept: list[str] = header[:]
    for line in selected:
        candidate = "\n".join(kept + [line])
        if len(candidate) > limit:
            break
        kept.append(line)
    kept.append("- [...对象索引已按预算截断...]")
    return "\n".join(kept)


def _entity_index_line_name(line: str) -> str:
    value = line[2:].strip() if line.startswith("- ") else line.strip()
    if " (" in value:
        return value.split(" (", 1)[0].strip()
    return value.strip()


def _entity_name_terms(name: str) -> list[str]:
    value = str(name or "").strip()
    if not value:
        return []
    terms = [value]
    for separator in ("·", "・", " ", "/", "／", "-", "_"):
        if separator in value:
            terms.extend(part.strip() for part in value.split(separator))
    return [term for term in dict.fromkeys(terms) if len(term) >= 2]


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
        waves * phase2_alias_relation_llm_timeout_seconds()
        + int(phase2_postprocess_timeout_seconds() * 2)
    )
    return max(configured_timeout_seconds, dynamic_timeout)


async def _run_alias_relation_llm_calls(
    service: SceneEntityExtractionRuntime,
    prepared: list[dict[str, Any]],
    *,
    started_at: float,
    total_timeout_seconds: int,
    concurrency: int,
    llm_timeout_seconds: int,
    on_result: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
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
                        client_timeout=llm_timeout_seconds,
                    ),
                    timeout=llm_timeout_seconds,
                )
            except Exception as exc:
                return item, None, exc
            return item, output, None

    for item in prepared:
        task = asyncio.create_task(call(item))
        task_items[task] = item

    results: list[tuple[dict[str, Any], Any | None, Exception | None]] = []
    pending = set(task_items)
    while pending:
        remaining_s = total_timeout_seconds - (time.monotonic() - started_at)
        if remaining_s <= 0:
            break
        done, pending = await asyncio.wait(
            pending,
            timeout=remaining_s,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            break
        for task in done:
            result = task.result()
            results.append(result)
            if on_result is not None:
                await on_result(result[0])

    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
        timeout_error = TimeoutError(timeout_message)
        for task in pending:
            item = task_items[task]
            results.append((item, None, timeout_error))
            if on_result is not None:
                await on_result(item)

    return sorted(results, key=lambda item: int(item[0].get("position", 0)))


def _phase2b_checkpoint_by_scene(
    existing_checkpoints: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not existing_checkpoints:
        return {}
    scenes = existing_checkpoints.get("scenes")
    if scenes is None:
        phase2b = existing_checkpoints.get("phase2b")
        if isinstance(phase2b, dict):
            scenes = phase2b.get("scenes")
    if isinstance(scenes, list):
        return {
            str(item["scene_id"]): item
            for item in scenes
            if isinstance(item, dict) and item.get("scene_id")
        }
    return {
        str(scene_id): checkpoint
        for scene_id, checkpoint in existing_checkpoints.items()
        if isinstance(checkpoint, dict)
    }


def _checkpoint_retry_count(checkpoint: dict[str, Any] | None) -> int:
    if not checkpoint:
        return 0
    try:
        return max(0, int(checkpoint.get("retry_count") or 0))
    except (TypeError, ValueError):
        return 0


def _build_phase2b_checkpoint(
    scene: dict[str, Any],
    *,
    scene_id: str,
    scene_index: int,
    status: str,
    retry_count: int,
    aliases: int = 0,
    relations: int = 0,
    fallback: bool = False,
    error: str | None = None,
    error_kind: str | None = None,
) -> dict[str, Any]:
    checkpoint = {
        "scene_id": scene_id,
        "scene_index": scene_index,
        "position": int(scene.get("scene_index") or scene_index or 0),
        "status": status,
        "aliases": aliases,
        "relations": relations,
        "retry_count": retry_count,
        "fallback": fallback,
        "source": "deep_import",
        "auto_ingested": True,
    }
    if error is not None:
        checkpoint["error"] = error
    if error_kind is not None:
        checkpoint["error_kind"] = error_kind
    return checkpoint


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
