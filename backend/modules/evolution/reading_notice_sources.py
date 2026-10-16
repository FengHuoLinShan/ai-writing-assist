"""Read-only notices for unread canonical chapters and unresolved reading work."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from infrastructure.stable_hash import stable_hash
from infrastructure.tasks.facade import list_task_lifecycle_contracts
from modules.evolution.completed_read_chapters import read_completed_chapter_indices
from modules.evolution.models import EvolutionRun
from modules.evolution.state_review import has_unreconciled_scene_calls
from modules.evolution.store import PostgresAttemptStore
from modules.project.facade import require_active_project
from modules.story.contracts import scene_chapter_indices
from modules.story.facade import get_scene_contract, get_scenes_by_novel
from modules.writing.facade import get_manuscript_source_manifest

SOURCE_ID = "evolution.reading"
ATTENTION_STATUSES = {
    "cancelled",
    "failed",
    "interrupted",
    "needs_budget",
    "needs_reconciliation",
    "source_changed",
    "stopped",
}


def _chapter_index(value: object) -> int | None:
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if index > 0 else None


def _source_key(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "chapter_index": int(source["chapter_index"]),
        "draft_id": str(source.get("draft_id") or ""),
        "source_hash": str(source.get("source_hash") or ""),
    }


def _action(*, chapter_index: int | None, scene_id: str | None) -> dict[str, Any]:
    return {
        "kind": "navigate",
        "page": "writing",
        "open_evolution_reading": True,
        **({"chapter_index": chapter_index} if chapter_index else {}),
        **({"scene_id": scene_id} if scene_id else {}),
        "label": "打开演化阅读",
    }


def _chapter_cutoff(scope: dict[str, object], scene: object | None) -> int | None:
    requested = _chapter_index(scope.get("chapter_index"))
    mapped = sorted(scene_chapter_indices(scene.__dict__)) if scene is not None else []
    scene_cutoff = max(mapped) if mapped else None
    if requested is not None and scene_cutoff is not None:
        return min(requested, scene_cutoff)
    return requested or scene_cutoff


def _scope_fingerprint(
    *,
    novel_id: str,
    chapter_cutoff: int | None,
    scene_id: str | None,
    scene_index: int | None,
    sources: list[dict[str, Any]],
) -> str:
    return stable_hash(
        {
            "novel_id": novel_id,
            "chapter_cutoff": chapter_cutoff,
            "scene_id": scene_id,
            "scene_index": scene_index,
            "sources": [_source_key(source) for source in sources],
        }
    )


def _step_source_chapters(step: dict[str, Any]) -> set[int]:
    binding = step.get("source_binding")
    if not isinstance(binding, dict):
        return set()
    indexes: set[int] = set()
    raw = [binding, *(binding.get("additional_sources") or [])]
    for item in raw:
        if isinstance(item, dict):
            index = _chapter_index(item.get("chapter_index"))
            if index is not None:
                indexes.add(index)
    return indexes


def _step_is_before_cutoff(
    step: dict[str, Any], *, chapter_cutoff: int | None, scene_index: int | None
) -> bool:
    try:
        step_index = int(step["scene_index"])
    except (KeyError, TypeError, ValueError):
        return False
    if scene_index is not None:
        return step_index <= scene_index
    if chapter_cutoff is None:
        return True
    chapters = _step_source_chapters(step)
    return bool(chapters) and max(chapters) <= chapter_cutoff


def _preparation_is_before_cutoff(
    preparation: dict[str, Any], *, chapter_cutoff: int | None, scene_index: int | None
) -> bool:
    if scene_index is not None:
        try:
            return scene_index >= int(preparation.get("start_scene_index", 0))
        except (TypeError, ValueError):
            return False
    if chapter_cutoff is None:
        return True
    sources = preparation.get("sources") or []
    chapters = {
        index
        for item in sources
        if isinstance(item, dict)
        if (index := _chapter_index(item.get("chapter_index"))) is not None
    }
    return bool(chapters) and max(chapters) <= chapter_cutoff


def _structure_review_summary(structure: dict[str, Any]) -> dict[str, Any]:
    unresolved = []
    for batch in structure.get("batches", []):
        sources = {
            ref.get("scene_id"): {
                "scene_id": ref.get("scene_id"),
                "run_key": ref.get("run_key"),
                "attempt_id": ref.get("attempt_id"),
            }
            for ref in batch.get("sources", [])
        }
        for item in batch.get("unresolved_reveals", []):
            unresolved.append(
                {
                    "batch_key": batch.get("batch_key"),
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "needs_review": True,
                    "review_reason": item.get("review_reason"),
                    "supporting_scene_ids": item.get("supporting_scene_ids", []),
                    "evidence_gate": item.get("evidence_gate", {}),
                    "source_refs": [
                        sources[scene_id]
                        for scene_id in item.get("supporting_scene_ids", [])
                        if scene_id in sources
                    ],
                }
            )
    return {"unresolved_reveal_count": len(unresolved), "unresolved_reveals": unresolved}


def _has_unsettled_calls(calls: object) -> bool:
    return isinstance(calls, dict) and any(
        isinstance(call, dict) and call.get("stage") in {"sampling", "failed"}
        for call in calls.values()
    )


def _reading_attention_notice(
    *,
    run: dict[str, Any],
    run_row: EvolutionRun,
    scene_rows: list[dict[str, Any]],
    scope_hash: str,
    chapter_cutoff: int | None,
    scene_index: int | None,
    scene_id: str | None,
) -> dict[str, Any] | None:
    status = str(run.get("status") or "")
    plan = run_row.reading_plan_json or {}
    steps = plan.get("steps") or []
    completed = max(0, int(run.get("completed_scenes") or 0))
    preparation = plan.get("preparation") or {}

    if status == "needs_scene_review":
        if not _preparation_is_before_cutoff(
            preparation, chapter_cutoff=chapter_cutoff, scene_index=scene_index
        ):
            return None
        target = {"run_key": run_row.run_key, "status": status}
        basis = stable_hash(
            {"scope": scope_hash, "run": target, "preparation": preparation}
        )
        return {
            "notice_key": f"{SOURCE_ID}:review-boundary:{run_row.run_key}",
            "source_id": SOURCE_ID,
            "category": "reading_review",
            "severity": "medium",
            "target": {"chapter_index": chapter_cutoff, "scene_id": scene_id},
            "summary": "演化阅读的场景边界需要作者确认，确认后才能继续。",
            "evidence": [{"note": "读取状态来自当前阅读计划的边界复核记录。"}],
            "basis_fingerprint": basis,
            "stale": False,
            "actions": [
                {
                    "kind": "navigate",
                    "page": "outline",
                    "scene_id": scene_id,
                    "chapter_index": chapter_cutoff,
                    "label": "去大纲确认边界",
                }
            ],
            "disposition_ref": None,
        }

    if status in ATTENTION_STATUSES:
        failure_step = steps[completed] if completed < len(steps) else None
        if (
            failure_step is None
            and completed >= len(steps)
            and status in {"cancelled", "interrupted", "stopped"}
        ):
            return None
        if failure_step is None and steps:
            failure_step = steps[-1]
        if failure_step is not None and not _step_is_before_cutoff(
            failure_step,
            chapter_cutoff=chapter_cutoff,
            scene_index=scene_index,
        ):
            return None
        if failure_step is None and not _preparation_is_before_cutoff(
            preparation, chapter_cutoff=chapter_cutoff, scene_index=scene_index
        ):
            return None
        run_state = {
            "run_key": run_row.run_key,
            "status": status,
            "completed_scenes": completed,
            "total_scenes": int(run.get("total_scenes") or 0),
            "task_id": run.get("task_id"),
            "committed_scene_index": run_row.committed_scene_index,
        }
        summary = {
            "failed": "上次演化阅读失败；已完成的部分仍保留，请打开阅读面板核对。",
            "needs_reconciliation": "上次阅读的请求结果尚待核对；确认前不会自动重发。",
            "needs_budget": "上次阅读额度已用完；已完成的部分仍保留。",
            "source_changed": "阅读所依据的正文已变化，旧结果仍保留供核对。",
            "cancelled": "上次阅读未完成；已完成的部分仍保留。",
            "interrupted": "上次阅读中断；已完成的部分仍保留。",
            "stopped": "上次阅读已暂停；已完成的部分仍保留。",
        }.get(status, "上次阅读未完成；已完成的部分仍保留。")
        basis = stable_hash({"scope": scope_hash, "run": run_state})
        return {
            "notice_key": f"{SOURCE_ID}:run:{run_row.run_key}",
            "source_id": SOURCE_ID,
            "category": "reading_run",
            "severity": "medium",
            "target": {"chapter_index": chapter_cutoff, "scene_id": scene_id},
            "summary": summary,
            "evidence": [
                {
                    "chapter_index": run.get("end_chapter"),
                    "note": (
                        f"阅读当前状态：{status}；"
                        f"已完成 {completed} / {run_state['total_scenes']} 场。"
                    ),
                }
            ],
            "basis_fingerprint": basis,
            "stale": False,
            "actions": [_action(chapter_index=None, scene_id=scene_id)],
            "disposition_ref": None,
        }

    unresolved = (run.get("structure_review") or {}).get("unresolved_reveals") or []
    if not unresolved:
        return None
    scenes = {str(item.get("id")): item for item in scene_rows}
    visible: list[dict[str, Any]] = []
    for item in unresolved:
        source_ids = [
            str(ref.get("scene_id"))
            for ref in item.get("source_refs", [])
            if isinstance(ref, dict) and ref.get("scene_id")
        ]
        source_scenes = [scenes.get(source_id) for source_id in source_ids]
        complete_sources = bool(source_ids) and all(
            source_scene is not None for source_scene in source_scenes
        )
        if scene_index is not None:
            before_cutoff = complete_sources and all(
                int(source_scene["scene_index"]) <= scene_index
                for source_scene in source_scenes
                if source_scene is not None
            )
        elif chapter_cutoff is not None:
            source_chapters = [
                scene_chapter_indices(source_scene)
                for source_scene in source_scenes
                if source_scene is not None
            ]
            before_cutoff = complete_sources and all(
                indexes and max(indexes) <= chapter_cutoff for indexes in source_chapters
            )
        else:
            before_cutoff = True
        if before_cutoff:
            visible.append(item)
    if not visible:
        return None
    review_state = {
        "run_key": run_row.run_key,
        "status": status,
        "scene_ids": sorted(
            {
                str(ref.get("scene_id"))
                for item in visible
                for ref in item.get("source_refs", [])
                if isinstance(ref, dict) and ref.get("scene_id")
            }
        ),
        "items": [
            {
                "title": item.get("title"),
                "review_reason": item.get("review_reason"),
                "supporting_scene_ids": item.get("supporting_scene_ids"),
            }
            for item in visible
        ],
    }
    return {
        "notice_key": f"{SOURCE_ID}:review-structure:{run_row.run_key}",
        "source_id": SOURCE_ID,
        "category": "reading_review",
        "severity": "low",
        "target": {"chapter_index": chapter_cutoff, "scene_id": scene_id},
        "summary": f"演化阅读留下 {len(visible)} 条剧情结构候选待独立复核。",
        "evidence": [{"note": "候选仍是待复核建议，不代表已确认的剧情事实。"}],
        "basis_fingerprint": stable_hash({"scope": scope_hash, "review": review_state}),
        "stale": False,
        "actions": [_action(chapter_index=None, scene_id=scene_id)],
        "disposition_ref": None,
    }


async def _run_attention(
    db,
    novel_id: str,
    latest: EvolutionRun,
    *,
    scope_hash: str,
    chapter_cutoff: int | None,
    scene_index: int | None,
    scene_id: str | None,
) -> dict[str, Any] | None:
    plan = latest.reading_plan_json or {}
    steps = plan.get("steps") or []
    preparation = plan.get("preparation") or {}
    structure = plan.get("structure") or {}
    completed = sum(
        int(step.get("scene_index", -1)) <= latest.committed_scene_index
        for step in steps
        if isinstance(step, dict)
    )
    task_id = plan.get("task_id")
    lifecycle = (
        (
            await list_task_lifecycle_contracts(
                db,
                task_ids=[str(task_id)],
                novel_id=str(novel_id),
                max_heartbeat_gap=120,
            )
        ).get(str(task_id))
        if task_id
        else None
    )
    if latest.status == "source_stale":
        status = "source_changed"
    elif latest.status != "active":
        status = (
            "completed"
            if completed == len(steps)
            and preparation.get("stage") in {None, "complete"}
            and (plan.get("structure_version", 0) == 0 or structure.get("complete"))
            else "stopped"
        )
    else:
        pending = await PostgresAttemptStore(db, str(novel_id)).load_pending_frozen(
            latest.run_key, latest.committed_scene_index + 1
        )
        reconcile = bool(
            (
                pending
                and (
                    pending.payload.get("stage") in {"sampling", "failed"}
                    or has_unreconciled_scene_calls(pending.payload, frozen=pending)
                )
            )
            or _has_unsettled_calls(preparation.get("calls"))
            or _has_unsettled_calls((structure.get("current") or {}).get("calls"))
        ) and (not lifecycle or lifecycle.status not in {"pending", "running"})
        if reconcile:
            status = "needs_reconciliation"
        elif preparation.get("stage") == "needs_scene_review":
            status = "needs_scene_review"
        elif plan.get("pause_reason") == "budget":
            status = (
                lifecycle.status
                if lifecycle and lifecycle.status in {"pending", "running"}
                else "needs_budget"
            )
        elif (
            completed == len(steps)
            and preparation.get("stage") in {None, "complete"}
            and (plan.get("structure_version", 0) == 0 or structure.get("complete"))
        ):
            status = "completed"
        else:
            status = lifecycle.status if lifecycle else "interrupted"
    run_state = {
        "run_key": latest.run_key,
        "task_id": str(task_id) if task_id else None,
        "status": status,
        "completed_scenes": completed,
        "total_scenes": len(steps),
        "structure_review": _structure_review_summary(structure),
    }
    unresolved = (run_state.get("structure_review") or {}).get("unresolved_reveals") or []
    scene_rows = await get_scenes_by_novel(db, str(novel_id)) if unresolved else []
    attention = _reading_attention_notice(
        run=run_state,
        run_row=latest,
        scene_rows=scene_rows,
        scope_hash=scope_hash,
        chapter_cutoff=chapter_cutoff,
        scene_index=scene_index,
        scene_id=scene_id,
    )
    return attention


async def list_reading_notices(
    db, novel_id: str, scope: dict[str, object]
) -> list[dict[str, Any]]:
    """Materialized by the app notice registry; this function never changes state."""
    await require_active_project(db, str(novel_id))
    scene_id = str(scope.get("scene_id") or "") or None
    scene = await get_scene_contract(db, str(novel_id), scene_id) if scene_id else None
    if scene_id and scene is None:
        return []
    chapter_cutoff = _chapter_cutoff(scope, scene)
    scene_index = int(scene.scene_index) if scene is not None else None
    sources = await get_manuscript_source_manifest(
        db,
        str(novel_id),
        content_mode="canonical",
        **({"chapter_to": chapter_cutoff} if chapter_cutoff else {}),
    )
    if chapter_cutoff is not None:
        sources = [
            source
            for source in sources
            if int(source.get("chapter_index") or 0) <= chapter_cutoff
        ]
    completed = set(await read_completed_chapter_indices(db, str(novel_id)))
    unread = [
        source
        for source in sources
        if int(source.get("chapter_index") or 0) not in completed
    ]
    scope_hash = _scope_fingerprint(
        novel_id=str(novel_id),
        chapter_cutoff=chapter_cutoff,
        scene_id=scene_id,
        scene_index=scene_index,
        sources=sources,
    )
    notices: list[dict[str, Any]] = []
    if unread:
        unread_rows = [_source_key(source) for source in unread]
        chapters = [int(source["chapter_index"]) for source in unread_rows]
        start = min(chapters)
        scope_key = scene_id or f"chapter-{chapter_cutoff or 0}"
        notices.append(
            {
                "notice_key": f"{SOURCE_ID}:unread:{scope_key}",
                "source_id": SOURCE_ID,
                "category": "reading_unread",
                "severity": "low",
                "target": {"chapter_index": start, "scene_id": scene_id},
                "summary": (
                    f"当前已采用正文中有 {len(unread)} 章"
                    "尚无覆盖当前版本的完整成功阅读回执。"
                    f"从第 {start} 章开始。"
                ),
                "evidence": [
                    {
                        "chapter_index": start,
                        "note": (
                            "是否已读只按当前正文版本对应的成功回执判断；"
                            "准备计划和失败尝试不算完成。"
                        ),
                    }
                ],
                "basis_fingerprint": stable_hash(
                    {"scope": scope_hash, "unread": unread_rows}
                ),
                "stale": False,
                "actions": [_action(chapter_index=start, scene_id=scene_id)],
                "disposition_ref": None,
            }
        )

    runs = (
        await db.scalars(
            select(EvolutionRun)
            .where(
                EvolutionRun.novel_id == UUID(str(novel_id)),
                EvolutionRun.execution_mode == "live",
                EvolutionRun.reading_plan_json.is_not(None),
            )
            .order_by(EvolutionRun.created_at.desc(), EvolutionRun.id.desc())
        )
    ).all()
    for run in runs:
        attention = await _run_attention(
            db,
            novel_id,
            run,
            scope_hash=scope_hash,
            chapter_cutoff=chapter_cutoff,
            scene_index=scene_index,
            scene_id=scene_id,
        )
        if attention is not None:
            notices.append(attention)
            break
    return notices


NOTICE_SOURCE_SPEC = {
    "source_id": SOURCE_ID,
    "label": "演化阅读",
    "list_notices": list_reading_notices,
}
