"""Goal HTTP capability scope is bound to the current author project."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy import func, select

from app.main import app
from core.config import get_settings
from core.database import get_manager
from infrastructure.llm.schemas import AIRequestOutcome, LLMUsage
from infrastructure.llm.token_estimation import estimate_token_count
from infrastructure.llm.workflow_budget import (
    current_ai_run_envelope,
    current_workflow_budget,
)
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID, AccountPrincipal
from modules.account.models import Account
from modules.assistant.goal_runs import service
from modules.assistant.goal_runs.contracts import GoalOperationSelection, GoalPlan
from modules.assistant.models import AssistantRun
from modules.assistant.tests.test_goal_runs import _offline_snapshot, _PlanningClient
from modules.project.models import Project
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_goal_http_default_off_owner_recycled_and_demo_do_not_write(monkeypatch):
    manager = get_manager()
    own, foreign, recycled, other_owner = (uuid4() for _ in range(4))
    async with manager.session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code=uuid4().hex))
        db.add(Account(id=other_owner, support_code=uuid4().hex))
        db.add_all(
            [
                Project(id=own, owner_id=BOOTSTRAP_ACCOUNT_ID, title="Goal own"),
                Project(id=foreign, owner_id=other_owner, title="Goal foreign"),
                Project(
                    id=recycled,
                    owner_id=BOOTSTRAP_ACCOUNT_ID,
                    title="Goal recycled",
                    deleted_at=datetime.now(UTC),
                ),
            ]
        )
        await db.commit()

    initial_settings = replace(
        get_settings(),
        assistant_enabled=True,
        assistant_goal_runs_enabled=False,
        assistant_goal_runs_project_allowlist=(str(own), str(foreign), str(recycled)),
    )
    monkeypatch.setattr(service, "get_settings", lambda: initial_settings)
    async with XhrAsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        disabled = await client.get(
            "/api/assistant/goals/capabilities", params={"novel_id": str(own)}
        )
        assert disabled.status_code == 200 and disabled.json() == {"enabled": False}
        denied_start = await client.post(
            "/api/assistant/goals",
            json={
                "novel_id": str(own),
                "request_id": str(uuid4()),
                "goal": "核对合成项目",
                "budget": {
                    "requests": 4,
                    "possible_charge_requests": 4,
                    "tokens": 4096,
                    "time_limit_seconds": 600,
                },
            },
        )
        assert denied_start.status_code == 404

        enabled_settings = replace(initial_settings, assistant_goal_runs_enabled=True)
        monkeypatch.setattr(service, "get_settings", lambda: enabled_settings)
        allowed = await client.get(
            "/api/assistant/goals/capabilities", params={"novel_id": str(own)}
        )
        assert allowed.status_code == 200 and allowed.json()["enabled"] is True
        unavailable = allowed.json()["unavailable_operations"]
        assert any(item["operation_id"] == "story.plan_structure" for item in unavailable)
        for project_id in (foreign, recycled):
            hidden = await client.get(
                "/api/assistant/goals/capabilities",
                params={"novel_id": str(project_id)},
            )
            assert hidden.status_code == 200 and hidden.json() == {"enabled": False}
            run_path = f"/api/assistant/goals/{uuid4()}"
            budget = {
                "requests": 4,
                "possible_charge_requests": 4,
                "tokens": 4096,
                "time_limit_seconds": 600,
            }
            requests = [
                ("GET", "/api/assistant/goals/active", None),
                ("GET", "/api/assistant/goals/recent", None),
                ("GET", run_path, None),
                (
                    "POST",
                    "/api/assistant/goals",
                    {
                        "novel_id": str(project_id),
                        "request_id": str(uuid4()),
                        "goal": "不可访问的项目",
                        "budget": budget,
                    },
                ),
                (
                    "POST",
                    f"{run_path}/approve",
                    {
                        "expected_revision": 1,
                        "plan": {
                            "title": "只读计划",
                            "steps": [
                                {
                                    "step_id": "read",
                                    "operation_id": "evidence.project.search",
                                    "parameters": {"query": "资料"},
                                    "intent": "核对资料",
                                }
                            ],
                        },
                        "budget": budget,
                    },
                ),
                (
                    "POST",
                    f"{run_path}/steps/read/approve",
                    {"expected_revision": 1, "step_id": "read", "approve": True},
                ),
                (
                    "POST",
                    f"{run_path}/resume",
                    {"expected_revision": 1, "budget": budget},
                ),
                (
                    "POST",
                    f"{run_path}/replan",
                    {"expected_revision": 1, "reason": "缩小范围"},
                ),
                *(
                    ("POST", f"{run_path}/{action}", {"expected_revision": 1})
                    for action in ("advance", "pause", "cancel", "restore")
                ),
            ]
            for method, path, body in requests:
                query = (
                    {"novel_id": str(project_id)}
                    if path != "/api/assistant/goals"
                    else None
                )
                response = await client.request(
                    method,
                    path,
                    params=query,
                    json=body,
                )
                assert response.status_code == 404, (method, path, response.text)

        principal = AccountPrincipal(
            account_id=BOOTSTRAP_ACCOUNT_ID,
            status="active",
            identity_type="email",
            support_code="goal-demo-synthetic",
            access_scope="demo_readonly",
            demo_project_id=own,
        )
        token = bind_principal(principal)
        try:
            demo = await client.get(
                "/api/assistant/goals/capabilities", params={"novel_id": str(own)}
            )
            assert demo.status_code == 200 and demo.json() == {"enabled": False}
            demo_run = await client.get(
                "/api/assistant/goals/recent", params={"novel_id": str(own)}
            )
            assert demo_run.status_code == 404
        finally:
            reset_principal(token)

    async with manager.session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AssistantRun)
                .where(AssistantRun.novel_id.in_((own, foreign, recycled)))
            )
            == 0
        )


async def test_goal_http_plan_receives_only_executable_catalog(monkeypatch):
    manager = get_manager()
    novel_id = uuid4()
    async with manager.session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code=uuid4().hex))
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="Goal plan"))
        await db.commit()

    settings = replace(
        get_settings(),
        assistant_enabled=True,
        assistant_goal_runs_enabled=True,
        assistant_goal_runs_project_allowlist=(str(novel_id),),
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)

    async def snapshot(*_args, **_kwargs):
        return {
            **_offline_snapshot(),
            "profile": {"model": "gpt-6-luna", "max_tokens": 8192},
        }

    async def trace_disabled(*_args, **_kwargs):
        return False

    plan = GoalPlan.model_validate(
        {
            "title": "核对项目资料",
            "steps": [
                {
                    "step_id": "search",
                    "operation_id": "evidence.project.search",
                    "parameters": {"query": "合成资料"},
                    "intent": "核对当前项目",
                }
            ],
        }
    )
    requests = []

    class CapturingPlanner(_PlanningClient):
        async def generate_structured(self, request, response_schema, **kwargs):
            del kwargs
            requests.append(request)
            envelope = current_ai_run_envelope()
            workflow = current_workflow_budget()
            assert envelope is not None and workflow is not None
            reservation = await envelope.reserve()
            try:
                await workflow.before_request()
            except BaseException:
                await envelope.discard(reservation)
                raise
            prompt_tokens = sum(
                estimate_token_count(message.content, model="gpt-4o")
                for message in request.messages
            )
            usage = LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=80,
                total_tokens=prompt_tokens + 80,
            )
            await envelope.settle(
                reservation, usage=usage, outcome=AIRequestOutcome.succeeded
            )
            await workflow.completed(usage)
            if response_schema is GoalOperationSelection:
                return GoalOperationSelection(operation_ids=["evidence.project.search"])
            return plan

    @asynccontextmanager
    async def offline_client(*_args, **_kwargs):
        yield CapturingPlanner(plan)

    monkeypatch.setattr(service, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(service, "_trace_enabled", trace_disabled)
    monkeypatch.setattr(service, "open_project_snapshot_llm_client", offline_client)

    async with XhrAsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        started = await client.post(
            "/api/assistant/goals",
            json={
                "novel_id": str(novel_id),
                "request_id": str(uuid4()),
                "goal": "核对合成资料",
                "budget": {
                    "requests": 4,
                    "possible_charge_requests": 4,
                    "tokens": 12000,
                    "time_limit_seconds": 600,
                },
            },
        )
        assert started.status_code == 200, started.text
        assert started.json()["phase"] == "plan_review"
        assert started.json()["budget"]["used"]["requests"] == 2
        assert started.json()["budget"]["used"]["tokens"] > 1_000
        read_back = await client.get(
            f"/api/assistant/goals/{started.json()['run_id']}",
            params={"novel_id": str(novel_id)},
        )
        assert read_back.status_code == 200
        assert read_back.json()["run_id"] == started.json()["run_id"]

    assert len(requests) == 2
    selection_prompt = json.loads(requests[0].messages[1].content)
    assert "story.plan_structure" not in {
        item["id"] for item in selection_prompt["catalog"]
    }
    prompt = json.loads(requests[1].messages[1].content)
    offered = {item["operation_id"] for item in prompt["catalog"]}
    assert "evidence.project.search" in offered
    assert "story.character_card.generate" not in offered
    assert "story.plan_structure" not in offered
    assert all("parameter_schema" in item for item in prompt["catalog"])
    assert len(selection_prompt["catalog"]) > len(prompt["catalog"])
