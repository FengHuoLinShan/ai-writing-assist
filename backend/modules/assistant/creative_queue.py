"""Shared background slot and daily-count projection for authoritative Case runs."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from core.config import get_settings
from core.errors import ConflictError, DomainError, ValidationError
from modules.assistant.models import AssistantRun
from modules.assistant.proactive import _watch
from modules.project.facade import get_any_project_context


def enabled(row):
    return (
        get_settings().assistant_enabled
        and get_settings().collaboration_v2_enabled
        and bool((row.policy_json or {}).get("creative_v2", {}).get("case_ids"))
    )


def pending(row):
    return dict((row.dirty_json or {}).get("_creative_v2", {}))


async def register(db, novel_id, case_id, active):
    row = await _watch(db, novel_id, create=active, lock=True)
    if row is None:
        return
    project = await get_any_project_context(db, novel_id)
    ids = set((row.policy_json or {}).get("creative_v2", {}).get("case_ids", []))
    if active:
        ids.add(str(case_id))
    else:
        ids.discard(str(case_id))
    if len(ids) > 64:
        raise ValidationError("一部作品最多跟进六十四个创作目标，请先暂停不再需要的目标")
    row.policy_json = {
        **(row.policy_json or {}),
        "owner_id": str(project.owner_id),
        "creative_v2": {"case_ids": sorted(ids)},
    }
    changes = pending(row)
    if not active:
        changes.pop(str(case_id), None)
    row.dirty_json = {**(row.dirty_json or {}), "_creative_v2": changes}
    from modules.assistant.forecast.queue import refresh_due

    refresh_due(row)
    await db.flush()


async def mark_changed(db, row, kind, identity):
    if not enabled(row):
        return
    from modules.collaboration.facade import changed_cases

    matches = await changed_cases(
        db, str(row.novel_id), row.policy_json["creative_v2"]["case_ids"], kind, identity
    )
    changes = pending(row)
    now = datetime.now(UTC)
    for item in matches:
        previous = (row.last_checked_json or {}).get("creative:" + item["case_id"], {})
        if previous.get("source_hash") == item["source_hash"]:
            continue
        due = now + timedelta(seconds=45)
        if previous.get("at"):
            due = max(due, datetime.fromisoformat(previous["at"]) + timedelta(minutes=10))
        changes[item["case_id"]] = {
            **item,
            "due_at": due.isoformat(),
            "changed_at": now.isoformat(),
        }
    row.dirty_json = {**(row.dirty_json or {}), "_creative_v2": changes}


def due_targets(row, now):
    if not enabled(row):
        return []
    return [
        (key, value)
        for key, value in pending(row).items()
        if not value.get("blocked") and datetime.fromisoformat(value["due_at"]) <= now
    ]


async def claim(db, row, case_id, change):
    from modules.collaboration.facade import submit_changed_case

    changes = pending(row)
    try:
        async with db.begin_nested():
            submitted = await submit_changed_case(db, str(row.novel_id), case_id)
    except DomainError as error:
        changes[case_id] = {
            **change,
            **(
                {"due_at": (datetime.now(UTC) + timedelta(seconds=30)).isoformat()}
                if error.code == "ACTIVE_RUN_CONFLICT"
                else {"blocked": True}
            ),
        }
        submitted = None
    else:
        changes.pop(case_id, None)
        row.active_run_id = UUID(submitted["run_id"])
        row.last_checked_json = {
            **(row.last_checked_json or {}),
            "creative:" + case_id: {
                "at": datetime.now(UTC).isoformat(),
                "source_hash": change["source_hash"],
            },
        }
    row.dirty_json = {**(row.dirty_json or {}), "_creative_v2": changes}
    from modules.assistant.forecast.queue import refresh_due

    refresh_due(row)
    await db.flush()
    return submitted is not None


async def project_run(
    db, novel_id, run_id, *, owner_id, task_id, status, budget, case_id, request_hash
):
    """A read projection with the same ID; Collaboration alone executes and accounts."""
    watch = await _watch(db, novel_id, lock=True)
    row = await db.scalar(
        select(AssistantRun).where(
            AssistantRun.novel_id == UUID(novel_id), AssistantRun.id == UUID(run_id)
        )
    )
    if row is None:
        row = AssistantRun(
            id=UUID(run_id),
            novel_id=UUID(novel_id),
            owner_id=UUID(owner_id),
            operation_id=UUID(run_id),
            mode="background",
            request_hash=request_hash,
            request_json={
                "protocol": "creative_projection_v2",
                "case_id": case_id,
                "authority": "collaboration_run",
            },
        )
        db.add(row)
    if watch and status in {"pending", "running"}:
        if watch.active_run_id not in {None, UUID(run_id)}:
            raise ConflictError("另一次后台工作正在进行", code="ACTIVE_RUN_CONFLICT")
        watch.active_run_id = UUID(run_id)
    row.task_id, row.status, row.budget_json = (
        UUID(task_id),
        "completed" if status == "partial" else status,
        budget,
    )
    row.result_json = {
        "answer": "创作试验结果已保留，请在创作试验中查看。",
        "results": [{"type": "collaboration_run", "id": run_id}],
        "case_id": case_id,
    }
    if (
        watch
        and status not in {"pending", "running"}
        and str(watch.active_run_id) == run_id
    ):
        watch.active_run_id = None
        from modules.assistant.forecast.queue import refresh_due

        refresh_due(watch)
    await db.flush()
