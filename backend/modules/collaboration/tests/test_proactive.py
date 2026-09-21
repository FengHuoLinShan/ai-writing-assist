"""Background cases share the original project slot without another execution root."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select

from core.config import get_settings
from infrastructure.tasks.models import AsyncTask
from modules.assistant import proactive as care
from modules.assistant.models import AssistantRun, AssistantWatch
from modules.collaboration import cases
from modules.collaboration.contracts import Grant, GrantUpdate
from modules.collaboration.models import CollaborationRun
from modules.collaboration.tests.test_workspaces import setup_trial


async def test_explicit_case_grant_shares_slot_and_projection_is_not_execution(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, test_project_id
    case, _, drafts, _ = await setup_trial(db, nid, monkeypatch)
    settings = replace(
        get_settings(), assistant_enabled=True, collaboration_v2_enabled=True
    )
    for name in [
        "modules.assistant.proactive",
        "modules.assistant.creative_queue",
        "modules.assistant.forecast.queue",
        "modules.collaboration.proactive",
    ]:
        monkeypatch.setattr(name + ".get_settings", lambda: settings)
    case = await cases.update_grant(
        db,
        nid,
        case["id"],
        GrantUpdate(
            expected_grant_hash=case["grant_hash"],
            grant=Grant.model_validate({**case["grant"], "follow_changes": True}),
        ),
    )
    before = await db.scalar(select(func.count()).select_from(AsyncTask))
    await care.mark_changed(db, nid, "writing_draft", drafts[0].id)
    row = await db.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == UUID(nid))
    )
    assert row.policy_json["creative_v2"]["case_ids"] == [case["id"]]
    change = row.dirty_json["_creative_v2"][case["id"]]
    assert datetime.fromisoformat(change["due_at"]) > datetime.now(UTC) + timedelta(
        seconds=40
    )
    assert await db.scalar(select(func.count()).select_from(AsyncTask)) == before
    past = datetime.now(UTC) - timedelta(seconds=1)
    row.dirty_json = {
        "_creative_v2": {case["id"]: {**change, "due_at": past.isoformat()}}
    }
    row.due_at = past
    await db.flush()
    assert await care.schedule_due(db) == 1
    run = await db.scalar(
        select(CollaborationRun).where(CollaborationRun.case_id == UUID(case["id"]))
    )
    projection = await db.get(AssistantRun, run.id)
    assert row.active_run_id == run.id
    assert projection.id == run.id and projection.task_id == run.task_id
    assert projection.request_json["authority"] == "collaboration_run"
    assert run.request_json["background"] is True
    task = await db.get(AsyncTask, run.task_id)
    assert task.task_type == "collaboration_run"
    assert await care.schedule_due(db) == 0
    await cases.stop_run(db, nid, str(run.id))
    assert row.active_run_id is None and projection.status == "cancelled"
    assert run.budget_json["requests"] == 0
