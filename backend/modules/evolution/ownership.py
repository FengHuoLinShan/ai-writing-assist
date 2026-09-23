"""Explicit project canary/stop; never changes provider, budgets or source history."""

from sqlalchemy import select

from core.errors import ConflictError
from modules.evolution.models import EvolutionRun


async def switch_project_engine(
    db, novel_id, *, to_engine, expected_epoch, stop_active=False
):
    from infrastructure.tasks.facade import cancel_unfinished_tasks_for_novel
    from modules.imports.facade import drain_understanding_owner
    from modules.project.facade import (
        advance_understanding_engine,
        get_understanding_engine,
        require_active_project_exclusive,
    )

    await require_active_project_exclusive(db, str(novel_id))
    current = await get_understanding_engine(db, novel_id)
    if expected_epoch != current["epoch"]:
        raise ConflictError(
            "理解流程状态已变化，请重新读取", code="understanding_owner_changed"
        )
    if to_engine not in {"legacy", "evolution", "read_only"}:
        raise ValueError("unsupported understanding engine")
    if to_engine == "legacy" and current["schema_floor"] > 1:
        raise ConflictError(
            "旧引擎不能解释新版理解；可暂停并前向修复",
            code="incompatible_engine_rollback",
        )
    stopped_imports = await drain_understanding_owner(
        db, str(novel_id), stop_active=stop_active
    )
    from uuid import UUID

    runs = list(
        (
            await db.scalars(
                select(EvolutionRun)
                .where(
                    EvolutionRun.novel_id == UUID(str(novel_id)),
                    EvolutionRun.execution_mode == "live",
                    EvolutionRun.status == "active",
                )
                .order_by(EvolutionRun.id)
                .with_for_update()
            )
        ).all()
    )
    if runs and not stop_active:
        raise ConflictError("演化流程尚未排空；请完成或明确停止后切换")
    for run in runs:
        run.status = "stopped"
        run.owner_epoch += 1
    await db.flush()
    cancelled_tasks = await cancel_unfinished_tasks_for_novel(
        db,
        novel_id=str(novel_id),
        transition_reason="understanding_engine_changed",
        task_types={
            "deep_import",
            "scene_auto_extraction",
            "world_object_auto_extraction",
            "plot_structure_auto_extraction",
            "targeted_completion",
            "import_review_resolution",
            "evolution_scene_step",
            "evolution_scene_step_v2",
        },
    )
    state = await advance_understanding_engine(
        db, novel_id, engine=to_engine, expected_epoch=expected_epoch
    )
    return {
        **state,
        "stopped_imports": stopped_imports,
        "stopped_evolution_runs": len(runs),
        "cancelled_tasks": cancelled_tasks,
    }
