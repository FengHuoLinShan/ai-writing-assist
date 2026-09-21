"""Worker housekeeping for revoked/expired execution, preserving all receipts."""

from datetime import UTC, datetime

from sqlalchemy import or_, select

from core.config import get_settings
from infrastructure.tasks.facade import cancel_exact_task
from modules.assistant.facade import lock_background_slot
from modules.collaboration.cases import sync_background_projection
from modules.collaboration.contracts import Grant
from modules.collaboration.models import (
    CollaborationCase,
    CollaborationRun,
    CollaborationWorkItem,
)


async def stop_unavailable_runs(db):
    settings = get_settings()
    unavailable = or_(
        CollaborationCase.status != "active",
        CollaborationCase.grant_json["expires_at"].as_string()
        <= datetime.now(UTC).isoformat(),
        CollaborationCase.recipe_json["id"]
        .as_string()
        .in_(settings.creative_disabled_recipes),
    )
    candidates = (
        await db.execute(
            select(
                CollaborationRun.id, CollaborationRun.novel_id, CollaborationRun.case_id
            )
            .join(
                CollaborationCase,
                (CollaborationCase.id == CollaborationRun.case_id)
                & (CollaborationCase.novel_id == CollaborationRun.novel_id),
            )
            .where(
                CollaborationRun.status.in_(["pending", "running"]),
                unavailable
                if settings.assistant_enabled and settings.collaboration_v2_enabled
                else True,
            )
            .order_by(CollaborationRun.created_at)
            .limit(50)
        )
    ).all()
    stopped = 0
    for run_id, novel_id, case_id in candidates:
        case = await db.get(CollaborationCase, case_id)
        if case is None:
            continue
        grant = Grant.model_validate(case.grant_json)
        if (
            settings.assistant_enabled
            and settings.collaboration_v2_enabled
            and case.status == "active"
            and grant.expires_at > datetime.now(UTC)
            and case.recipe_json["id"] not in settings.creative_disabled_recipes
        ):
            continue
        await lock_background_slot(db, str(novel_id))
        case = await db.scalar(
            select(CollaborationCase)
            .where(
                CollaborationCase.id == case_id, CollaborationCase.novel_id == novel_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if case is None:
            continue
        grant = Grant.model_validate(case.grant_json)
        if (
            settings.assistant_enabled
            and settings.collaboration_v2_enabled
            and case.status == "active"
            and grant.expires_at > datetime.now(UTC)
            and case.recipe_json["id"] not in settings.creative_disabled_recipes
        ):
            continue
        run = await db.scalar(
            select(CollaborationRun)
            .where(CollaborationRun.id == run_id, CollaborationRun.novel_id == novel_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None or run.status not in {"pending", "running"}:
            continue
        if run.task_id:
            await cancel_exact_task(
                db,
                novel_id=str(novel_id),
                task_id=str(run.task_id),
                task_types={"collaboration_run"},
                transition_reason="creative_grant_unavailable",
            )
        run.status, run.error_code = "cancelled", "GRANT_UNAVAILABLE"
        run.generation += 1
        work = (
            await db.scalars(
                select(CollaborationWorkItem).where(
                    CollaborationWorkItem.novel_id == novel_id,
                    CollaborationWorkItem.run_id == run_id,
                    CollaborationWorkItem.status.in_(["pending", "running"]),
                )
            )
        ).all()
        for item in work:
            item.status = "cancelled"
        await sync_background_projection(db, run, case)
        stopped += 1
    await db.flush()
    return stopped
