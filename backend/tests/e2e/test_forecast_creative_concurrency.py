"""Independent PostgreSQL sessions, real domains and exactly-once confirmation."""

import asyncio
from dataclasses import replace
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.assistant.forecast import runtime, service
from modules.assistant.forecast.contracts import (
    DecisionRequest,
    EvaluateRequest,
    FeedRequest,
    FocusRequest,
)
from modules.assistant.forecast.models import ForecastCandidate
from modules.assistant.models import AssistantRun
from modules.collaboration import cases
from modules.collaboration.contracts import CaseCreate
from modules.collaboration.merge import merge_workspace
from modules.collaboration.models import CollaborationCase, CreativeMergeReceipt
from modules.collaboration.tests.test_workspaces import approve_trial, setup_trial
from modules.project.models import Project
from modules.writing.models import WritingDraft
from tests.e2e.config import DATABASE_URL


async def test_concurrent_case_forecast_merge_notice_and_project_cascade(monkeypatch):
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, project = uuid4(), uuid4()
    nid = str(project)
    principal = AccountPrincipal(
        account_id=owner,
        status="active",
        identity_type="email",
        support_code="creative-race-" + owner.hex[:12],
    )
    token = bind_principal(principal)
    settings = replace(
        get_settings(),
        assistant_enabled=True,
        collaboration_v2_enabled=True,
        assistant_forecast_enabled=True,
    )
    for module in (cases, runtime, service):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner, status="active", support_code=principal.support_code)
            )
            await db.flush()
            db.add(Project(id=project, owner_id=owner, title="Synthetic creative races"))
            await db.flush()
            case, trial, drafts, _ = await setup_trial(db, nid, monkeypatch, two=True)
            decision = await approve_trial(db, nid, case, trial)
            creation = CaseCreate(
                operation_id=uuid4(),
                goal="同一个提交只能建立一次",
                grant=case["grant"],
                recipe_id="deep_review",
            )

        async def create():
            async with sessions.begin() as db:
                return await cases.create_case(db, nid, creation)

        created = await asyncio.wait_for(asyncio.gather(create(), create()), 20)
        assert created[0]["id"] == created[1]["id"]

        async def merge():
            async with sessions.begin() as db:
                return await merge_workspace(db, nid, trial["id"], decision)

        merged = await asyncio.wait_for(asyncio.gather(merge(), merge()), 20)
        assert merged[0]["receipt_id"] == merged[1]["receipt_id"]
        assert sum(bool(value.get("replayed")) for value in merged) == 1

        focus = FocusRequest(client_context_id=uuid4(), focus_seq=1, page="account")
        data = EvaluateRequest(
            operation_id=uuid4(),
            context=focus,
            horizon={"unit": "decision"},
            requested_capabilities=["account.readiness.v1"],
        )

        async def submit():
            async with sessions.begin() as db:
                return await runtime.submit(db, nid, data)

        submitted = await asyncio.wait_for(asyncio.gather(submit(), submit()), 20)
        assert submitted[0].run_id == submitted[1].run_id
        async with sessions() as db:
            run = await db.get(AssistantRun, submitted[0].run_id)
            task = await db.get(AsyncTask, run.task_id)
            db.task_checkpoint_enabled = True
            await runtime.execute(db, task)
            feed = await service.feed(db, nid, FeedRequest(context=focus))
            candidate = feed.items[0]
            await db.commit()

        async def decide(action):
            async with sessions.begin() as db:
                return await service.decide(
                    db,
                    nid,
                    candidate.candidate_id,
                    DecisionRequest(
                        expected_notice_version=candidate.notice_version,
                        expected_assessment_hash=candidate.assessment_hash,
                        action=action,
                    ),
                )

        decisions = await asyncio.wait_for(
            asyncio.gather(
                decide("read"), decide("as_ordinary_detail"), return_exceptions=True
            ),
            20,
        )
        assert sum(isinstance(value, ConflictError) for value in decisions) == 1
        assert sum(not isinstance(value, Exception) for value in decisions) == 1
        async with sessions.begin() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(CreativeMergeReceipt)
                    .where(CreativeMergeReceipt.novel_id == project)
                )
                == 1
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(WritingDraft)
                    .where(WritingDraft.novel_id == project)
                )
                == 4
            )
            await db.execute(delete(Project).where(Project.id == project))
            for model in (ForecastCandidate, CollaborationCase, CreativeMergeReceipt):
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.novel_id == project)
                    )
                    == 0
                )
    finally:
        reset_principal(token)
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == project))
            await db.execute(delete(Account).where(Account.id == owner))
        await engine.dispose()
