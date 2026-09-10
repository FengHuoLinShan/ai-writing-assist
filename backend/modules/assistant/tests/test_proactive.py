"""Standing authorization, transactional changes, bounded reviews and notices."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from core.config import get_settings
from core.container import container_scope
from core.errors import ValidationError
from infrastructure.llm.schemas import LLMUsage
from infrastructure.llm.workflow_budget import current_workflow_budget
from infrastructure.tasks.facade import enqueue_task
from infrastructure.tasks.models import AsyncTask
from modules.assistant import proactive
from modules.assistant.models import AssistantNotice, AssistantRun, AssistantWatch
from modules.assistant.schemas import NoticeDecision, ProactivePolicy


@pytest.fixture
def enabled(monkeypatch):
    settings = replace(get_settings(), assistant_enabled=True)
    monkeypatch.setattr(proactive, "get_settings", lambda: settings)


async def _submit(db, novel_id, change, meta):
    task_id = enqueue_task(db, "writing_semantic_review", novel_id=novel_id, meta=meta)
    await db.flush()
    return {
        "task_id": task_id,
        "target": {"type": "writing_draft", "id": change["asset_id"]},
    }


async def _due(db, novel_id, monkeypatch):
    row = await db.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == UUID(novel_id))
    )
    clock = datetime.now(UTC) + timedelta(seconds=61)
    monkeypatch.setattr(proactive, "_now", lambda: clock)
    assert await proactive.schedule_due(db) == 1
    await db.commit()
    run = await db.get(AssistantRun, row.active_run_id)
    task = await db.get(AsyncTask, run.task_id)
    task.status = "running"
    await db.commit()
    return row, run, task


@pytest.mark.asyncio
async def test_failed_notice_recheck_keeps_old_budget_and_rejects_replay_or_revoked_scope(
    db_session, test_project_id, enabled, monkeypatch
):
    db, nid, asset = db_session, test_project_id, str(uuid4())
    await proactive.save_policy(db, nid, ProactivePolicy(enabled=True))
    await proactive.mark_changed(db, nid, "writing_draft", asset)
    with container_scope({"assistant.proactive.submitters": {"writing": _submit}}):
        watch, run, task = await _due(db, nid, monkeypatch)
    task.status = "failed"
    run.budget_json = {**run.budget_json, "requests": 6}
    key = run.request_json["change_key"]
    watch.dirty_json = {key: {**watch.dirty_json[key], "blocked": True}}
    await proactive._notice(
        db,
        nid,
        key=["failed-recheck"],
        title="检查未完成",
        summary="可重新检查",
        result_ref={"task_id": str(task.id)},
    )
    notice = await db.scalar(
        select(AssistantNotice).where(AssistantNotice.novel_id == UUID(nid))
    )
    first_id, second_id = uuid4(), uuid4()
    result = await proactive.recheck_notice(db, nid, notice.id, first_id)
    assert not result["replayed"] and watch.active_run_id is None
    assert not watch.dirty_json[key].get("blocked")
    assert run.budget_json["requests"] == 6 and run.status == "failed"
    assert (await proactive.recheck_notice(db, nid, notice.id, second_id))["replayed"]
    watch.dirty_json = {}
    assert (await proactive.recheck_notice(db, nid, notice.id, first_id))["replayed"]
    assert not watch.dirty_json
    await proactive.save_policy(db, nid, ProactivePolicy(enabled=False))
    with pytest.raises(ValidationError, match="关闭"):
        await proactive.recheck_notice(db, nid, notice.id, uuid4())


@pytest.mark.asyncio
async def test_changes_are_authorized_coalesced_transactional(
    db_session, test_project_id, enabled, monkeypatch
):
    db, nid, asset = db_session, test_project_id, str(uuid4())
    await proactive.mark_changed(db, nid, "writing_draft", asset)
    assert await db.scalar(select(func.count()).select_from(AssistantWatch)) == 0
    await proactive.save_policy(db, nid, ProactivePolicy(enabled=True))
    await db.commit()
    await proactive.mark_changed(db, nid, "writing_draft", asset)
    await db.rollback()
    row = await db.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == UUID(nid))
    )
    assert not row.dirty_json
    await proactive.mark_changed(db, nid, "writing_draft", asset)
    await proactive.mark_changed(db, nid, "writing_draft", asset)
    assert len(row.dirty_json) == 1
    with container_scope({"assistant.proactive.submitters": {"writing": _submit}}):
        assert await proactive.schedule_due(db) == 0
        row, run, task = await _due(db, nid, monkeypatch)
        assert await proactive.schedule_due(db) == 0
        await proactive.save_policy(db, nid, ProactivePolicy(enabled=False))
        await db.commit()
        called = False

        async def handler(**kwargs):
            nonlocal called
            called = True

        with pytest.raises(ValidationError, match="授权"):
            await proactive.execute_review_task(db, task, handler)
        assert not called


@pytest.mark.asyncio
async def test_preparation_failure_can_be_rechecked_without_a_child_task(
    db_session, test_project_id, enabled
):
    db, nid, asset = db_session, test_project_id, str(uuid4())
    await proactive.save_policy(db, nid, ProactivePolicy(enabled=True))
    await proactive.mark_changed(db, nid, "writing_draft", asset)
    watch = await db.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == UUID(nid))
    )
    key = f"writing_draft:{asset}"
    watch.dirty_json = {key: {**watch.dirty_json[key], "blocked": True}}
    await proactive._notice(
        db,
        nid,
        key=["prepare-failure"],
        title="未开始检查",
        summary="连接暂不可用",
        result_ref={"change_key": key},
    )
    notice = await db.scalar(
        select(AssistantNotice).where(AssistantNotice.novel_id == UUID(nid))
    )
    result = await proactive.recheck_notice(db, nid, notice.id, uuid4())
    assert not result["replayed"] and not watch.dirty_json[key].get("blocked")
    assert watch.active_run_id is None


@pytest.mark.asyncio
async def test_review_receipts_notices_snooze_and_no_domain_adoption(
    db_session, test_project_id, enabled, monkeypatch
):
    db, nid, asset = db_session, test_project_id, str(uuid4())
    await proactive.save_policy(db, nid, ProactivePolicy(enabled=True))
    await proactive.mark_changed(db, nid, "writing_draft", asset)
    with container_scope({"assistant.proactive.submitters": {"writing": _submit}}):
        _, run, task = await _due(db, nid, monkeypatch)

    async def handler(**kwargs):
        meter = current_workflow_budget()
        await meter.before_request()
        await meter.completed(
            LLMUsage(prompt_tokens=9, completion_tokens=4, total_tokens=13)
        )
        return {
            "findings": [
                {
                    "kind": "continuity",
                    "message": "这一处年龄值得核对",
                    "location": {"draft_id": asset, "excerpt": "十六岁"},
                }
            ]
        }

    with container_scope({"assistant.proactive.findings": {}}):
        result = await proactive.execute_review_task(db, task, handler)
    assert result["findings"][0]["location"]["excerpt"] == "十六岁"
    assert run.budget_json["requests"] == 1 and run.budget_json["prompt_tokens"] == 9
    task.status, task.result = "done", result
    await db.flush()
    notices = (await proactive.list_notices(db, nid))["items"]
    assert len(notices) == 1 and not notices[0]["needs_recheck"]
    notice_id = notices[0]["id"]
    await proactive.decide_notice(
        db,
        notice_id,
        NoticeDecision(
            novel_id=nid, action="snooze", until=proactive._now() + timedelta(days=1)
        ),
    )
    assert not (await proactive.list_notices(db, nid))["items"]
    await proactive.decide_notice(
        db, notice_id, NoticeDecision(novel_id=nid, action="intentional")
    )
    notice = await db.get(AssistantNotice, UUID(notice_id))
    assert notice.disposition == "intentional" and notice.status == "dismissed"
    assert result["findings"][0]["message"] == "这一处年龄值得核对"


@pytest.mark.asyncio
async def test_new_change_suppresses_old_notice_keeps_backlog(
    db_session, test_project_id, enabled, monkeypatch
):
    db, nid, asset = db_session, test_project_id, str(uuid4())
    await proactive.save_policy(db, nid, ProactivePolicy(enabled=True))
    await proactive.mark_changed(db, nid, "writing_draft", asset)
    with container_scope({"assistant.proactive.submitters": {"writing": _submit}}):
        watch, run, task = await _due(db, nid, monkeypatch)

    async def handler(**kwargs):
        await proactive.mark_changed(db, nid, "writing_draft", asset)
        return {"findings": [{"message": "旧稿问题"}]}

    with container_scope({"assistant.proactive.findings": {}}):
        await proactive.execute_review_task(db, task, handler)
    assert run.result_json["superseded"] is True
    assert watch.dirty_json and watch.active_run_id is None
    assert not (await proactive.list_notices(db, nid))["items"]


@pytest.mark.asyncio
@pytest.mark.parametrize("restriction", ["category", "excluded"])
async def test_narrowed_policy_drops_old_pending_changes(
    db_session, test_project_id, enabled, monkeypatch, restriction
):
    db, nid, asset = db_session, test_project_id, str(uuid4())
    await proactive.save_policy(db, nid, ProactivePolicy(enabled=True))
    await proactive.mark_changed(db, nid, "core_entity", asset)
    row = await db.scalar(select(AssistantWatch))
    old_dirty = dict(row.dirty_json)
    setting = ProactivePolicy(
        enabled=True,
        categories=["writing"] if restriction == "category" else ["world"],
        excluded_targets=[f"core_entity:{asset}"] if restriction == "excluded" else [],
    )
    await proactive.save_policy(db, nid, setting)
    assert not row.dirty_json
    # Also reject persisted markers from an older scheduler version at claim time.
    row.dirty_json = old_dirty
    clock = datetime.now(UTC) + timedelta(seconds=61)
    monkeypatch.setattr(proactive, "_now", lambda: clock)
    with container_scope({"assistant.proactive.submitters": {"world": _submit}}):
        assert await proactive.schedule_due(db) == 0
    assert not row.dirty_json
    assert await db.scalar(select(func.count()).select_from(AssistantRun)) == 0
