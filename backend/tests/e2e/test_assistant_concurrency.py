"""Real PostgreSQL locks protect batch approval and incremental review ownership."""

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from core.container import container_scope
from infrastructure.tasks.facade import enqueue_task
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.assistant import proactive
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.evidence_tools import fingerprint
from modules.assistant.models import AssistantActionBatch, AssistantRun, AssistantWatch
from modules.assistant.operations import decide_batch, prepare_actions
from modules.assistant.schemas import (
    BatchDecision,
    ProactivePolicy,
    ProposedAction,
    WorkContext,
)
from modules.project.models import Project, ProjectAuthorTask
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_concurrent_approval_and_background_claim_are_exactly_once(monkeypatch):
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, nid = uuid.uuid4(), uuid.uuid4()
    principal = AccountPrincipal(
        account_id=owner,
        status="active",
        identity_type="email",
        support_code="agent-" + owner.hex[:16],
    )
    token = bind_principal(principal)
    settings = replace(get_settings(), assistant_enabled=True)
    monkeypatch.setattr(proactive, "get_settings", lambda: settings)
    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner, status="active", support_code=principal.support_code)
            )
            await db.flush()
            db.add(Project(id=nid, owner_id=owner, title="Synthetic Agent concurrency"))
            await db.flush()
            run = AssistantRun(
                novel_id=nid,
                owner_id=owner,
                request_hash="a" * 64,
                status="waiting_approval",
            )
            db.add(run)
            await db.flush()
            actions = await prepare_actions(
                db,
                str(nid),
                [
                    ProposedAction(
                        key="todo",
                        capability="project.add_task",
                        title="核对日期",
                        arguments={"title": "核对日期"},
                    )
                ],
                context=AssistantOperationContext(str(run.id), str(owner), WorkContext()),
            )
            batch = AssistantActionBatch(
                novel_id=nid,
                run_id=run.id,
                fingerprint=fingerprint(actions),
                actions_json=actions,
            )
            db.add(batch)
            await db.flush()
            batch_id = str(batch.id)
            decision = BatchDecision(
                novel_id=nid,
                fingerprint=batch.fingerprint,
                selected=["todo"],
                confirmed=True,
            )
            await proactive.save_policy(db, str(nid), ProactivePolicy(enabled=True))

        async def approve():
            async with sessions.begin() as db:
                return await decide_batch(db, batch_id, decision, str(owner))

        replies = await asyncio.wait_for(asyncio.gather(approve(), approve()), timeout=15)
        assert all(reply["status"] == "completed" for reply in replies)
        async with sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(ProjectAuthorTask)
                    .where(ProjectAuthorTask.novel_id == nid)
                )
                == 1
            )

        async def changed(asset_id):
            async with sessions.begin() as db:
                await proactive.mark_changed(db, str(nid), "writing_draft", asset_id)

        await asyncio.wait_for(
            asyncio.gather(changed(str(uuid.uuid4())), changed(str(uuid.uuid4()))),
            timeout=15,
        )
        async with sessions() as db:
            watch = await db.scalar(
                select(AssistantWatch).where(AssistantWatch.novel_id == nid)
            )
            assert len(watch.dirty_json) == 2
        now = datetime.now(UTC) + timedelta(seconds=61)
        monkeypatch.setattr(proactive, "_now", lambda: now)

        async def submit(db, novel_id, change, meta):
            task_id = enqueue_task(
                db, "writing_semantic_review", novel_id=novel_id, meta=meta
            )
            await db.flush()
            return {
                "task_id": task_id,
                "target": {"type": change["asset_type"], "id": change["asset_id"]},
            }

        async def claim():
            async with sessions.begin() as db:
                return await proactive.schedule_due(db)

        with container_scope({"assistant.proactive.submitters": {"writing": submit}}):
            claims = await asyncio.wait_for(asyncio.gather(claim(), claim()), timeout=15)
        assert sum(claims) == 1
        async with sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AssistantRun)
                    .where(
                        AssistantRun.novel_id == nid, AssistantRun.mode == "background"
                    )
                )
                == 1
            )
            background = await db.scalar(
                select(AssistantRun).where(
                    AssistantRun.novel_id == nid, AssistantRun.mode == "background"
                )
            )
            background_id, task_id = background.id, background.task_id

        # Exercise real fenced worker sessions with a synthetic domain handler;
        # this verifies persistence/restart, not model or Writing review quality.
        from types import SimpleNamespace

        from infrastructure.llm.schemas import LLMUsage
        from infrastructure.llm.workflow_budget import current_workflow_budget
        from infrastructure.tasks.registry import TaskRegistry
        from infrastructure.tasks.worker import TaskWorker
        from modules.assistant.models import AssistantNotice
        from run_worker import (
            _guard_active_task_project_finalize,
            _require_active_task_project,
        )

        calls = 0

        async def review_handler(db, task):
            nonlocal calls
            meter = current_workflow_budget()
            await meter.before_request()
            calls += 1
            if calls == 1:
                raise RuntimeError(
                    "synthetic worker interruption after request reservation"
                )
            assert meter.budget.requests == 2
            await meter.completed(
                LLMUsage(prompt_tokens=9, completion_tokens=4, total_tokens=13)
            )
            return {
                "findings": [
                    {
                        "kind": "continuity",
                        "message": "这处变化需要核对",
                        "location": {"excerpt": "合成检查依据"},
                    }
                ]
            }

        monkeypatch.setitem(
            TaskRegistry()._handlers, "writing_semantic_review", review_handler
        )

        def fresh_worker():
            return TaskWorker(
                db_manager=SimpleNamespace(engine=engine, session_factory=sessions),
                heartbeat_interval=60,
                task_preflight=_require_active_task_project,
                task_commit_guard=_guard_active_task_project_finalize,
                execution_wrapper=proactive.execute_review_task,
            )

        first = await fresh_worker().run_once(task_id=task_id, novel_id=nid)
        assert first.status == "pending"  # Existing bounded Writing auto_requeue policy.
        async with sessions.begin() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AssistantNotice)
                    .where(AssistantNotice.novel_id == nid)
                )
                == 0
            )
        await asyncio.sleep(1.1)  # The existing first retry has a one-second backoff.
        second = await fresh_worker().run_once(task_id=task_id, novel_id=nid)
        assert second.status == "done", second.error_message
        async with sessions() as db:
            background = await db.get(AssistantRun, background_id)
            assert background.status == "completed"
            assert background.budget_json["requests"] == 2
            assert background.budget_json["usage_complete"] is False
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AssistantNotice)
                    .where(AssistantNotice.novel_id == nid)
                )
                == 1
            )
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
            await db.execute(delete(Account).where(Account.id == owner))
        reset_principal(token)
        await engine.dispose()
