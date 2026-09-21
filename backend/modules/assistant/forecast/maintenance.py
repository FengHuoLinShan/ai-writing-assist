"""Bounded retention and operational projections; never delete adopted assets."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update

from modules.assistant.forecast.models import ForecastCandidate
from modules.assistant.models import AssistantRun, AssistantWatch


async def expire_assessments(db):
    candidates = (
        await db.execute(
            select(ForecastCandidate.id, ForecastCandidate.novel_id)
            .where(
                ForecastCandidate.validation_state == "valid",
                ForecastCandidate.expires_at <= datetime.now(UTC),
            )
            .order_by(ForecastCandidate.novel_id, ForecastCandidate.expires_at)
            .limit(500)
        )
    ).all()
    from core.errors import NotFoundError
    from modules.project.facade import (
        get_any_project_context,
        require_active_project,
        require_interaction_project,
    )

    ids = []
    for novel_id in dict.fromkeys(value.novel_id for value in candidates):
        project = await get_any_project_context(db, str(novel_id))
        if project is None:
            continue
        try:
            await (
                require_interaction_project
                if project.project_kind == "interaction"
                else require_active_project
            )(db, str(novel_id))
        except NotFoundError:
            continue
        ids += [value.id for value in candidates if value.novel_id == novel_id]
    if ids:
        await db.execute(
            update(ForecastCandidate)
            .where(
                ForecastCandidate.id.in_(ids),
                ForecastCandidate.validation_state == "valid",
            )
            .values(validation_state="expired")
        )
    # Immutable assessment, source and merge receipts survive expiry. Project
    # deletion is the existing cascade boundary, not a destructive table downgrade.
    return len(ids)


async def diagnostics(db, novel_id):
    rows = (
        await db.scalars(
            select(AssistantRun)
            .where(
                AssistantRun.novel_id == UUID(novel_id),
                AssistantRun.request_json["protocol"]
                .as_string()
                .in_(["forecast_v1", "creative_projection_v2"]),
                AssistantRun.created_at >= datetime.now(UTC) - timedelta(days=1),
            )
            .order_by(AssistantRun.created_at.desc())
            .limit(1001)
        )
    ).all()
    complete, rows = len(rows) <= 1000, rows[:1000]
    unknown = sum(
        int((row.budget_json or {}).get("pending_usage", 0))
        + int((row.budget_json or {}).get("usage_unknown", 0))
        for row in rows
    )
    watch = await db.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == UUID(novel_id))
    )
    due = watch.due_at if watch else None
    if due and due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    lag = max(0, (datetime.now(UTC) - due).total_seconds()) if due else 0
    return {
        "window": "past_24_hours",
        "enumeration_complete": complete,
        "runs": len(rows),
        "requests": sum(int((row.budget_json or {}).get("requests", 0)) for row in rows),
        "unknown_usage": unknown,
        "source_rejections": sum(
            (row.result_json or {}).get("error_code")
            in {"SOURCE_STALE", "POLICY_CHANGED", "GOAL_CHANGED"}
            for row in rows
        ),
        "queue_lag_seconds": lag,
        "alerts": [
            *(["用量仍有未确认项，不应据此宣称完整成本。"] if unknown else []),
            *(
                ["后台队列已等待超过十分钟，请核对占用任务与恢复状态。"]
                if lag > 600
                else []
            ),
        ],
        "retention": "评估到期后失效，保留采用与来源回执；项目永久删除沿原级联清理。",
    }
