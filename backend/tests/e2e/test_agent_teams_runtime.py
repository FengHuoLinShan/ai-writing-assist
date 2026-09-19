"""Real PostgreSQL/worker/leases with deterministic provider IO; no model spend."""

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from infrastructure.llm.errors import (
    LLMAuthError,
    LLMContentFilterError,
    LLMInvalidResponseError,
    LLMQuotaError,
    LLMRateLimitError,
)
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
from modules.assistant.models import AssistantRun
from modules.assistant.schemas import SessionCreate, WorkContext
from modules.assistant.service import AssistantService
from modules.assistant.teams.contracts import TeamRunCreate
from modules.project.models import Project
from modules.writing.facade import create_draft_only, get_draft
from run_worker import _guard_active_task_project_finalize, _require_active_task_project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize(
    "cancel,fatal,summary_failure,member_error",
    [
        (False, False, False, None),
        (True, False, False, None),
        (False, True, False, None),
        (False, False, True, None),
        (False, False, False, LLMInvalidResponseError),
        (False, False, False, LLMContentFilterError),
        (False, False, False, LLMAuthError),
        (False, False, False, LLMQuotaError),
        (False, False, False, LLMRateLimitError),
    ],
)
async def test_team_real_worker_domain_review_and_cancellation(
    monkeypatch, cancel, fatal, summary_failure, member_error
):
    engine = create_async_engine(DATABASE_URL, pool_size=8, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, nid = uuid.uuid4(), uuid.uuid4()
    principal = AccountPrincipal(
        account_id=owner,
        status="active",
        identity_type="email",
        support_code="team-" + owner.hex[:15],
    )
    token = bind_principal(principal)
    settings = replace(
        get_settings(), assistant_enabled=True, assistant_deep_review_enabled=True
    )
    monkeypatch.setattr("modules.assistant.service.get_settings", lambda: settings)
    service = AssistantService()
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def provider(_provider, request):
        calls.append(request)
        if fatal:
            raise RuntimeError("Synthetic external budget refusal")
        usage = LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        if request.tools:
            output = next(
                tool for tool in request.tools if tool.name.startswith("final_result")
            )
            if "summary" in output.parameters["properties"]:
                if member_error and "你的专项：事实与规则" in request.messages[0].content:
                    raise member_error("Synthetic member failure")
                assert "reports" not in request.messages[-1].content
                if cancel:
                    started.set()
                    await asyncio.wait_for(release.wait(), timeout=15)
                answer = {
                    "summary": "正文已经独立查读",
                    "checked_dimensions": ["正文承诺"],
                }
            else:
                if summary_failure:
                    from pydantic_ai.exceptions import UnexpectedModelBehavior

                    raise UnexpectedModelBehavior("Synthetic invalid summary")
                body = json.loads(request.messages[-1].content)
                reference = body["domain_review"]
                answer = {
                    "answer": "三个专项已独立核对，详细问题由正文审稿持有。",
                    "evidence_ids": [reference["evidence_id"]],
                }
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(
                        id=str(uuid.uuid4()),
                        name=output.name,
                        arguments=json.dumps(answer),
                    )
                ],
                usage=usage,
            )
        if "长篇小说语义审稿人" in request.messages[0].content:
            material = json.loads(request.messages[1].content)
            assert (
                material["targets"][0]["review_context"]["knowledge_boundary_checked"]
                is False
            )
            output = {
                "findings": [],
                "not_checked": [],
                "coverage": [
                    {
                        "draft_id": draft_id,
                        "scene_contract": "not_applicable",
                        "timeline_location": "checked",
                        "identity_relation": "checked",
                        "ability_world_rule": "checked",
                        "knowledge_boundary": "not_applicable",
                    }
                ],
            }
        else:
            output = {
                "verdict": "pass",
                "findings": [],
                "dimensions": [
                    {"dimension": dimension, "checked": True}
                    for dimension in (
                        "world_entities",
                        "world_rules",
                        "world_bible",
                        "prior_prose",
                        "outline",
                        "plot_threads",
                        "memory",
                    )
                ],
            }
        return LLMCallResponse(content=json.dumps(output), usage=usage)

    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner, status="active", support_code=principal.support_code)
            )
            await db.flush()
            db.add(Project(id=nid, owner_id=owner, title="Synthetic team review"))
            db.add(
                AccountLLMCredential(
                    owner_id=owner,
                    provider_id="deepseek",
                    encrypted_api_key=encrypt_secret("synthetic-team-key"),
                    key_fingerprint=fingerprint_secret(
                        "synthetic-team-key", purpose="account-llm-api-key"
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
                db, str(nid), 1, "第一章", "昨日他承诺守住大门。今日他仍守在门前。"
            )
            draft_id = draft.id
            discussion = await service.create_session(db, SessionCreate(novel_id=nid))
            run = await service.submit(
                db,
                str(discussion.id),
                TeamRunCreate(
                    novel_id=nid,
                    operation_id=uuid.uuid4(),
                    message="核对承诺",
                    context=WorkContext(
                        page="writing", draft_id=draft_id, chapter_index=1
                    ),
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
            OpenAIProvider, "generate", autospec=True, side_effect=provider
        ):
            execution = asyncio.create_task(
                worker.run_once(task_id=run_id, novel_id=str(nid))
            )
            if cancel:
                from modules.assistant.api import stop_run

                await asyncio.wait_for(started.wait(), timeout=15)
                async with sessions.begin() as db:
                    await stop_run(db, uuid.UUID(run_id), nid)
                release.set()
            finished = await asyncio.wait_for(execution, timeout=30)
        assert engine.pool.checkedout() == 0
        async with sessions() as db:
            view = await service.get_run(db, str(nid), run_id)
            stored = await db.get(AssistantRun, uuid.UUID(run_id))
            if fatal or member_error in (LLMAuthError, LLMQuotaError, LLMRateLimitError):
                assert finished.status == stored.status == "failed"
                assert not stored.result_json.get("actions")
            elif cancel:
                assert finished.status == stored.status == "cancelled"
                assert all(
                    item["status"] != "succeeded"
                    for item in view["result"]["collaboration"]["work_items"]
                )
                assert len(calls) <= 3
            else:
                assert finished.status == "done", (
                    finished.error_message,
                    stored.checkpoint_json.get("failure"),
                )
                assert stored.status == "completed"
                assert stored.result_json["actions"] == []
                assert stored.result_json["collaboration"]["completed_count"] == (
                    2 if member_error else 3
                )
                if member_error:
                    items = stored.checkpoint_json["collaboration_v1"]["items"]
                    assert {item["role"]: item["status"] for item in items} == {
                        "facts": "failed",
                        "characters": "succeeded",
                        "narrative": "succeeded",
                    }
                assert stored.result_json["collaboration"]["completion"] == "partial"
                assert stored.result_json["knowledge_review"]["status"] == (
                    "not_checked" if summary_failure else "passed"
                )
                assert (
                    len(calls)
                    == stored.budget_json["requests"]
                    == (5 if summary_failure else 6)
                )
                if summary_failure:
                    assert stored.checkpoint_json["collaboration_v1"][
                        "summary_unavailable"
                    ]
                    assert not stored.result_json.get("plans")
                child = await db.scalar(
                    select(AsyncTask).where(
                        AsyncTask.novel_id == nid,
                        AsyncTask.task_type == "writing_semantic_review",
                    )
                )
                assert child.status == "done" and child.meta["_parent_task_id"] == run_id
                assert view["result"]["collaboration"]["freshness"] == "fresh"
            assert (
                await get_draft(db, str(nid), draft_id)
            ).content == "昨日他承诺守住大门。今日他仍守在门前。"
            assert "members" not in json.dumps(view, default=str)
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == nid))
            await db.execute(delete(Account).where(Account.id == owner))
        reset_principal(token)
        await engine.dispose()
