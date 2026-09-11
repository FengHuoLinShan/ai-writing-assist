"""Author API chain and real PydanticAI orchestration over deterministic provider IO."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select

from core.config import get_settings
from infrastructure.llm import web_search
from infrastructure.llm.schemas import LLMCallResponse, LLMToolCall, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.assistant.models import AssistantActionBatch, AssistantRun
from modules.assistant.service import AssistantService
from modules.project.models import ProjectAuthorTask


async def _session(async_client, novel_id):
    response = await async_client.post(
        "/api/assistant/sessions", json={"novel_id": novel_id}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize(
    "allow_web,web_backend", [(True, "searxng-v1"), (False, "searxng-v1"), (True, None)]
)
async def test_partial_recheck_reuses_request_and_only_replans_remaining_actions(
    async_client,
    db_session,
    test_project_id,
    account_llm_connection,
    monkeypatch,
    allow_web,
    web_backend,
):
    from modules.account.facade import current_account_id

    monkeypatch.setattr(
        "modules.assistant.service.get_settings",
        lambda: replace(get_settings(), assistant_enabled=True),
    )
    monkeypatch.setattr(
        web_search,
        "get_settings",
        lambda: replace(get_settings(), web_search_url="http://search:8080"),
    )
    session_id = await _session(async_client, test_project_id)
    excluded = str(uuid.uuid4())
    run = AssistantRun(
        novel_id=uuid.UUID(test_project_id),
        owner_id=current_account_id(),
        session_id=uuid.UUID(session_id),
        request_hash="r" * 64,
        status="completed",
        request_json={
            "context": {"scope": "project", "excluded_targets": [excluded]},
            "allow_web": allow_web,
            **({"web_backend": web_backend} if web_backend else {}),
        },
        budget_json={"requests": 4, "web_requests": 2},
    )
    db_session.add(run)
    await db_session.flush()
    batch = AssistantActionBatch(
        novel_id=run.novel_id,
        run_id=run.id,
        status="partial",
        fingerprint="b" * 64,
        actions_json=[
            {
                "key": key,
                "title": title,
                "capability": "project.add_task",
                "arguments": {"title": title},
            }
            for key, title in [("done", "已完成勿重做"), ("pending", "仍需核对")]
        ],
        results_json=[
            {"key": "done", "status": "completed"},
            {"key": "pending", "status": "failed"},
        ],
        authorization_json={"selected": ["done", "pending"]},
    )
    db_session.add(batch)
    await db_session.commit()
    body = {"novel_id": test_project_id, "operation_id": str(uuid.uuid4())}
    for _ in range(2):
        response = await async_client.post(
            f"/api/assistant/batches/{batch.id}/recheck", json=body
        )
        assert response.status_code == 202, response.text
        assert response.json()["id"] == body["operation_id"]
    created = await db_session.get(AssistantRun, uuid.UUID(body["operation_id"]))
    assert created.request_json["context"]["excluded_targets"] == [excluded]
    assert created.request_json["allow_web"] is allow_web
    assert created.request_json["web_backend"] == web_backend
    assert created.request_json["web_search"] == (
        web_search.search_snapshot() if allow_web and web_backend else None
    )
    await db_session.refresh(run)
    assert run.budget_json == {"requests": 4, "web_requests": 2}
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AssistantRun)
            .where(AssistantRun.session_id == run.session_id)
        )
        == 2
    )
    assert "已完成勿重做" not in json.dumps(created.request_json, ensure_ascii=False)
    assert "仍需核对" in created.request_json["message"]
    assert created.budget_json["requests"] == 0
    assert batch.status == "partial"


class FakeClient:
    model_name = "deepseek-v4-flash"

    async def generate(self, request, *, transport_retries):
        assert not transport_retries
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
                    arguments='{"answer":"已准备明天的核对事项，请确认后加入待办。","actions":[{"key":"todo","capability":"project.add_task","title":"添加核对事项","arguments":{"title":"核对人物年龄"}}]}',
                )
            ],
            usage=LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        )

    async def close(self):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_version", ["1", "2"])
async def test_author_turn_preview_confirm_and_replay(
    async_client,
    db_session,
    test_project_id,
    account_llm_connection,
    monkeypatch,
    runtime_version,
):
    settings = replace(get_settings(), assistant_enabled=True)
    monkeypatch.setattr("modules.assistant.service.get_settings", lambda: settings)
    monkeypatch.setattr(
        "modules.assistant.service.create_project_snapshot_llm_client",
        lambda *a, **kw: FakeClient(),
    )
    monkeypatch.setattr(db_session, "task_checkpoint_enabled", True, raising=False)
    capability = await async_client.get(
        "/api/assistant/capabilities", params={"novel_id": test_project_id}
    )
    assert capability.status_code == 200
    assert capability.json()["native_search"] == {
        "available": False,
        "canonical_model": "deepseek-flash",
        "reason": "联网暂不可用：当前连接未返回实际搜索记录与正式出处，"
        "不能采用为查证结果。",
    }
    session_id = await _session(async_client, test_project_id)
    operation = str(uuid.uuid4())
    body = {
        "novel_id": test_project_id,
        "operation_id": operation,
        "message": "提醒我核对人物年龄",
        "allow_web": False,
    }
    created = await async_client.post(
        f"/api/assistant/sessions/{session_id}/turns", json=body
    )
    assert created.status_code == 202, created.text
    again = await async_client.post(
        f"/api/assistant/sessions/{session_id}/turns", json=body
    )
    assert again.status_code == 202 and again.json()["id"] == operation
    changed = await async_client.post(
        f"/api/assistant/sessions/{session_id}/turns",
        json={**body, "message": "不同请求"},
    )
    assert changed.status_code == 409
    task = await db_session.get(AsyncTask, uuid.UUID(operation))
    assert task is not None
    from modules.assistant.operations import catalog, resolve_operations

    run = await db_session.get(AssistantRun, uuid.UUID(operation))
    if runtime_version == "1":
        frozen = json.loads(
            Path(__file__).parents[1].joinpath("runtime_v1.json").read_text()
        )
        run.request_json = {
            **run.request_json,
            "runtime_version": "1",
            "tools_hash": frozen["tools_hash"],
        }
    else:
        frozen = run.request_json
    monkeypatch.setitem(catalog(), "project.future_tool", catalog()["project.add_task"])
    assert "project.future_tool" not in resolve_operations(frozen["operations"])
    task.status = "running"
    await db_session.flush()
    result = await AssistantService().execute(db_session, task)
    assert result["status"] == "waiting_approval"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ProjectAuthorTask)
            .where(ProjectAuthorTask.novel_id == uuid.UUID(test_project_id))
        )
        == 0
    )
    view = await async_client.get(
        f"/api/assistant/runs/{operation}", params={"novel_id": test_project_id}
    )
    assert view.status_code == 200, view.text
    data = view.json()
    assert data["usage"]["requests"] == 1
    assert "checkpoint_json" not in data and "llm_snapshot" not in str(data)
    batch = data["result"]["batch"]
    event_response = await async_client.get(
        f"/api/assistant/runs/{operation}/events", params={"novel_id": test_project_id}
    )
    assert event_response.status_code == 200
    events = event_response.json()
    assert [item["sequence"] for item in events["events"]] == list(
        range(1, events["cursor"] + 1)
    )
    assert events["events"][-1]["phase"] == "waiting_approval"
    assert "model_history" not in str(events)
    repeated_events = await async_client.get(
        f"/api/assistant/runs/{operation}/events",
        params={"novel_id": test_project_id, "after": events["cursor"]},
    )
    assert repeated_events.json()["events"] == []
    decision = {
        "novel_id": test_project_id,
        "fingerprint": batch["fingerprint"],
        "selected": ["todo"],
        "confirmed": True,
    }
    for _ in range(2):
        approved = await async_client.post(
            f"/api/assistant/batches/{batch['id']}/decide", json=decision
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "completed"
    detail = await async_client.get(
        f"/api/assistant/sessions/{session_id}", params={"novel_id": test_project_id}
    )
    messages = detail.json()["messages"]
    assert all(message["assistant_run_id"] == operation for message in messages)
    assert messages[-1]["kind"] == "decision"
    assert messages[-1]["task_id"] == operation
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ProjectAuthorTask)
            .where(ProjectAuthorTask.novel_id == uuid.UUID(test_project_id))
        )
        == 1
    )


@pytest.mark.asyncio
async def test_sessions_preserve_legacy_identity_and_reject_cross_project(
    async_client, test_project_id
):
    legacy = await async_client.post(
        "/api/world/cocreation-sessions",
        json={
            "novel_id": test_project_id,
            "title": "旧讨论",
            "source": {"kind": "project"},
        },
    )
    assert legacy.status_code == 201
    session_id = legacy.json()["id"]
    current = await async_client.get(
        f"/api/assistant/sessions/{session_id}", params={"novel_id": test_project_id}
    )
    assert current.status_code == 200 and current.json()["session"]["id"] == session_id
    other = await async_client.post("/api/projects", json={"title": "另一作品"})
    denied = await async_client.get(
        f"/api/assistant/sessions/{session_id}", params={"novel_id": other.json()["id"]}
    )
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_submit_requires_connection_and_rejects_caller_authority(
    async_client, test_project_id, monkeypatch
):
    settings = replace(get_settings(), assistant_enabled=True)
    monkeypatch.setattr("modules.assistant.service.get_settings", lambda: settings)
    session_id = await _session(async_client, test_project_id)
    body = {
        "novel_id": test_project_id,
        "operation_id": str(uuid.uuid4()),
        "message": "查一下",
    }
    denied = await async_client.post(
        f"/api/assistant/sessions/{session_id}/turns",
        json={**body, "owner_id": str(uuid.uuid4())},
    )
    assert denied.status_code == 422
    missing = await async_client.post(
        f"/api/assistant/sessions/{session_id}/turns", json=body
    )
    assert missing.status_code in {400, 422}


@pytest.mark.asyncio
async def test_batch_invalid_selection_never_writes(
    async_client, db_session, test_project_id
):
    from modules.account.facade import current_account_id

    run = AssistantRun(
        novel_id=uuid.UUID(test_project_id),
        owner_id=current_account_id(),
        request_hash="a" * 64,
        status="waiting_approval",
    )
    db_session.add(run)
    await db_session.flush()
    batch = AssistantActionBatch(
        novel_id=run.novel_id, run_id=run.id, fingerprint="b" * 64, actions_json=[]
    )
    db_session.add(batch)
    await db_session.flush()
    response = await async_client.post(
        f"/api/assistant/batches/{batch.id}/decide",
        json={
            "novel_id": test_project_id,
            "fingerprint": "b" * 64,
            "selected": ["unknown"],
            "confirmed": True,
        },
    )
    assert response.status_code in {400, 422}
    assert not batch.authorization_json


@pytest.mark.parametrize(
    "allow_web,web_backend", [(True, "searxng-v1"), (False, "searxng-v1"), (True, None)]
)
async def test_renew_budget_preserves_search_consent_and_replay(
    async_client,
    db_session,
    test_project_id,
    account_llm_connection,
    monkeypatch,
    allow_web,
    web_backend,
):
    from modules.account.facade import current_account_id

    settings = replace(
        get_settings(), assistant_enabled=True, web_search_url="http://search:8080"
    )
    monkeypatch.setattr("modules.assistant.service.get_settings", lambda: settings)
    monkeypatch.setattr(web_search, "get_settings", lambda: settings)
    session_id = await _session(async_client, test_project_id)
    run = AssistantRun(
        novel_id=uuid.UUID(test_project_id),
        owner_id=current_account_id(),
        session_id=uuid.UUID(session_id),
        request_hash="r" * 64,
        status="budget_exceeded",
        budget_json={"requests": 12, "web_requests": 4},
        request_json={
            "message": "查证公开事实",
            "context": {},
            "allow_web": allow_web,
            **({"web_backend": web_backend} if web_backend else {}),
        },
    )
    db_session.add(run)
    await db_session.commit()
    body = {
        "novel_id": test_project_id,
        "operation_id": str(uuid.uuid4()),
        "renew_budget": True,
    }
    for _ in range(2):
        response = await async_client.post(
            f"/api/assistant/runs/{run.id}/resume", json=body
        )
        assert response.status_code == 202, response.text
        assert response.json()["id"] == body["operation_id"]
    created = await db_session.get(AssistantRun, uuid.UUID(body["operation_id"]))
    assert created.request_json["allow_web"] is allow_web
    assert created.request_json["web_backend"] == web_backend
    assert created.request_json["web_search"] == (
        web_search.search_snapshot() if allow_web and web_backend else None
    )
    assert created.budget_json["requests"] == 0
    await db_session.refresh(run)
    assert run.budget_json == {"requests": 12, "web_requests": 4}
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AssistantRun)
            .where(AssistantRun.session_id == run.session_id)
        )
        == 2
    )


async def test_resume_expired_budget_returns_conflict(
    async_client,
    db_session,
    test_project_id,
):
    from modules.account.facade import current_account_id

    task = AsyncTask(
        task_type="assistant_turn",
        novel_id=uuid.UUID(test_project_id),
        status="failed",
        recovery_policy="manual_resume",
        meta={"novel_id": test_project_id, "recovery_required": True},
        result={"recovery_required": True},
    )
    db_session.add(task)
    await db_session.flush()
    run = AssistantRun(
        novel_id=uuid.UUID(test_project_id),
        owner_id=current_account_id(),
        task_id=task.id,
        request_hash="e" * 64,
        status="failed",
        budget_json={"started_at": "2020-01-01T00:00:00Z"},
    )
    db_session.add(run)
    await db_session.commit()

    detail = await async_client.get(
        f"/api/assistant/runs/{run.id}", params={"novel_id": test_project_id}
    )
    response = await async_client.post(
        f"/api/assistant/runs/{run.id}/resume",
        json={"novel_id": test_project_id},
    )

    assert detail.json()["can_resume"] is False
    assert response.status_code == 409
    assert response.json()["error"] == "assistant_new_budget_required"


async def test_resume_missing_task_returns_not_found(
    async_client,
    db_session,
    test_project_id,
    monkeypatch,
):
    from modules.account.facade import current_account_id

    task = AsyncTask(
        task_type="assistant_turn",
        novel_id=uuid.UUID(test_project_id),
        status="failed",
        recovery_policy="manual_resume",
        meta={"novel_id": test_project_id, "recovery_required": True},
        result={"recovery_required": True},
    )
    db_session.add(task)
    await db_session.flush()
    run = AssistantRun(
        novel_id=uuid.UUID(test_project_id),
        owner_id=current_account_id(),
        task_id=task.id,
        request_hash="m" * 64,
        status="failed",
        budget_json={},
    )
    db_session.add(run)
    await db_session.commit()

    async def missing(*_args, **_kwargs):
        raise ValueError("task not found")

    monkeypatch.setattr("modules.assistant.service.resume_manual_task", missing)
    detail = await async_client.get(
        f"/api/assistant/runs/{run.id}", params={"novel_id": test_project_id}
    )
    response = await async_client.post(
        f"/api/assistant/runs/{run.id}/resume",
        json={"novel_id": test_project_id},
    )

    assert detail.json()["can_resume"] is True
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


@pytest.mark.parametrize("scope", ["project", "chapter", "excluded", "confirmed"])
async def test_legacy_history_reaches_model_only_within_authorized_scope(
    async_client, db_session, test_project_id, account_llm_connection, monkeypatch, scope
):
    from modules.assistant.session_models import AssistantMessage

    settings = replace(get_settings(), assistant_enabled=True)
    monkeypatch.setattr("modules.assistant.service.get_settings", lambda: settings)
    seen = []

    class HistoryClient(FakeClient):
        async def generate(self, request, *, transport_retries):
            seen.extend(message.content for message in request.messages)
            response = await super().generate(
                request, transport_retries=transport_retries
            )
            response.tool_calls[0].arguments = '{"answer":"已读取本次允许的讨论"}'
            return response

    monkeypatch.setattr(
        "modules.assistant.service.create_project_snapshot_llm_client",
        lambda *a, **kw: HistoryClient(),
    )
    monkeypatch.setattr(db_session, "task_checkpoint_enabled", True, raising=False)
    session_id = await _session(async_client, test_project_id)
    other = await async_client.post("/api/projects", json={"title": "另一作品"})
    other_id = other.json()["id"]
    other_session = await _session(async_client, other_id)
    context = {"scope": "project"}
    confirmation_id = None
    if scope == "chapter":
        context = {"scope": "current", "chapter_index": 3}
    elif scope == "excluded":
        context["excluded_targets"] = [str(uuid.uuid4())]
    elif scope == "confirmed":
        response = await async_client.post(
            "/api/evidence/compilation/confirm",
            json={
                "novel_id": test_project_id,
                "action": "writing.generate",
                "task": "核对讨论",
                "scope": "chapter",
                "chapter_index": 1,
                "context_mode": "canonical",
                "include_pending_objects": False,
            },
        )
        assert response.status_code == 201, response.text
        confirmation_id = uuid.UUID(response.json()["id"])
        context.update(
            context_confirmation_id=str(confirmation_id),
            context_confirmation_action="writing.generate",
        )
    for nid, sid, content, cid, kind in [
        (test_project_id, session_id, "旧共创消息", confirmation_id, "message"),
        (test_project_id, session_id, "旧手工决定", confirmation_id, "decision"),
        (test_project_id, session_id, "其他确认的讨论", uuid.uuid4(), "message"),
        (other_id, other_session, "其他作品的私有讨论", None, "message"),
    ]:
        db_session.add(
            AssistantMessage(
                novel_id=uuid.UUID(nid),
                session_id=uuid.UUID(sid),
                role="author",
                kind=kind,
                content=content,
                context_confirmation_id=cid,
            )
        )
    await db_session.commit()
    operation = str(uuid.uuid4())
    response = await async_client.post(
        f"/api/assistant/sessions/{session_id}/turns",
        json={
            "novel_id": test_project_id,
            "operation_id": operation,
            "message": "本轮唯一请求",
            "allow_web": False,
            "context": context,
        },
    )
    assert response.status_code == 202, response.text
    task = await db_session.get(AsyncTask, uuid.UUID(operation))
    task.status = "running"
    await db_session.flush()
    result = await AssistantService().execute(db_session, task)
    assert result["status"] == "completed"
    text = "\n".join(seen)
    for content in ("旧共创消息", "旧手工决定"):
        assert (content in text) is (scope in {"project", "confirmed"})
    assert ("其他确认的讨论" in text) is (scope == "project")
    assert "其他作品的私有讨论" not in text
    assert text.count("本轮唯一请求") == 1
