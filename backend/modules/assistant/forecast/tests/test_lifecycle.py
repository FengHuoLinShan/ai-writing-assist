"""Quiet wakeups and quota rollover use real notices/watch rows, without a model."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from infrastructure.tasks.models import AsyncTask
from modules.assistant import proactive
from modules.assistant.forecast import queue, wake
from modules.assistant.forecast.contracts import FocusRequest
from modules.assistant.models import AssistantNotice, AssistantRun, AssistantWatch
from modules.assistant.schemas import ProactivePolicy
from modules.assistant.tests.test_proactive import enabled  # noqa: F401
from modules.evidence.contracts import (
    RagEntityActivityBundleContract,
    RagEntityActivityStatContract,
)
from modules.project.facade import get_project_context
from modules.story.outline_state.models import Scene


async def test_wake_conditions_require_new_event_and_keep_missing_source_pending(
    db_session, test_project_id, monkeypatch
):
    db, nid, entity = db_session, test_project_id, str(uuid4())
    scene = Scene(novel_id=UUID(nid), scene_index=1, title="等待")
    db.add(scene)
    await db.flush()
    stats = {"chapter": 1}

    async def appearances(_db, _novel):
        return RagEntityActivityBundleContract(
            items=[
                RagEntityActivityStatContract(
                    entity_id=entity,
                    appearance_chapters=[stats["chapter"]],
                    last_chapter_index=stats["chapter"],
                )
            ],
            status="ready",
        )

    monkeypatch.setattr(wake, "get_entity_activity_stats", appearances)
    condition = await wake.freeze_condition(
        db,
        nid,
        {
            "kind": "object_reappears",
            "object_id": entity,
            "after_event_token": "original-event",
        },
    )
    waiting = AssistantNotice(
        novel_id=UUID(nid),
        fingerprint="a" * 64,
        title="稍后再看",
        summary="原说明",
        status="snoozed",
        result_ref_json={
            "type": "forecast",
            "forecast_v1": {"wake_condition": condition},
        },
    )
    archived = AssistantNotice(
        novel_id=UUID(nid),
        fingerprint="b" * 64,
        title="场景",
        summary="原说明",
        status="snoozed",
        result_ref_json={
            "type": "forecast",
            "forecast_v1": {
                "wake_condition": {"kind": "scene_activated", "target_id": str(scene.id)}
            },
        },
    )
    db.add_all([waiting, archived])
    await db.flush()
    before = await db.scalar(select(func.count()).select_from(AsyncTask))
    assert (await wake.evaluate_conditions(db, nid))["woken"] == 0
    assert waiting.status == "snoozed"
    stats["chapter"] = 2
    assert (await wake.evaluate_conditions(db, nid))["woken"] == 1
    assert (await wake.evaluate_conditions(db, nid))["woken"] == 0
    scene.status = "deprecated"
    await db.flush()
    focus = FocusRequest(
        client_context_id=uuid4(), focus_seq=1, page="scene", scene_id=scene.id
    )
    assert (await wake.evaluate_conditions(db, nid, focus))["woken"] == 0
    assert archived.status == "snoozed"
    assert archived.result_ref_json["forecast_v1"]["wake_status"] == "unavailable"
    assert await db.scalar(select(func.count()).select_from(AsyncTask)) == before


@pytest.mark.usefixtures("enabled")
async def test_rolling_quota_survives_midnight_timezone_and_new_changes(
    db_session, test_project_id, monkeypatch
):
    db, nid = db_session, test_project_id
    now = datetime(2026, 9, 21, 16, 10, tzinfo=UTC)  # Shanghai next-day 00:10.
    monkeypatch.setattr(proactive, "_now", lambda: now)
    await proactive.save_policy(
        db, nid, ProactivePolicy(enabled=True, daily_limit=1, timezone="Asia/Shanghai")
    )
    row = await db.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == UUID(nid))
    )
    row.policy_json = {**row.policy_json, "forecast_v1": {}}
    project = await get_project_context(db, nid)
    previous = now - timedelta(hours=1)
    db.add(
        AssistantRun(
            novel_id=UUID(nid),
            owner_id=UUID(project.owner_id),
            mode="background",
            status="completed",
            request_hash="a" * 64,
            created_at=previous,
        )
    )
    asset = str(uuid4())
    await proactive.mark_changed(db, nid, "writing_draft", asset)
    row.due_at = now - timedelta(seconds=1)
    await db.flush()
    assert await proactive.schedule_due(db) == 0
    assert row.due_at == previous + timedelta(days=1)
    await proactive.mark_changed(db, nid, "writing_draft", asset)
    assert row.due_at == previous + timedelta(days=1)
    row.policy_json = {
        **row.policy_json,
        "settings": {**row.policy_json["settings"], "timezone": "UTC"},
    }
    queue.refresh_due(row)
    assert row.due_at == previous + timedelta(days=1)
