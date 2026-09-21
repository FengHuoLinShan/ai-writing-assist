from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from core.config import get_settings
from infrastructure.tasks.models import AsyncTask
from modules.collaboration import cases, maintenance
from modules.collaboration.contracts import RunCreate
from modules.collaboration.models import (
    CollaborationCase,
    CollaborationRun,
    CreativeWorkspace,
)
from modules.collaboration.tests.test_workspaces import setup_trial


@pytest.mark.parametrize("reason", ["expiry", "shutdown"])
async def test_maintenance_cancels_execution_and_retains_trial_budget(
    db_session, test_project_id, account_llm_connection, monkeypatch, reason
):
    db, nid = db_session, test_project_id
    case, workspace, _, _ = await setup_trial(db, nid, monkeypatch)
    submission = await cases.submit_run(
        db, nid, case["id"], RunCreate(operation_id=uuid4(), expected_goal_version=1)
    )
    case_row = await db.get(CollaborationCase, UUID(case["id"]))
    case_row.requests_used = 3
    if reason == "expiry":
        case_row.grant_json = {
            **case_row.grant_json,
            "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        }
    settings = replace(
        get_settings(),
        assistant_enabled=True,
        collaboration_v2_enabled=reason != "shutdown",
    )
    monkeypatch.setattr(maintenance, "get_settings", lambda: settings)
    await db.flush()
    assert await maintenance.stop_unavailable_runs(db) == 1
    assert await maintenance.stop_unavailable_runs(db) == 0
    run = await db.get(CollaborationRun, UUID(submission["run_id"]))
    task = await db.get(AsyncTask, UUID(submission["task_id"]))
    assert run.status == task.status == "cancelled"
    assert run.error_code == "GRANT_UNAVAILABLE" and case_row.requests_used == 3
    assert await db.get(CreativeWorkspace, UUID(workspace["id"])) is not None
