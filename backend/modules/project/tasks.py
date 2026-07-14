from __future__ import annotations

import inspect

from infrastructure.tasks.registry import task_handler
from modules.project.smart_dedup import SmartDedupService


@task_handler("smart_dedup_scan", recovery_policy="restart_origin")
async def handle_smart_dedup_scan(db, task):
    """Run one project-wide smart dedupe scan and store suggestions in task result."""
    meta = task.meta or {}
    novel_id = str(meta.get("novel_id") or "")
    if not novel_id:
        raise ValueError("novel_id is required for smart_dedup_scan")

    task.update_progress(0.03)

    def _progress(value: float) -> None:
        task.update_progress(max(0.03, min(0.98, value)))

    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        create_project_snapshot_llm_client,
        restore_project_llm_execution_settings,
    )

    snapshot = meta.get("llm_execution_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        snapshot = await build_project_llm_execution_snapshot(db, novel_id)
        task.meta = {**meta, "llm_execution_snapshot": snapshot}
        # Worker sessions fence commit() with the active lease and merge detached
        # task metadata. Persist the frozen profile before any restore or LLM call
        # so a crashed attempt cannot rebuild it from later project settings.
        await db.commit()
    project_settings = await restore_project_llm_execution_settings(
        db, novel_id, snapshot
    )
    client = create_project_snapshot_llm_client(project_settings, novel_id=novel_id)
    try:
        result = await SmartDedupService().scan(
            db,
            novel_id=novel_id,
            scopes=meta.get("scopes"),
            limit_per_scope=int(meta.get("limit_per_scope", 1000)),
            max_suggestions=int(meta.get("max_suggestions", 120)),
            progress_callback=_progress,
            llm_client=client,
        )
    finally:
        await client.close()
    task.update_progress(1.0)
    flush = getattr(db, "flush", None)
    if flush is not None:
        result_flush = flush()
        if inspect.isawaitable(result_flush):
            await result_flush
    return result
