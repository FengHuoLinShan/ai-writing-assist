"""Prove whole current chapters from successful live Evolution Scene receipts."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import and_, select

from modules.evolution.models import (
    EvolutionFrozenAttempt,
    EvolutionReceiptRecord,
    EvolutionRun,
)
from modules.evolution.pipeline import SceneSourceBinding
from modules.project.facade import require_active_project
from modules.writing.facade import list_manuscript_sources


async def read_completed_chapter_indices(
    db, novel_id: str, *, exclude_chapter_indices: list[int] | None = None
) -> list[int]:
    """Return chapters whose current canonical text was wholly read successfully.

    A prepared plan alone proves coverage, never success. Every Scene touching a
    chapter must have an applied successful receipt for that exact frozen
    source. Revisions, failed Scenes, shadow runs, and partial reads fail closed.
    """
    await require_active_project(db, novel_id)
    nid = UUID(novel_id)
    excluded = set(exclude_chapter_indices or [])
    runs = (
        await db.scalars(
            select(EvolutionRun).where(
                EvolutionRun.novel_id == nid,
                EvolutionRun.execution_mode == "live",
                EvolutionRun.status.in_(("active", "drained", "stopped")),
            )
        )
    ).all()
    if not runs:
        return []

    plans = []
    wanted_scene_indices: set[int] = set()
    for run in runs:
        steps = (run.reading_plan_json or {}).get("steps") or []
        if not isinstance(steps, list) or not steps:
            continue
        planned: dict[int, list[tuple[int, int | None, str, str, int]]] = defaultdict(
            list
        )
        scene_info: dict[int, tuple[str, dict]] = {}
        seen_scene_indices: set[int] = set()
        valid_plan = True
        for step in steps:
            try:
                scene_index = int(step["scene_index"])
                scene_id = str(step["scene_id"])
                binding = SceneSourceBinding.model_validate(step["source_binding"])
            except (KeyError, TypeError, ValueError):
                valid_plan = False
                break
            if scene_index in seen_scene_indices:
                valid_plan = False
                break
            seen_scene_indices.add(scene_index)
            scene_info[scene_index] = (scene_id, step["source_binding"])
            for part in binding.ranges():
                if part.chapter_index in excluded:
                    continue
                planned[part.chapter_index].append(
                    (
                        part.start_offset,
                        part.end_offset,
                        part.draft_id,
                        part.content_hash,
                        scene_index,
                    )
                )
        if not valid_plan or not planned:
            continue
        plans.append((run, planned, scene_info))
        wanted_scene_indices.update(row[4] for spans in planned.values() for row in spans)
    if not plans:
        return []
    rows = (
        await db.execute(
            select(EvolutionReceiptRecord, EvolutionFrozenAttempt)
            .join(
                EvolutionFrozenAttempt,
                and_(
                    EvolutionFrozenAttempt.novel_id == EvolutionReceiptRecord.novel_id,
                    EvolutionFrozenAttempt.run_key == EvolutionReceiptRecord.run_key,
                    EvolutionFrozenAttempt.attempt_key
                    == EvolutionReceiptRecord.attempt_key,
                ),
            )
            .where(
                EvolutionReceiptRecord.novel_id == nid,
                EvolutionReceiptRecord.run_key.in_([run.run_key for run, _, _ in plans]),
                EvolutionReceiptRecord.committed_scene_index.in_(wanted_scene_indices),
                EvolutionReceiptRecord.execution_status == "succeeded",
                EvolutionFrozenAttempt.status == "applied",
            )
        )
    ).all()
    receipts = defaultdict(list)
    for receipt, frozen in rows:
        receipts[(receipt.run_key, int(receipt.committed_scene_index))].append(
            frozen.payload_json or {}
        )
    ready: list[tuple[int, list[tuple[int, int | None, str, str, int]]]] = []
    current_candidates: set[int] = set()
    for run, planned, scene_info in plans:
        for chapter_index, spans in planned.items():
            if all(
                run.committed_scene_index >= scene_index
                and any(
                    payload.get("scene_index") == scene_index
                    and str(payload.get("scene_id")) == scene_info[scene_index][0]
                    and payload.get("source_binding") == scene_info[scene_index][1]
                    for payload in receipts.get((run.run_key, scene_index), ())
                )
                for _, _, _, _, scene_index in spans
            ):
                ready.append((chapter_index, spans))
                current_candidates.add(chapter_index)
    if not ready:
        return []
    current = {
        item.chapter_index: item
        for item in await list_manuscript_sources(
            db, novel_id, sorted(current_candidates), content_mode="canonical"
        )
    }
    chapters: set[int] = set()
    for chapter_index, spans in ready:
        draft = current.get(chapter_index)
        content = draft.content if draft is not None else None
        if not content or not content.strip():
            continue
        if any(
            draft.id != draft_id or draft.content_hash != content_hash
            for _, _, draft_id, content_hash, _ in spans
        ):
            continue
        cursor = 0
        for start, raw_end, _, _, _ in sorted(spans):
            end = len(content) if raw_end is None else raw_end
            if start < cursor or end > len(content) or content[cursor:start].strip():
                break
            cursor = end
        else:
            if not content[cursor:].strip():
                chapters.add(chapter_index)
    return sorted(chapters)
