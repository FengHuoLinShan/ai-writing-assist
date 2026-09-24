"""Forecast targets share the original watch lock, active slot and daily quota."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4, uuid5

from core.config import get_settings
from core.errors import DomainError
from modules.assistant.forecast.contracts import EvaluateRequest, FocusRequest, Horizon
from modules.assistant.forecast.policy import effective_policy


def automatic(row):
    policy = effective_policy(row)
    settings = get_settings()
    return bool(
        policy.enabled
        and policy.automatic
        and settings.assistant_enabled
        and settings.assistant_forecast_enabled
        and settings.assistant_forecast_automatic_enabled
        and settings.assistant_forecast_semantic_enabled
    )


def pending(row):
    return dict((row.dirty_json or {}).get("_forecast_v1", {}).get("pending", {}))


def record_change(row, asset_type, asset_id, now):
    if not automatic(row):
        return
    if asset_id in {
        value.rsplit(":", 1)[-1]
        for value in (row.policy_json.get("settings") or {}).get("excluded_targets", [])
    }:
        return
    page = {
        "writing_draft": "writing",
        "outline_scene": "scene",
        "core_entity": "world",
        "world_bible_page": "world",
        "world_bible_draft": "world",
        "plot_thread": "outline",
        "outline_arc": "outline",
        "foreshadowing_plan": "outline",
        "reveal_plan": "outline",
        "import_workflow": "imports",
    }.get(asset_type)
    if page is None:
        return
    partition = dict((row.dirty_json or {}).get("_forecast_v1", {}))
    targets = pending(row)
    key = f"{asset_type}:{asset_id}"
    if key not in targets and len(targets) >= 200:
        partition["overflow"] = True
    else:
        due = now + timedelta(seconds=8)
        previous = (row.last_checked_json or {}).get(f"forecast:{key}")
        if previous:
            due = max(due, datetime.fromisoformat(previous["at"]) + timedelta(seconds=45))
        focus = {
            "client_context_id": str(uuid5(row.novel_id, "forecast-background")),
            "focus_seq": 0,
            "page": page,
            "editor_state": "saved" if page == "writing" else "not_applicable",
        }
        if page == "writing":
            focus["draft_id"] = asset_id
        elif page == "scene":
            focus["scene_id"] = asset_id
        else:
            focus["target"] = {
                "resource_kind": "world_bible_draft"
                if asset_type == "world_bible_draft"
                else asset_type,
                "resource_id": asset_id,
            }
        targets[key] = {
            "context": focus,
            "changed_at": now.isoformat(),
            "due_at": due.isoformat(),
        }
    row.dirty_json = {
        **(row.dirty_json or {}),
        "_forecast_v1": {**partition, "pending": targets},
    }
    refresh_due(row)


def due_targets(row, now):
    if not automatic(row):
        return []
    return [
        (key, value)
        for key, value in pending(row).items()
        if not value.get("blocked") and datetime.fromisoformat(value["due_at"]) <= now
    ]


def refresh_due(row):
    from modules.assistant import creative_queue, editorial_queue

    dates = [
        datetime.fromisoformat(value["due_at"])
        for key, value in (row.dirty_json or {}).items()
        if not key.startswith("_") and not value.get("blocked") and value.get("due_at")
    ]
    if automatic(row):
        dates += [
            datetime.fromisoformat(value["due_at"])
            for value in pending(row).values()
            if not value.get("blocked")
        ]
    if creative_queue.enabled(row):
        dates += [
            datetime.fromisoformat(value["due_at"])
            for value in creative_queue.pending(row).values()
            if not value.get("blocked")
        ]
    if editorial_queue.enabled(row):
        dates += [
            datetime.fromisoformat(value["due_at"])
            for value in editorial_queue.pending(row).values()
            if not value.get("blocked")
        ]
    not_before = (row.dirty_json or {}).get("_scheduler", {}).get("not_before")
    row.due_at = (
        max(min(dates), datetime.fromisoformat(not_before))
        if dates and not_before
        else min(dates)
        if dates
        else None
    )


async def claim(db, row, key, change):
    from modules.assistant.forecast.runtime import submit

    targets = pending(row)
    try:
        async with db.begin_nested():
            focus = FocusRequest.model_validate(change["context"])
            policy = effective_policy(row)
            submission = await submit(
                db,
                str(row.novel_id),
                EvaluateRequest(
                    operation_id=uuid4(),
                    context=focus,
                    horizon=Horizon(
                        unit="scene" if focus.page in {"writing", "scene"} else "decision"
                    ),
                    trigger="saved_change",
                    requested_capabilities=policy.enabled_capabilities,
                ),
                background=True,
            )
    except (DomainError, ValueError):
        targets[key] = {**change, "blocked": True}
        submitted = False
    else:
        targets.pop(key, None)
        row.active_run_id = submission.run_id
        row.last_checked_json = {
            **(row.last_checked_json or {}),
            f"forecast:{key}": {
                "at": datetime.now(UTC).isoformat(),
                "change_at": change["changed_at"],
            },
        }
        submitted = True
    partition = dict((row.dirty_json or {}).get("_forecast_v1", {}))
    row.dirty_json = {
        **(row.dirty_json or {}),
        "_forecast_v1": {**partition, "pending": targets},
    }
    refresh_due(row)
    await db.flush()
    return submitted
