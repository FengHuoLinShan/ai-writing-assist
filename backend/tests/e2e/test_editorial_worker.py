"""Editorial review on a real PostgreSQL worker lease and concurrent decisions."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.assistant import editorial
from modules.assistant.editorial_contracts import IssueDecision, ReviewPass, ReviewSubmit
from modules.assistant.editorial_models import EditorialIssue, EditorialReview
from modules.project.models import Project
from modules.writing.facade import create_draft_only
from modules.writing.models import WritingDraft
from run_worker import _guard_active_task_project_finalize, _require_active_task_project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_worker_publishes_verified_advice_and_pg_decision_cas(monkeypatch):
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, novel_id = uuid4(), uuid4()
    token = bind_principal(
        AccountPrincipal(
            account_id=owner,
            status="active",
            identity_type="email",
            support_code="editorial-" + owner.hex[:12],
        )
    )
    settings = replace(
        get_settings(), assistant_enabled=True, assistant_editorial_enabled=True
    )
    monkeypatch.setattr(editorial, "get_settings", lambda: settings)

    async def snapshot(_db, _novel_id):
        return {"test_snapshot": True}

    @asynccontextmanager
    async def client(_db, _novel_id, _snapshot):
        yield SimpleNamespace(model_name="synthetic")

    async def model(_client, _request, _schema, **_kwargs):
        return ReviewPass.model_validate(
            {
                "summary": "地址线索需要核对",
                "findings": [
                    {
                        "category": "copy",
                        "judgment": "地址的写法可能引起误解",
                        "reader_impact": "读者可能以为地点已确定",
                        "severity": "medium",
                        "evidence": [{"chapter_index": 1, "quote": "地址指向旧港"}],
                    }
                ],
            }
        )

    monkeypatch.setattr(editorial, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(editorial, "open_project_snapshot_llm_client", client)
    monkeypatch.setattr(editorial, "run_managed_structured", model)
    text = "信上的地址指向旧港。"
    try:
        async with sessions.begin() as db:
            db.add(
                Account(
                    id=owner, status="active", support_code="editorial-" + owner.hex[:12]
                )
            )
            await db.flush()
            db.add(
                Project(id=novel_id, owner_id=owner, title="Synthetic editorial worker")
            )
            await db.flush()
            draft = await create_draft_only(db, str(novel_id), 1, "第一章", text)
            result = await editorial.submit(
                db,
                ReviewSubmit(
                    novel_id=novel_id,
                    operation_id=uuid4(),
                    scope="chapter",
                    start_chapter=1,
                    expected_brief_version=0,
                    dimensions=["copy"],
                ),
            )
            draft_id, review_id, task_id = draft.id, result["id"], result["task_id"]
        worker = TaskWorker(
            db_manager=SimpleNamespace(engine=engine, session_factory=sessions),
            task_preflight=_require_active_task_project,
            task_commit_guard=_guard_active_task_project_finalize,
            heartbeat_interval=60,
        )
        finished = await worker.run_once(task_id=task_id, novel_id=str(novel_id))
        assert finished.status == "done"
        async with sessions() as db:
            review = await db.get(EditorialReview, review_id)
            issue = await db.scalar(
                select(EditorialIssue).where(EditorialIssue.novel_id == novel_id)
            )
            assert review.status == "completed" and issue is not None
            assert (
                review.report_json["top_findings"][0]["authority"]
                == "editorial_suggestion"
            )
            assert (await db.get(WritingDraft, draft_id)).content == text
            assert (await db.get(AsyncTask, task_id)).status == "done"
            issue_id = issue.id

        async def decide(label):
            async with sessions.begin() as db:
                return await editorial.decide_issue(
                    db,
                    issue_id,
                    IssueDecision(
                        novel_id=novel_id,
                        expected_version=0,
                        disposition=label,
                    ),
                )

        outcomes = await asyncio.gather(
            decide("prepare"), decide("later"), return_exceptions=True
        )
        assert sum(isinstance(item, ConflictError) for item in outcomes) == 1
        async with sessions() as db:
            issue = await db.get(EditorialIssue, issue_id)
            assert issue.row_version == 1 and len(issue.decision_json) == 1
    finally:
        reset_principal(token)
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
            await db.execute(delete(Account).where(Account.id == owner))
        await engine.dispose()
