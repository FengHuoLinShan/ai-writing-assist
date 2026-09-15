"""W3-C：Assistant 业务通道的运行信封回归。

assistant_turn 的 canonical root/额度/deadline 声明契约，以及真实
AssistantService.execute 链路上 run_project_agent 的 root capability
归属与单账本语义（信封与 AgentRunBudget 各计一次，不双扣）。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from core.config import get_settings
from infrastructure.llm.agent_runtime import AGENT_STEP_NAME
from infrastructure.llm.schemas import LLMCallResponse, LLMToolCall, LLMUsage
from infrastructure.llm.workflow_budget import (
    AIRunEnvelope,
    new_ai_run_envelope,
)
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import get_registry
from modules.assistant import service as assistant_service
from modules.assistant.models import AssistantRun
from modules.assistant.service import AssistantService


def test_assistant_turn_declares_run_envelope_contract() -> None:
    """assistant_turn 声明 canonical root、静态 L0=30 与 Agent 30 分钟 deadline。"""
    import modules.assistant.tasks  # noqa: F401  注册副作用

    registry = get_registry()
    assert registry.get_root_capability("assistant_turn") == "assistant.turn"
    task = object()
    assert registry.resolve_run_request_limit("assistant_turn", task) == 30
    assert registry.resolve_run_deadline_seconds("assistant_turn", task) == 1800.0


class _NullLimiter:
    def run(self, call, *, limiter_scope=None):
        return call()

    @asynccontextmanager
    async def scope(self, *, limiter_scope=None):
        yield


class _ScriptedAnswerProvider:
    """provider 传输层替身；reserve/settle 由真实 LLMClient 单入口承担。"""

    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request) -> LLMCallResponse:
        self.calls += 1
        output = next(
            tool
            for tool in request.tools
            if "answer" in tool.parameters.get("properties", {})
        )
        return LLMCallResponse(
            tool_calls=[
                LLMToolCall(
                    id="final-1",
                    name=output.name,
                    arguments=(
                        '{"answer":"已准备明天的核对事项，请确认后加入待办。",'
                        '"actions":[{"key":"todo","capability":"project.add_task",'
                        '"title":"添加核对事项","arguments":{"title":"核对人物年龄"}}]}'
                    ),
                )
            ],
            usage=LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        )


def _scripted_client(monkeypatch: pytest.MonkeyPatch, provider) -> object:
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.limits import reset_llm_limiter_for_tests

    reset_llm_limiter_for_tests()
    client = LLMClient()
    client._provider = provider  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "infrastructure.llm.client.get_llm_limiter", lambda: _NullLimiter()
    )
    return client


async def test_assistant_turn_agent_declares_root_capability_and_single_ledger(
    async_client,
    db_session,
    test_project_id,
    account_llm_connection,
    monkeypatch,
) -> None:
    settings = replace(get_settings(), assistant_enabled=True)
    monkeypatch.setattr("modules.assistant.service.get_settings", lambda: settings)
    provider = _ScriptedAnswerProvider()
    monkeypatch.setattr(
        "modules.assistant.service.create_project_snapshot_llm_client",
        lambda *args, **kwargs: _scripted_client(monkeypatch, provider),
    )
    monkeypatch.setattr(db_session, "task_checkpoint_enabled", True, raising=False)

    response = await async_client.post(
        "/api/assistant/sessions", json={"novel_id": test_project_id}
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["id"]
    operation = str(uuid.uuid4())
    created = await async_client.post(
        f"/api/assistant/sessions/{session_id}/turns",
        json={
            "novel_id": test_project_id,
            "operation_id": operation,
            "message": "提醒我核对人物年龄",
            "allow_web": False,
        },
    )
    assert created.status_code == 202, created.text
    task = await db_session.get(AsyncTask, uuid.UUID(operation))
    assert task is not None
    task.status = "running"
    await db_session.flush()

    captured: list[str | None] = []
    real_run = assistant_service.run_project_agent

    async def spying_run(client, request, **kwargs):
        captured.append(kwargs.get("capability_id"))
        return await real_run(client, request, **kwargs)

    monkeypatch.setattr(assistant_service, "run_project_agent", spying_run)

    envelope = AIRunEnvelope(
        new_ai_run_envelope(
            operation_id=operation,
            run_id=operation,
            root_capability_id="assistant.turn",
            novel_id=test_project_id,
            request_limit=30,
            deadline_at=datetime.now(UTC) + timedelta(seconds=1800),
        ).snapshot()
    )

    from infrastructure.llm.workflow_budget import ai_run_scope

    with ai_run_scope(envelope):
        result = await AssistantService().execute(db_session, task)

    assert result["status"] == "waiting_approval"
    # 主 Agent 循环显式声明 run 的 root capability。
    assert captured == ["assistant.turn"]
    snapshot = envelope.snapshot()
    assert snapshot.requests_started == 1
    assert snapshot.requests_settled == 1
    assert [step.step_name for step in snapshot.steps] == [AGENT_STEP_NAME]
    assert snapshot.steps[0].step_capability_id == "assistant.turn"
    # 信封请求与领域 AgentRunBudget 恰好一致，不双扣。
    run = await db_session.get(AssistantRun, uuid.UUID(operation))
    assert run is not None
    assert (run.budget_json or {}).get("requests") == snapshot.requests_started
