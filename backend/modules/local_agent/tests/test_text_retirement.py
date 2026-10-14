"""Retired text settings cannot reopen the host transport."""

import pytest

from core.errors import ValidationError
from modules.local_agent.executor_service import task_snapshot_client


@pytest.mark.asyncio
async def test_legacy_text_settings_fail_before_project_or_device_access():
    with pytest.raises(ValidationError, match="只运行图片任务"):
        await task_snapshot_client(
            None, None, {"_local_agent": {"device_id": "old-device"}}, budget=None
        )


@pytest.mark.parametrize("entry", ["pending", "approve", "claim"])
async def test_legacy_pending_text_task_is_failed_and_receipts_remain_readable(
    db_session, async_client, test_project_id, entry
):
    import uuid

    from infrastructure.tasks.models import AsyncTask
    from modules.local_agent.models import LocalAgentDevice, LocalAgentInvocation

    pair = await async_client.post(
        "/api/local-agent/devices/pair", json={"novel_id": test_project_id, "name": "Mac"}
    )
    activated = await async_client.post(
        "/api/local-agent/companion/activate", json={"code": pair.json()["code"]}
    )
    device = await db_session.get(
        LocalAgentDevice, uuid.UUID(activated.json()["device_id"])
    )
    task = AsyncTask(
        novel_id=uuid.UUID(test_project_id),
        task_type="assistant_turn",
        status="pending",
        meta={
            "_local_agent": True,
            "_local_approved": entry == "claim",
            "_local_device_id": str(device.id),
        },
    )
    db_session.add(task)
    await db_session.flush()
    invocation = LocalAgentInvocation(
        novel_id=task.novel_id,
        owner_id=device.owner_id,
        device_id=device.id,
        task_id=task.id,
        ordinal=1,
        cli="pi",
        status="completed",
        request_json={"prompt": "private history"},
        result_json={"visible_text": "历史回执"},
    )
    db_session.add(invocation)
    await db_session.commit()
    if entry == "pending":
        response = await async_client.get(
            "/api/local-agent/tasks/pending", params={"novel_id": test_project_id}
        )
        assert response.status_code == 200
        assert response.json() == {"items": []}
    elif entry == "approve":
        response = await async_client.post(
            f"/api/local-agent/tasks/{task.id}/approve",
            json={"novel_id": test_project_id, "acknowledge_full_host_access": True},
        )
        assert response.status_code == 400
        assert "本机设备只运行图片任务" in response.text
    else:
        response = await async_client.post(
            "/api/local-agent/companion/claim",
            headers={"Authorization": f"Bearer {activated.json()['token']}"},
        )
        assert response.status_code == 200
        assert response.json() == {"job": None}
    await db_session.refresh(task)
    assert task.status == "failed"
    assert task.finished_at is not None and task.lease_id is None
    assert "当前账户模型重新发起" in task.error_message
    receipt = await async_client.get(
        f"/api/local-agent/tasks/{task.id}/receipts", params={"novel_id": test_project_id}
    )
    assert receipt.json()["items"][0]["visible_text"] == "历史回执"
    assert "private history" not in receipt.text


@pytest.mark.parametrize(
    "task_type", ["assistant_turn", "world_object_image_generate", "map_atlas_generate"]
)
async def test_pending_and_approve_do_not_change_foreign_owner_tasks(
    db_session, async_client, project_factory, task_type
):
    import uuid

    from infrastructure.tasks.models import AsyncTask
    from modules.account.models import Account

    account = Account(support_code="foreign-local-retirement")
    db_session.add(account)
    await db_session.flush()
    novel_id = await project_factory.create_project(owner_id=account.id)
    task = AsyncTask(
        novel_id=novel_id,
        task_type=task_type,
        status="pending",
        meta={
            "_local_agent": True,
            "_local_approved": False,
            "_local_device_id": str(uuid.uuid4()),
        },
    )
    db_session.add(task)
    await db_session.commit()
    pending = await async_client.get(
        "/api/local-agent/tasks/pending", params={"novel_id": str(novel_id)}
    )
    approved = await async_client.post(
        f"/api/local-agent/tasks/{task.id}/approve",
        json={"novel_id": str(novel_id), "acknowledge_full_host_access": True},
    )
    assert pending.status_code == approved.status_code == 404
    await db_session.refresh(task)
    assert task.status == "pending" and task.error_message is None
