"""真实 worker 租约与提交故障；模型输出使用合成替身。"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import get_settings
from infrastructure.tasks import facade as tasks
from infrastructure.tasks.models import AsyncTask
from modules.assistant.guided_flow import direction_cards, runtime
from modules.assistant.models import AssistantRun
from modules.assistant.tasks import handle_direction_cards  # noqa: F401
from modules.assistant.tests.test_guided_flow import _cards_payload
from modules.project.models import Project
from modules.writing.tests.test_writing_generate_recovery import _worker


@pytest.mark.parametrize("frozen_state", ["valid", "stale", "before_freeze"])
async def test_direction_task_reuses_paid_checkpoint_after_finalize_crash(
    test_engine, monkeypatch, frozen_state
):
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    nid, run_id, task_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: replace(
            get_settings(), assistant_enabled=True, assistant_guided_flows_enabled=True
        ),
    )
    paid = []

    async def generate(db, novel_id, **kwargs):
        paid.append(kwargs)
        assert not db.in_transaction()
        return _cards_payload()

    monkeypatch.setattr(direction_cards, "draft_direction_cards", generate)
    original = tasks.write_private_task_checkpoint
    checkpoints = []

    async def crash_after_freeze(db, **kwargs):
        if kwargs["key"] == "_guided_direction_cards_started_v1":
            return await original(db, **kwargs)
        checkpoints.append(kwargs)
        if frozen_state != "before_freeze":
            await original(db, **kwargs)
        raise RuntimeError("simulated checkpoint/finalize failure after paid response")

    monkeypatch.setattr(tasks, "write_private_task_checkpoint", crash_after_freeze)
    try:
        async with sessions.begin() as db:
            project = Project(id=nid, title="方向卡恢复合成作品")
            db.add(project)
            await db.flush()
            db.add(
                AssistantRun(
                    id=run_id,
                    novel_id=nid,
                    owner_id=project.owner_id,
                    mode="author",
                    status="running",
                    request_hash="a" * 64,
                    request_json={
                        "protocol": runtime.PROTOCOL,
                        "flow_id": "new_book_opening",
                        "flow_version": 1,
                    },
                    checkpoint_json={},
                    budget_json={},
                    result_json={},
                )
            )
            db.add(
                AsyncTask(
                    id=task_id,
                    novel_id=nid,
                    task_type="assistant_direction_cards",
                    max_attempts=2,
                    recovery_policy="auto_requeue",
                    meta={
                        "run_id": str(run_id),
                        "owner_id": str(project.owner_id),
                        "input_fingerprint": "a" * 64,
                        "batch": 1,
                        "input": {"vision": "潮城"},
                        "llm_execution_snapshot": {"version": 1},
                    },
                )
            )
        worker = _worker(sessions)
        first = await worker.run_once()
        assert first.id == task_id
        async with sessions.begin() as db:
            task = await db.get(AsyncTask, task_id)
            assert task.status == "pending"
            assert task.meta["_guided_direction_cards_started_v1"]
            if frozen_state != "before_freeze":
                assert task.meta["_guided_direction_cards_v1"]["cards"]
            if frozen_state == "stale":
                task.meta = {
                    **task.meta,
                    "_guided_direction_cards_v1": {
                        **task.meta["_guided_direction_cards_v1"],
                        "input_fingerprint": "b" * 64,
                    },
                }
            task.updated_at = datetime.now(UTC) - timedelta(seconds=5)
        second = await worker.run_once()
        assert second.id == task_id
        async with sessions() as db:
            task = await db.get(AsyncTask, task_id)
            assert task.status == ("done" if frozen_state == "valid" else "failed")
            if frozen_state == "valid":
                assert len(task.result["cards"]) == 2
        assert len(paid) == 1 and len(checkpoints) == 1
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(AssistantRun).where(AssistantRun.id == run_id))
            await db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            await db.execute(delete(Project).where(Project.id == nid))
