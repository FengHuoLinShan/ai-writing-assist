"""Pairing and pending-task gate with the real owner-scoped HTTP routes."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.config import get_settings
from infrastructure.tasks.enqueuer import _new_task
from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask
from modules.assistant.schemas import AssistantAnswer
from modules.assistant.service import AssistantService
from modules.local_agent.models import LocalAgentDevice, LocalAgentInvocation
from modules.local_agent.runtime import _reported_usage


def test_local_task_creation_disables_implicit_replay():
    task = _new_task(
        task_type="story_one_click",
        meta={"_local_agent": True},
        status="pending",
        progress=0,
        coalescing_key=None,
        novel_id=str(uuid.uuid4()),
    )
    assert task.recovery_policy == "never_retry"
    assert task.max_attempts == 1


@pytest.mark.asyncio
async def test_pair_select_approve_and_claim(db_session, async_client, test_project_id):
    created = await async_client.post(
        "/api/local-agent/devices/pair",
        json={"novel_id": test_project_id, "name": "作者的 Mac"},
    )
    assert created.status_code == 200, created.text
    paired = await async_client.post(
        "/api/local-agent/companion/activate",
        json={"code": created.json()["code"]},
    )
    assert paired.status_code == 200, paired.text
    device_id = paired.json()["device_id"]
    selected = await async_client.put(
        "/api/local-agent/executor",
        json={"novel_id": test_project_id, "kind": "pi", "device_id": device_id},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["kind"] == "pi"

    task = AsyncTask(
        task_type="assistant_turn",
        novel_id=uuid.UUID(test_project_id),
        status="pending",
        meta={
            "_local_agent": True,
            "_local_ready": False,
            "_local_approved": False,
            "_local_device_id": device_id,
        },
    )
    db_session.add(task)
    await db_session.commit()
    lifecycle = TaskLifecycleService()
    assert await lifecycle.claim_next(db_session) is None

    approved = await async_client.post(
        f"/api/local-agent/tasks/{task.id}/approve",
        json={"novel_id": test_project_id, "acknowledge_full_host_access": True},
    )
    assert approved.status_code == 200, approved.text
    claimed = await lifecycle.claim_next(db_session)
    assert claimed is not None and claimed.id == task.id
    assert claimed.meta["_local_ready"] is False
    revoked = await async_client.delete(
        f"/api/local-agent/devices/{device_id}",
        params={"novel_id": test_project_id},
    )
    assert revoked.status_code == 200, revoked.text
    assert (
        await db_session.get(AsyncTask, task.id, populate_existing=True)
    ).status == "cancelled"
    executor = await async_client.get(
        "/api/local-agent/executor", params={"novel_id": test_project_id}
    )
    assert executor.json()["kind"] == "gateway"


@pytest.mark.asyncio
async def test_pair_code_is_single_use(db_session, async_client, test_project_id):
    created = await async_client.post(
        "/api/local-agent/devices/pair",
        json={"novel_id": test_project_id, "name": "Mac"},
    )
    code = created.json()["code"]
    first = await async_client.post(
        "/api/local-agent/companion/activate", json={"code": code}
    )
    second = await async_client.post(
        "/api/local-agent/companion/activate", json={"code": code}
    )
    assert first.status_code == 200
    assert second.status_code >= 400


@pytest.mark.asyncio
async def test_companion_download_runs_without_source_checkout(
    async_client, test_project_id, tmp_path
):
    response = await async_client.get(
        "/api/local-agent/companion/download", params={"novel_id": test_project_id}
    )
    assert response.status_code == 200
    package = tmp_path / "novelcraft-agent.pyz"
    package.write_bytes(response.content)
    result = subprocess.run(
        [sys.executable, str(package), "--help"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": ""},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "pair" in result.stdout


@pytest.mark.asyncio
async def test_companion_lease_tool_limit_and_receipt(
    db_session, async_client, test_project_id
):
    created = await async_client.post(
        "/api/local-agent/devices/pair",
        json={"novel_id": test_project_id, "name": "Mac"},
    )
    activated = await async_client.post(
        "/api/local-agent/companion/activate",
        json={"code": created.json()["code"]},
    )
    device_id, token = activated.json()["device_id"], activated.json()["token"]
    task = AsyncTask(
        task_type="assistant_turn",
        novel_id=uuid.UUID(test_project_id),
        status="pending",
        meta={
            "_local_agent": True,
            "_local_ready": False,
            "_local_approved": False,
            "_local_device_id": device_id,
        },
    )
    db_session.add(task)
    await db_session.commit()
    approved = await async_client.post(
        f"/api/local-agent/tasks/{task.id}/approve",
        json={"novel_id": test_project_id, "acknowledge_full_host_access": True},
    )
    assert approved.status_code == 200
    running = await TaskLifecycleService().claim_next(db_session)
    assert running is not None
    device = await db_session.get(LocalAgentDevice, uuid.UUID(device_id))
    invocation = LocalAgentInvocation(
        novel_id=uuid.UUID(test_project_id),
        owner_id=device.owner_id,
        device_id=device.id,
        task_id=task.id,
        ordinal=1,
        cli="pi",
        status="pending",
        request_json={
            "prompt": "synthetic",
            "tools": {"read_fact": {}},
            "timeout_seconds": 30,
            "max_tool_attempts": 1,
            "task_lease_id": str(running.lease_id),
        },
    )
    db_session.add(invocation)
    await db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    claimed = await async_client.post(
        "/api/local-agent/companion/claim", json={}, headers=headers
    )
    assert claimed.status_code == 200, claimed.text
    job = claimed.json()["job"]
    lease = job["lease_id"]
    route = f"/api/local-agent/companion/jobs/{invocation.id}"
    call = {"lease_id": lease, "call_id": "one", "name": "read_fact", "arguments": {}}
    first = await async_client.post(route + "/tools", json=call, headers=headers)
    repeated = await async_client.post(route + "/tools", json=call, headers=headers)
    overflow = await async_client.post(
        route + "/tools", json={**call, "call_id": "two"}, headers=headers
    )
    assert first.status_code == repeated.status_code == 200
    assert overflow.status_code == 400
    stale = await async_client.post(
        route + "/heartbeat",
        json={"lease_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert stale.status_code == 409
    finished = await async_client.post(
        route + "/finish",
        json={"lease_id": lease, "status": "failed", "error": "synthetic failure"},
        headers=headers,
    )
    assert finished.status_code == 200, finished.text
    receipt = await async_client.get(
        f"/api/local-agent/tasks/{task.id}/receipts",
        params={"novel_id": test_project_id},
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["items"][0]["error"] == "synthetic failure"
    assert "prompt" not in receipt.text


@pytest.mark.asyncio
async def test_companion_never_receives_prompt_for_stale_task(
    db_session, async_client, test_project_id
):
    pair = await async_client.post(
        "/api/local-agent/devices/pair",
        json={"novel_id": test_project_id, "name": "Mac"},
    )
    activated = await async_client.post(
        "/api/local-agent/companion/activate", json={"code": pair.json()["code"]}
    )
    device = await db_session.get(
        LocalAgentDevice, uuid.UUID(activated.json()["device_id"])
    )
    task = AsyncTask(
        task_type="assistant_turn",
        novel_id=uuid.UUID(test_project_id),
        status="cancelled",
        meta={"_local_agent": True, "_local_device_id": str(device.id)},
    )
    db_session.add(task)
    await db_session.flush()
    invocation = LocalAgentInvocation(
        novel_id=uuid.UUID(test_project_id),
        owner_id=device.owner_id,
        device_id=device.id,
        task_id=task.id,
        ordinal=1,
        cli="claude",
        status="pending",
        request_json={"prompt": "private synthetic text", "task_lease_id": "stale"},
    )
    db_session.add(invocation)
    await db_session.commit()
    response = await async_client.post(
        "/api/local-agent/companion/claim",
        json={},
        headers={"Authorization": f"Bearer {activated.json()['token']}"},
    )
    assert response.status_code == 200
    assert response.json() == {"job": None}
    assert "private synthetic text" not in response.text
    receipt = await async_client.get(
        f"/api/local-agent/tasks/{task.id}/receipts",
        params={"novel_id": test_project_id},
    )
    assert receipt.json()["items"][0]["status"] == "failed"


def test_unreported_tokens_remain_unknown():
    assert _reported_usage({"usage": {"input_tokens": 5}}) is None
    assert _reported_usage({"usage": None}) is None
    known = _reported_usage({"usage": {"input_tokens": 5, "output_tokens": 3}})
    assert known and known.total_tokens == 8


@pytest.mark.asyncio
async def test_assistant_submit_freezes_local_executor_without_account_model(
    db_session, async_client, test_project_id, monkeypatch
):
    monkeypatch.setattr(
        "modules.assistant.service.get_settings",
        lambda: replace(get_settings(), assistant_enabled=True),
    )
    pair = await async_client.post(
        "/api/local-agent/devices/pair",
        json={"novel_id": test_project_id, "name": "Mac"},
    )
    device = await async_client.post(
        "/api/local-agent/companion/activate",
        json={"code": pair.json()["code"]},
    )
    selected = await async_client.put(
        "/api/local-agent/executor",
        json={
            "novel_id": test_project_id,
            "kind": "claude",
            "device_id": device.json()["device_id"],
        },
    )
    assert selected.status_code == 200
    session = await async_client.post(
        "/api/assistant/sessions", json={"novel_id": test_project_id}
    )
    assert session.status_code == 201
    response = await async_client.post(
        f"/api/assistant/sessions/{session.json()['id']}/turns",
        json={
            "novel_id": test_project_id,
            "operation_id": str(uuid.uuid4()),
            "message": "合成测试任务",
            "allow_web": False,
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["local_agent"] == {"kind": "claude", "approved": False}
    assert await TaskLifecycleService().claim_next(db_session) is None
    approved = await async_client.post(
        f"/api/local-agent/tasks/{response.json()['task_id']}/approve",
        json={"novel_id": test_project_id, "acknowledge_full_host_access": True},
    )
    assert approved.status_code == 200
    task = await TaskLifecycleService().claim_next(db_session)
    assert task is not None
    db_session.task_checkpoint_enabled = True

    async def fake_local_run(*_args, **kwargs):
        assert kwargs["cli"] == "claude"
        assert kwargs["novel_id"] == test_project_id
        return SimpleNamespace(output=AssistantAnswer(answer="合成结果"))

    monkeypatch.setattr("modules.local_agent.client.run_local_agent", fake_local_run)
    result = await AssistantService().execute(db_session, task)
    assert result["status"] == "completed"
