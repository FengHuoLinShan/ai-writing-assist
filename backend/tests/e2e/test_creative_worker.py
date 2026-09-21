"""Actual worker leases and PostgreSQL; only provider transport is replaced."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from core.errors import ConflictError
from infrastructure.llm.errors import LLMTimeoutError
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.account.settings_constants import ACCOUNT_LLM_PROVIDER_TEMPLATES
from modules.account.settings_models import AccountLLMCredential, GlobalLLMDefaults
from modules.collaboration import cases, views
from modules.collaboration.contracts import RunCreate
from modules.collaboration.models import (
    CollaborationArtifact,
    CollaborationCase,
    CollaborationRun,
)
from modules.collaboration.tests.test_workspaces import setup_trial
from modules.project.models import Project
from modules.writing.facade import create_draft_only
from run_worker import _guard_active_task_project_finalize, _require_active_task_project
from tests.e2e.config import DATABASE_URL
from tests.support.creative_browser_provider import structured_reply


@pytest.mark.parametrize(
    "mode",
    [
        "complete",
        "cancel",
        "source_changed",
        "shutdown",
        "timeout",
        "unknown_usage",
        "partial_resume",
    ],
)
async def test_worker_fences_late_outputs_and_preserves_root_usage(monkeypatch, mode):
    engine = create_async_engine(DATABASE_URL, pool_size=6, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, nid = uuid4(), uuid4()
    principal = AccountPrincipal(
        account_id=owner,
        status="active",
        identity_type="email",
        support_code="creative-worker-" + owner.hex[:10],
    )
    token = bind_principal(principal)
    values = {
        "settings": replace(
            get_settings(), assistant_enabled=True, collaboration_v2_enabled=True
        )
    }
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def provider(self, request):
        calls.append(request)
        if mode == "timeout":
            raise LLMTimeoutError("Synthetic transport timeout")
        if len(calls) == 1 and mode in {"cancel", "source_changed", "shutdown"}:
            started.set()
            await asyncio.wait_for(release.wait(), 15)
        if mode == "partial_resume":
            from infrastructure.llm.schemas import LLMCallResponse, LLMUsage

            schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])[
                "title"
            ]
            if schema == "GraphDelta":
                payload = json.loads(
                    next(item.content for item in request.messages if item.role == "user")
                )
                revision = payload["expected_plan_revision"]
                return LLMCallResponse(
                    content=json.dumps(
                        {
                            "expected_plan_revision": revision,
                            "reason": "已冻结的原目标",
                            "finish": revision != 1,
                            "items": [
                                {
                                    "logical_key": "follow",
                                    "capability": "investigate",
                                    "question": "核对动机",
                                }
                            ]
                            if revision == 1
                            else [],
                        }
                    ),
                    usage=LLMUsage(
                        prompt_tokens=10, completion_tokens=5, total_tokens=15
                    ),
                    finish_reason="stop",
                )
        response = structured_reply(request)
        assert response is not None, "Unexpected provider call"
        if mode == "unknown_usage":
            response = response.model_copy(update={"usage": None})
        return response

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner, status="active", support_code=principal.support_code)
            )
            await db.flush()
            db.add(Project(id=nid, owner_id=owner, title="Synthetic worker rehearsal"))
            db.add(
                AccountLLMCredential(
                    owner_id=owner,
                    provider_id="deepseek",
                    encrypted_api_key=encrypt_secret("synthetic-creative-test"),
                    key_fingerprint=fingerprint_secret(
                        "synthetic-creative-test", purpose="account-llm-api-key"
                    ),
                    verified_at=datetime.now(UTC),
                )
            )
            db.add(
                GlobalLLMDefaults(
                    owner_id=owner, **ACCOUNT_LLM_PROVIDER_TEMPLATES["deepseek"]
                )
            )
            await db.flush()
            case, _, _, _ = await setup_trial(db, str(nid), monkeypatch)
            if mode == "partial_resume":
                from modules.collaboration.recipes import RECIPES

                owned = await db.get(CollaborationCase, UUID(case["id"]))
                owned.recipe_json = RECIPES["deep_review"].model_dump(mode="json")
            monkeypatch.setattr(cases, "get_settings", lambda: values["settings"])
            submitted = await cases.submit_run(
                db,
                str(nid),
                case["id"],
                RunCreate(operation_id=uuid4(), expected_goal_version=1),
            )
            run_id = submitted["run_id"]
        worker = TaskWorker(
            db_manager=SimpleNamespace(engine=engine, session_factory=sessions),
            task_preflight=_require_active_task_project,
            task_commit_guard=_guard_active_task_project_finalize,
            heartbeat_interval=60,
        )
        execution = asyncio.create_task(
            worker.run_once(task_id=submitted["task_id"], novel_id=str(nid))
        )
        if mode in {"cancel", "source_changed", "shutdown"}:
            await asyncio.wait_for(started.wait(), 15)
            async with sessions.begin() as db:
                if mode == "cancel":
                    await cases.stop_run(db, str(nid), run_id)
                elif mode == "source_changed":
                    await create_draft_only(db, str(nid), 1, "开场", "作者已经另作选择。")
                else:
                    values["settings"] = replace(
                        values["settings"], collaboration_v2_enabled=False
                    )
            release.set()
        await asyncio.wait_for(execution, 40)
        if mode == "partial_resume":
            async with sessions.begin() as db:
                assert (await views.run_view(db, str(nid), run_id))["can_resume"] is True
                prior_run = await db.get(CollaborationRun, UUID(run_id))
                spent = prior_run.budget_json["requests"]
                resumed = await cases.resume_run(db, str(nid), run_id)
                assert (
                    resumed["task_id"] == submitted["task_id"]
                    and prior_run.budget_json["requests"] == spent
                )
            await worker.run_once(task_id=submitted["task_id"], novel_id=str(nid))
        async with sessions() as db:
            run = await db.get(CollaborationRun, UUID(run_id))
            task = await db.get(AsyncTask, UUID(submitted["task_id"]))
            owner_case = await db.get(CollaborationCase, run.case_id)
            assert run.budget_json["requests"] == owner_case.requests_used >= 1
            artifacts = await db.scalar(
                select(func.count())
                .select_from(CollaborationArtifact)
                .where(CollaborationArtifact.run_id == run.id)
            )
            if mode == "partial_resume":
                assert task.status == "done" and run.status == "completed"
                assert (
                    run.budget_json["requests"]
                    == owner_case.requests_used
                    == len(calls)
                    == 5
                )
            elif mode in {"complete", "unknown_usage"}:
                assert (
                    task.status == "done" and run.status == "completed" and artifacts >= 6
                )
                assert len(calls) == owner_case.requests_used == 16
                assert run.budget_json["usage_complete"] is (mode == "complete")
            else:
                assert task.status in {"cancelled", "failed"} and artifacts == 0
                assert (await views.run_view(db, str(nid), run_id))["status"] in {
                    "failed",
                    "cancelled",
                }
                if mode == "timeout":
                    with pytest.raises(ConflictError, match="恢复资格"):
                        await cases.resume_run(db, str(nid), run_id)
    finally:
        release.set()
        reset_principal(token)
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
            await db.execute(delete(Account).where(Account.id == owner))
        await engine.dispose()
