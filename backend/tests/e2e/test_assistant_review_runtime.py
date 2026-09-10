"""An Agent invokes an existing read-only review under one budget and two leases."""

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMToolCall, LLMUsage
from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.account.settings_constants import ACCOUNT_LLM_PROVIDER_TEMPLATES
from modules.account.settings_models import AccountLLMCredential, GlobalLLMDefaults
from modules.assistant.models import AssistantActionBatch, AssistantRun
from modules.assistant.schemas import SessionCreate, TurnCreate, WorkContext
from modules.assistant.service import AssistantService
from modules.project.models import Project
from modules.writing.facade import create_draft_only, get_draft
from run_worker import _guard_active_task_project_finalize, _require_active_task_project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize(
    "cancel_review,world_review,cancel_via_tasks",
    [
        (False, False, False),
        (True, False, False),
        (True, False, True),
        (False, True, False),
    ],
)
async def test_agent_runs_read_only_review_without_confirmation_or_extra_budget(
    monkeypatch,
    cancel_review,
    world_review,
    cancel_via_tasks,
):
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, nid = uuid.uuid4(), uuid.uuid4()
    principal = AccountPrincipal(
        account_id=owner,
        status="active",
        identity_type="email",
        support_code="review-" + owner.hex[:15],
    )
    token = bind_principal(principal)
    settings = replace(get_settings(), assistant_enabled=True)
    monkeypatch.setattr("modules.assistant.service.get_settings", lambda: settings)
    service = AssistantService()
    model_calls = []
    review_started, release_review = asyncio.Event(), asyncio.Event()

    class ParentClient:
        model_name = "deepseek-v4-flash"
        calls = 0

        async def generate(self, request, *, transport_retries):
            assert not transport_retries
            self.calls += 1
            if self.calls == 1:
                call = LLMToolCall(
                    id="review",
                    name="review_world_constraints" if world_review else "review_assets",
                    arguments=json.dumps(
                        {"draft_ids": [draft_id]}
                        if world_review
                        else {
                            "capability": "writing.review",
                            "arguments": {"draft_ids": [draft_id]},
                        }
                    ),
                )
            else:
                receipt = json.loads(
                    next(
                        message.content
                        for message in reversed(request.messages)
                        if message.role == "tool"
                    )
                )
                assert receipt["review_result"]["status"] == "completed"
                output = next(
                    tool
                    for tool in request.tools
                    if "answer" in tool.parameters.get("properties", {})
                )
                call = LLMToolCall(
                    id="answer",
                    name=output.name,
                    arguments=json.dumps(
                        {
                            "answer": "已检查正文，没有材料证明人物知识边界。",
                            "evidence_ids": [receipt["evidence_id"]],
                            "omissions": ["未检查人物知识边界"],
                        },
                        ensure_ascii=False,
                    ),
                )
            return LLMCallResponse(
                tool_calls=[call],
                usage=LLMUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
            )

        async def close(self):
            pass

    parent = ParentClient()
    monkeypatch.setattr(
        "modules.assistant.service.create_project_snapshot_llm_client",
        lambda *args, **kw: parent,
    )

    async def review_provider(_provider, request):
        model_calls.append(request)
        if world_review:
            material = json.loads(request.messages[-1].content)
            context = material["targets"][0]["review_context"]
            assert context["review_mode"] == "world_constraints"
            assert "铜门只能从内侧打开" in str(context["world_evidence"])
            assert context["knowledge_boundary_checked"] is False
        review_started.set()
        if cancel_review:
            await asyncio.wait_for(release_review.wait(), timeout=15)
        result = {
            "findings": [],
            "not_checked": ["人物知识没有资料证明"],
            "coverage": [
                {
                    "draft_id": draft_id,
                    "scene_contract": "not_checked",
                    "timeline_location": "checked",
                    "identity_relation": "checked",
                    "ability_world_rule": "checked" if world_review else "not_checked",
                    "knowledge_boundary": "not_checked",
                }
            ],
        }
        return LLMCallResponse(
            content=json.dumps(result, ensure_ascii=False),
            usage=LLMUsage(prompt_tokens=20, completion_tokens=5, total_tokens=25),
        )

    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner, status="active", support_code=principal.support_code)
            )
            await db.flush()
            db.add(Project(id=nid, owner_id=owner, title="Synthetic inline review"))
            db.add(
                AccountLLMCredential(
                    owner_id=owner,
                    provider_id="deepseek",
                    encrypted_api_key=encrypt_secret("synthetic-inline-key"),
                    key_fingerprint=fingerprint_secret(
                        "synthetic-inline-key", purpose="account-llm-api-key"
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
            draft = await create_draft_only(
                db, str(nid), 1, "第一章", "他先查看窗外，再推开院门。"
            )
            draft_id = draft.id
            if world_review:
                from modules.world.facade import create_entity

                await create_entity(
                    db,
                    str(nid),
                    {
                        "name": "铜门规则",
                        "entity_type": "rule",
                        "status": "canonical",
                        "summary": "铜门只能从内侧打开。",
                        "importance": 1.0,
                    },
                )
            discussion = await service.create_session(db, SessionCreate(novel_id=nid))
            run = await service.submit(
                db,
                str(discussion.id),
                TurnCreate(
                    novel_id=nid,
                    operation_id=uuid.uuid4(),
                    message="检查当前正文",
                    context=WorkContext(draft_id=draft_id, chapter_index=1),
                    allow_web=False,
                ),
                str(owner),
            )
            run_id = run["id"]
        worker = TaskWorker(
            db_manager=SimpleNamespace(engine=engine, session_factory=sessions),
            task_preflight=_require_active_task_project,
            task_commit_guard=_guard_active_task_project_finalize,
            heartbeat_interval=60,
        )
        with patch.object(
            OpenAIProvider, "generate", autospec=True, side_effect=review_provider
        ):
            runner = asyncio.create_task(
                worker.run_once(task_id=run_id, novel_id=str(nid))
            )
            if cancel_review:
                from modules.assistant.api import stop_run

                await asyncio.wait_for(review_started.wait(), timeout=15)
                async with sessions.begin() as db:
                    stored = await db.get(AssistantRun, uuid.UUID(run_id))
                    stored.checkpoint_json = {"evidence_refs": {}}
                    await db.flush()
                    if cancel_via_tasks:
                        from infrastructure.tasks.api import cancel_task

                        response = await cancel_task(
                            uuid.UUID(run_id), db=db, novel_id=str(nid)
                        )
                        assert response.cancelled
                    else:
                        await stop_run(db, uuid.UUID(run_id), nid)
                release_review.set()
            finished = await asyncio.wait_for(runner, timeout=15)
        if cancel_review:
            assert finished.status == "cancelled"
            async with sessions() as db:
                if cancel_via_tasks:
                    await AssistantService().get_run(db, str(nid), run_id)
                stored = await db.get(AssistantRun, uuid.UUID(run_id))
                child = await db.scalar(
                    select(AsyncTask).where(
                        AsyncTask.novel_id == nid,
                        AsyncTask.task_type == "writing_semantic_review",
                    )
                )
                assert stored.status == child.status == "cancelled"
                assert stored.budget_json["requests"] == 2
                assert stored.budget_json["pending_usage"] >= 1
                assert parent.calls == 1
                assert (
                    await get_draft(db, str(nid), draft_id)
                ).content == "他先查看窗外，再推开院门。"
            return
        assert finished.status == "done", finished.error_message
        async with sessions() as db:
            stored = await db.get(AssistantRun, uuid.UUID(run_id))
            assert stored.status == "completed", stored.error
            assert stored.budget_json["requests"] == 3
            assert len(model_calls) == 1 and parent.calls == 2
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AssistantActionBatch)
                    .where(AssistantActionBatch.novel_id == nid)
                )
                == 0
            )
            assert (
                await get_draft(db, str(nid), draft_id)
            ).content == "他先查看窗外，再推开院门。"
            child = await db.scalar(
                select(AsyncTask).where(
                    AsyncTask.novel_id == nid,
                    AsyncTask.task_type == "writing_semantic_review",
                )
            )
            assert child.status == "done" and child.meta["_parent_task_id"] == run_id
            if world_review:
                coverage = child.result["coverage"]["world_constraints"][draft_id]
                assert coverage["checked"] and coverage["sources"]
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
            await db.execute(delete(Account).where(Account.id == owner))
        reset_principal(token)
        await engine.dispose()
