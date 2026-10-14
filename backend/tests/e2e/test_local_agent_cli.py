"""PostgreSQL JSON/lease gate for a paired local Agent task."""

from __future__ import annotations

import uuid

import pytest

from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask
from modules.local_agent.models import LocalAgentDevice, LocalAgentInvocation

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_local_task_waits_for_owner_approval_and_device(db_session, project_client):
    client, novel_id = project_client
    created = await client.post(
        "/api/local-agent/devices/pair",
        json={"novel_id": novel_id, "name": "测试 Mac"},
    )
    assert created.status_code == 200, created.text
    paired = await client.post(
        "/api/local-agent/companion/activate",
        json={"code": created.json()["code"]},
    )
    assert paired.status_code == 200, paired.text
    task = AsyncTask(
        task_type="world_object_image_generate",
        novel_id=uuid.UUID(novel_id),
        status="pending",
        meta={
            "_local_agent": True,
            "_local_ready": False,
            "_local_approved": False,
            "_local_device_id": paired.json()["device_id"],
        },
    )
    db_session.add(task)
    await db_session.commit()
    lifecycle = TaskLifecycleService()
    assert (
        await lifecycle.claim_next(db_session, task_id=task.id, novel_id=novel_id) is None
    )
    approved = await client.post(
        f"/api/local-agent/tasks/{task.id}/approve",
        json={"novel_id": novel_id, "acknowledge_full_host_access": True},
    )
    assert approved.status_code == 200, approved.text
    claimed = await lifecycle.claim_next(db_session, task_id=task.id, novel_id=novel_id)
    assert claimed is not None and claimed.status == "running"


@pytest.mark.parametrize("entry", ["pending", "approve", "claim"])
async def test_legacy_text_is_retired_at_postgres_transport_gate(
    db_session, project_client, entry
):
    client, novel_id = project_client
    pair = await client.post(
        "/api/local-agent/devices/pair", json={"novel_id": novel_id, "name": "旧文字夹具"}
    )
    activated = await client.post(
        "/api/local-agent/companion/activate", json={"code": pair.json()["code"]}
    )
    device = await db_session.get(
        LocalAgentDevice, uuid.UUID(activated.json()["device_id"])
    )
    task = AsyncTask(
        task_type="assistant_turn",
        novel_id=uuid.UUID(novel_id),
        status="pending",
        meta={
            "_local_agent": True,
            "_local_approved": False,
            "_local_device_id": str(device.id),
        },
    )
    if entry == "claim":
        task.mark_running(lease_id=str(uuid.uuid4()))
    db_session.add(task)
    await db_session.flush()
    invocation = LocalAgentInvocation(
        novel_id=task.novel_id,
        owner_id=device.owner_id,
        device_id=device.id,
        task_id=task.id,
        ordinal=1,
        cli="pi",
        status="pending",
        request_json={"prompt": "private synthetic text", "task_lease_id": task.lease_id},
    )
    db_session.add(invocation)
    await db_session.commit()
    if entry == "pending":
        response = await client.get(
            "/api/local-agent/tasks/pending", params={"novel_id": novel_id}
        )
        assert response.status_code == 200
        assert response.json() == {"items": []}
    elif entry == "approve":
        response = await client.post(
            f"/api/local-agent/tasks/{task.id}/approve",
            json={"novel_id": novel_id, "acknowledge_full_host_access": True},
        )
        assert response.status_code == 400
    else:
        response = await client.post(
            "/api/local-agent/companion/claim",
            headers={"Authorization": f"Bearer {activated.json()['token']}"},
        )
        assert response.status_code == 200 and response.json() == {"job": None}
    await db_session.refresh(task)
    await db_session.refresh(invocation)
    if entry == "claim":
        assert invocation.status == "failed" and invocation.lease_id is None
        assert "只运行图片任务" in invocation.error
    else:
        assert task.status == "failed" and task.lease_id is None
        assert "只运行图片任务" in task.error_message
    receipts = await client.get(
        f"/api/local-agent/tasks/{task.id}/receipts", params={"novel_id": novel_id}
    )
    assert receipts.status_code == 200
    assert "private synthetic text" not in receipts.text
