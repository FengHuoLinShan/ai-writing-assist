"""Author-controlled deferral and continuation of the existing import workflow."""

from __future__ import annotations

import uuid
from copy import deepcopy

from sqlalchemy import func, select

from modules.imports.models import ImportWorkflowRun


async def read_completion_control(db, *, task_id: str, novel_id: str) -> dict:
    value = (
        await db.execute(
            select(ImportWorkflowRun.checkpoints).where(
                ImportWorkflowRun.task_id == uuid.UUID(task_id),
                ImportWorkflowRun.novel_id == uuid.UUID(novel_id),
            )
        )
    ).scalar_one_or_none()
    return dict(value.get("completion_control") or {}) if isinstance(value, dict) else {}


async def request_completion_defer(db, *, task_id: str) -> dict:
    run = (
        await db.execute(
            select(ImportWorkflowRun)
            .where(
                ImportWorkflowRun.task_id == uuid.UUID(task_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if run is None:
        raise ValueError("整理记录不存在")
    completion_status = (
        (run.checkpoints or {}).get("targeted_completion", {}).get("status")
    )
    if completion_status in {"done", "deferred"} and run.status == "done":
        return {
            "task_id": task_id,
            "status": completion_status,
            "message": "查漏已暂缓"
            if completion_status == "deferred"
            else "本轮查漏已经完成",
        }
    if run.status not in {"pending", "running"}:
        raise ValueError("本次整理未在运行，请从最近成果继续查看")
    if completion_status == "done":
        return {
            "task_id": task_id,
            "status": "done",
            "message": "本轮查漏已经完成，其余整理仍在进行",
        }
    if not (run.authorization_snapshot or {}).get("targeted_completion"):
        raise ValueError("本次任务不包含专项查漏")
    run.checkpoints = {
        **dict(run.checkpoints or {}),
        "completion_control": {
            "version": 1,
            "defer_requested": True,
            "resume_requested": False,
        },
    }
    await db.flush()
    return {
        "task_id": task_id,
        "status": "defer_requested",
        "message": "将在当前安全检查点暂缓查漏，已完成成果保留",
    }


async def resume_deferred_completion(db, *, task_id: str, orchestrator) -> dict:
    from infrastructure.tasks.facade import resume_manual_task, update_task_projection
    from modules.imports.targeted_completion import authorize_completion, stable_hash
    from modules.project.facade import require_active_project_exclusive
    from modules.writing.facade import list_latest_drafts_for_chapters

    run = await orchestrator._runs.get_by_task(db, task_id=task_id)
    if run is None:
        raise ValueError("整理记录不存在")
    novel_id = str(run.novel_id)
    await require_active_project_exclusive(db, novel_id)
    run = (
        await db.execute(
            select(ImportWorkflowRun)
            .where(ImportWorkflowRun.task_id == uuid.UUID(task_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    state = deepcopy((run.checkpoints or {}).get("targeted_completion") or {})
    if (
        run.status != "done"
        or state.get("status") != "deferred"
        or state.get("rollback_receipts") is not None
    ):
        raise ValueError("只有已暂缓且未撤销的查漏阶段可以继续")
    active = await orchestrator._find_active_import_task(db, novel_id)
    if active is not None:
        raise ValueError("本作品已有整理任务，请等待当前任务完成")
    permission = deepcopy(
        (run.authorization_snapshot or {}).get("targeted_completion") or {}
    )
    drafts = await list_latest_drafts_for_chapters(
        db, novel_id, list(range(run.start_chapter, run.end_chapter + 1)), content_limit=1
    )
    if {str(draft.id): draft.content_hash for draft in drafts} != permission.get(
        "source_manifest"
    ):
        raise ValueError("章节来源已变化，请重新核对范围并发起查漏；原成果仍保留")
    if not permission.get("authorization_id"):
        if state.get("root_position") or state.get("packages"):
            raise ValueError("查漏授权与已有成果不一致")
        permission.update(enabled=True, roots=state["roots"])
        permission = await authorize_completion(
            db, novel_id=novel_id, task_id=task_id, permission=permission
        )
        state["permission_fingerprint"] = stable_hash(permission)
    state["status"] = "running"
    run.authorization_snapshot = {
        **run.authorization_snapshot,
        "targeted_completion": permission,
    }
    run.checkpoints = {
        **run.checkpoints,
        "targeted_completion": state,
        "completion_control": {
            "version": 1,
            "defer_requested": False,
            "resume_requested": True,
        },
    }
    result = {
        **dict(run.progress or {}),
        "phase": "pending",
        "authorization_snapshot": run.authorization_snapshot,
        "checkpoints": run.checkpoints,
        "targeted_completion": {
            **dict((run.progress or {}).get("targeted_completion") or {}),
            "status": "running",
            "available_actions": [],
        },
    }
    resumed = await resume_manual_task(
        db,
        task_id=task_id,
        task_types={run.workflow_type},
        novel_id=novel_id,
        allow_completed=True,
    )
    if resumed.status != "pending":
        raise ValueError("已有后续任务，请重新查看整理记录")
    run.generation += 1
    run.status = "pending"
    run.recovery_required = False
    orchestrator._runs._clear_owner(run)
    run.progress = result
    await update_task_projection(
        db,
        task_id=task_id,
        task_type=run.workflow_type,
        novel_id=novel_id,
        result=result,
        meta_patch={"authorization_snapshot": run.authorization_snapshot},
        progress=state["root_position"] / max(1, len(state["roots"])),
    )
    await db.flush()
    return {
        "workflow_id": str(run.id),
        "task_id": task_id,
        "status": "pending",
        "message": "从上次检查点继续查漏，基础成果不重跑",
    }


async def list_recent_workflows(db, *, novel_id: str, skip: int, limit: int) -> dict:
    condition = ImportWorkflowRun.novel_id == uuid.UUID(novel_id)
    total = (
        await db.execute(
            select(func.count()).select_from(ImportWorkflowRun).where(condition)
        )
    ).scalar_one()
    runs = (
        (
            await db.execute(
                select(ImportWorkflowRun)
                .where(condition)
                .order_by(
                    ImportWorkflowRun.created_at.desc(), ImportWorkflowRun.id.desc()
                )
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "task_id": str(run.task_id),
                "workflow_type": run.workflow_type,
                "status": run.status,
                "recovery_required": run.recovery_required,
                "start_chapter": run.start_chapter,
                "end_chapter": run.end_chapter,
                "created_at": run.created_at.isoformat(),
                "message": (run.progress or {}).get("message", ""),
                "asset_summary": (run.progress or {}).get("asset_summary", {}),
                "quality_status": (run.progress or {}).get("quality_status", "pending"),
                "failed_stages": sorted(
                    {
                        stage
                        for item in (run.progress or {}).get("phase_errors", [])
                        if (
                            stage := {
                                "structure_analysis": "plot_structure",
                                "entity_extraction": "world_objects",
                                "scene_segmentation": "scenes",
                            }.get(item.get("phase"))
                        )
                    }
                ),
                "targeted_completion": {
                    key: value
                    for key, value in (
                        (run.progress or {}).get("targeted_completion") or {}
                    ).items()
                    if key
                    in {
                        "status",
                        "root_count",
                        "completed_roots",
                        "created",
                        "filled",
                        "review",
                        "available_actions",
                    }
                },
                "defer_requested": bool(
                    (run.checkpoints or {})
                    .get("completion_control", {})
                    .get("defer_requested")
                ),
            }
            for run in runs
        ],
    }


async def active_asset_impact(db, *, novel_id: str, asset_id: str) -> dict:
    from modules.evidence.facade import list_context_snapshots

    runs = (
        (
            await db.execute(
                select(ImportWorkflowRun).where(
                    ImportWorkflowRun.novel_id == uuid.UUID(novel_id),
                    ImportWorkflowRun.status.in_(["pending", "running"]),
                )
            )
        )
        .scalars()
        .all()
    )

    def includes(value):
        if isinstance(value, dict):
            return any(includes(item) for item in value.values())
        if isinstance(value, list):
            return any(includes(item) for item in value)
        return value == asset_id

    items = []
    for run in runs:
        units = set()
        offset = 0
        while True:
            snapshots = await list_context_snapshots(
                db,
                novel_id=novel_id,
                workflow_id=str(run.task_id),
                limit=100,
                offset=offset,
            )
            for snapshot in snapshots:
                if snapshot.status == "running" and includes(snapshot.included_asset_ids):
                    units.add(snapshot.chapter_index)
            if len(snapshots) < 100:
                break
            offset += 100
        if units:
            items.append(
                {
                    "task_id": str(run.task_id),
                    "label": {
                        "deep_import": "正文基础整理",
                        "world_object_auto_extraction": "世界资料整理",
                        "plot_structure_auto_extraction": "剧情结构整理",
                        "targeted_completion": "专项查漏",
                    }.get(run.workflow_type, "资料整理"),
                    "chapters": sorted(index for index in units if index is not None),
                    "whole_unit": None in units,
                    "message": (
                        "正在进行的整理引用了这份资料；保存修改后，"
                        "受影响结果需重新核对，有效的独立成果保留。"
                    ),
                }
            )
    return {"items": items}
