"""Companion image endpoints and the server-side run_local_image orchestration."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

import pytest
from PIL import Image
from sqlalchemy import select

from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.local_agent import image_runtime
from modules.local_agent.facade import AgentExecutor, run_local_image
from modules.local_agent.models import (
    LocalAgentDevice,
    LocalAgentFile,
    LocalAgentInvocation,
)


def _png_bytes(size=(32, 32), color=(9, 9, 9)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


async def _paired_device(async_client, db_session, test_project_id, *, name="Mac"):
    created = await async_client.post(
        "/api/local-agent/devices/pair",
        json={"novel_id": test_project_id, "name": name},
    )
    activated = await async_client.post(
        "/api/local-agent/companion/activate",
        json={"code": created.json()["code"]},
    )
    device = await db_session.get(
        LocalAgentDevice, uuid.UUID(activated.json()["device_id"])
    )
    return device, activated.json()["token"]


async def _running_task(db_session, test_project_id, device):
    task = AsyncTask(
        task_type="world_object_image_generate",
        novel_id=uuid.UUID(test_project_id),
        status="pending",
        meta={"_local_agent": True, "_local_device_id": str(device.id)},
    )
    task.mark_running(lease_id=str(uuid.uuid4()))
    db_session.add(task)
    await db_session.commit()
    return task


async def _image_invocation(
    db_session, test_project_id, device, task, *, mode="image", max_tool_attempts=32
):
    invocation = LocalAgentInvocation(
        novel_id=uuid.UUID(test_project_id),
        owner_id=device.owner_id,
        device_id=device.id,
        task_id=task.id,
        ordinal=1,
        cli="pi",
        status="pending",
        request_json={
            "mode": mode,
            "prompt": "synthetic image prompt",
            "inputs": [],
            "width": 512,
            "height": 512,
            "timeout_seconds": 30,
            "max_tool_attempts": max_tool_attempts,
            "tools": {},
            "task_lease_id": str(task.lease_id),
        },
    )
    db_session.add(invocation)
    await db_session.commit()
    return invocation


async def _claim(async_client, token):
    response = await async_client.post(
        "/api/local-agent/companion/claim",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["job"]


class TestOutputEndpoint:
    async def test_wrong_token_is_not_found(self, async_client, test_project_id):
        response = await async_client.put(
            "/api/local-agent/companion/jobs/"
            f"{uuid.uuid4()}/output?lease_id={uuid.uuid4()}",
            content=_png_bytes(),
            headers={
                "Authorization": "Bearer nonexistent.token",
                "Content-Type": "image/png",
            },
        )
        assert response.status_code == 404

    async def test_stale_lease_is_conflict(
        self, db_session, async_client, test_project_id
    ):
        device, token = await _paired_device(async_client, db_session, test_project_id)
        task = await _running_task(db_session, test_project_id, device)
        invocation = await _image_invocation(db_session, test_project_id, device, task)
        await _claim(async_client, token)
        response = await async_client.put(
            f"/api/local-agent/companion/jobs/{invocation.id}/output"
            f"?lease_id={uuid.uuid4()}",
            content=_png_bytes(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/png",
            },
        )
        assert response.status_code == 409

    async def test_non_image_mode_is_rejected(
        self, db_session, async_client, test_project_id
    ):
        device, token = await _paired_device(async_client, db_session, test_project_id)
        task = await _running_task(db_session, test_project_id, device)
        invocation = await _image_invocation(
            db_session, test_project_id, device, task, mode="text"
        )
        job = await _claim(async_client, token)
        response = await async_client.put(
            f"/api/local-agent/companion/jobs/{invocation.id}/output"
            f"?lease_id={job['lease_id']}",
            content=_png_bytes(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/png",
            },
        )
        assert response.status_code in (404, 409)

    async def test_invalid_body_is_rejected(
        self, db_session, async_client, test_project_id
    ):
        device, token = await _paired_device(async_client, db_session, test_project_id)
        task = await _running_task(db_session, test_project_id, device)
        invocation = await _image_invocation(db_session, test_project_id, device, task)
        job = await _claim(async_client, token)
        response = await async_client.put(
            f"/api/local-agent/companion/jobs/{invocation.id}/output"
            f"?lease_id={job['lease_id']}",
            content=b"not a real image" * 10,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/png",
            },
        )
        assert response.status_code == 400

    async def test_valid_png_is_stored_as_reviewed_png(
        self, db_session, async_client, test_project_id
    ):
        device, token = await _paired_device(async_client, db_session, test_project_id)
        task = await _running_task(db_session, test_project_id, device)
        invocation = await _image_invocation(db_session, test_project_id, device, task)
        job = await _claim(async_client, token)
        payload = _png_bytes((40, 20))
        response = await async_client.put(
            f"/api/local-agent/companion/jobs/{invocation.id}/output"
            f"?lease_id={job['lease_id']}",
            content=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/png",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["width"], body["height"]) == (40, 20)
        stored = await db_session.scalar(
            select(LocalAgentFile).where(
                LocalAgentFile.invocation_id == invocation.id,
                LocalAgentFile.role == "output",
            )
        )
        assert stored is not None
        assert stored.sha256 == body["sha256"]
        with Image.open(io.BytesIO(stored.data)) as reencoded:
            assert reencoded.format == "PNG"

    async def test_oversize_body_is_rejected(
        self, db_session, async_client, test_project_id
    ):
        device, token = await _paired_device(async_client, db_session, test_project_id)
        task = await _running_task(db_session, test_project_id, device)
        invocation = await _image_invocation(db_session, test_project_id, device, task)
        job = await _claim(async_client, token)
        oversized = b"\x89PNG\r\n\x1a\n" + b"0" * (20 * 1024 * 1024 + 16)
        response = await async_client.put(
            f"/api/local-agent/companion/jobs/{invocation.id}/output"
            f"?lease_id={job['lease_id']}",
            content=oversized,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/png",
            },
        )
        assert response.status_code == 413


class TestInputsEndpoint:
    async def test_returns_stored_bytes(self, db_session, async_client, test_project_id):
        device, token = await _paired_device(async_client, db_session, test_project_id)
        task = await _running_task(db_session, test_project_id, device)
        invocation = await _image_invocation(db_session, test_project_id, device, task)
        payload = _png_bytes((16, 16))
        db_session.add(
            LocalAgentFile(
                invocation_id=invocation.id,
                novel_id=uuid.UUID(test_project_id),
                role="input",
                ordinal=0,
                name="reference-1.png",
                media_type="image/png",
                data=payload,
                byte_size=len(payload),
                sha256="a" * 64,
            )
        )
        await db_session.commit()
        job = await _claim(async_client, token)
        response = await async_client.get(
            f"/api/local-agent/companion/jobs/{invocation.id}/inputs/0"
            f"?lease_id={job['lease_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.content == payload
        assert response.headers["content-type"].startswith("image/png")

    async def test_missing_ordinal_is_not_found(
        self, db_session, async_client, test_project_id
    ):
        device, token = await _paired_device(async_client, db_session, test_project_id)
        task = await _running_task(db_session, test_project_id, device)
        invocation = await _image_invocation(db_session, test_project_id, device, task)
        job = await _claim(async_client, token)
        response = await async_client.get(
            f"/api/local-agent/companion/jobs/{invocation.id}/inputs/9"
            f"?lease_id={job['lease_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


class TestRunLocalImage:
    async def test_revoked_device_fails_before_creating_invocation(
        self, db_session, test_project_id
    ):
        from modules.project.models import Project

        project = await db_session.get(Project, uuid.UUID(test_project_id))
        task = AsyncTask(
            task_type="world_object_image_generate",
            novel_id=uuid.UUID(test_project_id),
            status="running",
        )
        task.mark_running(lease_id=str(uuid.uuid4()))
        db_session.add(task)
        await db_session.commit()
        executor = AgentExecutor(kind="pi", device_id=str(uuid.uuid4()))
        with pytest.raises(ConflictError) as excinfo:
            await run_local_image(
                db_session,
                task=task,
                novel_id=test_project_id,
                owner_id=str(project.owner_id),
                executor=executor,
                prompt="a red circle",
                width=64,
                height=64,
            )
        assert excinfo.value.code == "local_image_unavailable"
        remaining = await db_session.scalar(
            select(LocalAgentInvocation).where(LocalAgentInvocation.task_id == task.id)
        )
        assert remaining is None

    async def test_happy_path_returns_reviewed_image_and_clears_files(
        self, db_session, async_client, test_project_id, monkeypatch
    ):
        from modules.project.models import Project

        device, _token = await _paired_device(async_client, db_session, test_project_id)
        task = AsyncTask(
            task_type="world_object_image_generate",
            novel_id=uuid.UUID(test_project_id),
            status="running",
        )
        task.mark_running(lease_id=str(uuid.uuid4()))
        db_session.add(task)
        await db_session.commit()
        project = await db_session.get(Project, uuid.UUID(test_project_id))
        executor = AgentExecutor(kind="pi", device_id=str(device.id))
        output_payload = _png_bytes((30, 20))

        async def companion_completes(_seconds):
            invocation = await db_session.scalar(
                select(LocalAgentInvocation).where(
                    LocalAgentInvocation.task_id == task.id
                )
            )
            if invocation.status == "pending":
                invocation.status = "running"
                invocation.heartbeat_at = datetime.now(UTC)
                await db_session.commit()
                return
            if invocation.status == "running":
                db_session.add(
                    LocalAgentFile(
                        invocation_id=invocation.id,
                        novel_id=uuid.UUID(test_project_id),
                        role="output",
                        ordinal=0,
                        name="output.png",
                        media_type="image/png",
                        data=output_payload,
                        byte_size=len(output_payload),
                        sha256="deadbeef" * 8,
                    )
                )
                invocation.status = "completed"
                invocation.heartbeat_at = datetime.now(UTC)
                await db_session.commit()

        monkeypatch.setattr(image_runtime.asyncio, "sleep", companion_completes)
        result = await run_local_image(
            db_session,
            task=task,
            novel_id=test_project_id,
            owner_id=str(project.owner_id),
            executor=executor,
            prompt="a red circle",
            width=64,
            height=64,
            inputs=[("reference-1.png", "image/png", _png_bytes((10, 10)))],
        )
        assert (result.width, result.height) == (30, 20)
        assert result.data == output_payload

        invocation_id = await db_session.scalar(
            select(LocalAgentInvocation.id).where(LocalAgentInvocation.task_id == task.id)
        )
        remaining_files = (
            await db_session.scalars(
                select(LocalAgentFile).where(
                    LocalAgentFile.invocation_id == invocation_id
                )
            )
        ).all()
        assert remaining_files == []

    async def test_companion_reports_failed(
        self, db_session, async_client, test_project_id, monkeypatch
    ):
        from modules.project.models import Project

        device, _token = await _paired_device(async_client, db_session, test_project_id)
        task = AsyncTask(
            task_type="world_object_image_generate",
            novel_id=uuid.UUID(test_project_id),
            status="running",
        )
        task.mark_running(lease_id=str(uuid.uuid4()))
        db_session.add(task)
        await db_session.commit()
        project = await db_session.get(Project, uuid.UUID(test_project_id))
        executor = AgentExecutor(kind="pi", device_id=str(device.id))

        async def companion_fails(_seconds):
            invocation = await db_session.scalar(
                select(LocalAgentInvocation).where(
                    LocalAgentInvocation.task_id == task.id
                )
            )
            invocation.status = "failed"
            invocation.error = "本机 CLI 未安装"
            await db_session.commit()

        monkeypatch.setattr(image_runtime.asyncio, "sleep", companion_fails)
        with pytest.raises(ConflictError) as excinfo:
            await run_local_image(
                db_session,
                task=task,
                novel_id=test_project_id,
                owner_id=str(project.owner_id),
                executor=executor,
                prompt="a red circle",
                width=64,
                height=64,
            )
        assert excinfo.value.code == "local_image_failed"

    async def test_completed_without_output_row_fails_closed(
        self, db_session, async_client, test_project_id, monkeypatch
    ):
        from modules.project.models import Project

        device, _token = await _paired_device(async_client, db_session, test_project_id)
        task = AsyncTask(
            task_type="world_object_image_generate",
            novel_id=uuid.UUID(test_project_id),
            status="running",
        )
        task.mark_running(lease_id=str(uuid.uuid4()))
        db_session.add(task)
        await db_session.commit()
        project = await db_session.get(Project, uuid.UUID(test_project_id))
        executor = AgentExecutor(kind="pi", device_id=str(device.id))

        async def companion_completes_without_output(_seconds):
            invocation = await db_session.scalar(
                select(LocalAgentInvocation).where(
                    LocalAgentInvocation.task_id == task.id
                )
            )
            invocation.status = "completed"
            invocation.heartbeat_at = datetime.now(UTC)
            await db_session.commit()

        monkeypatch.setattr(
            image_runtime.asyncio, "sleep", companion_completes_without_output
        )
        with pytest.raises(ConflictError) as excinfo:
            await run_local_image(
                db_session,
                task=task,
                novel_id=test_project_id,
                owner_id=str(project.owner_id),
                executor=executor,
                prompt="a red circle",
                width=64,
                height=64,
            )
        assert excinfo.value.code == "local_image_missing_output"

    async def test_heartbeat_gap_fails_the_run(
        self, db_session, async_client, test_project_id, monkeypatch
    ):
        from modules.project.models import Project

        device, _token = await _paired_device(async_client, db_session, test_project_id)
        task = AsyncTask(
            task_type="world_object_image_generate",
            novel_id=uuid.UUID(test_project_id),
            status="running",
        )
        task.mark_running(lease_id=str(uuid.uuid4()))
        db_session.add(task)
        await db_session.commit()
        project = await db_session.get(Project, uuid.UUID(test_project_id))
        executor = AgentExecutor(kind="pi", device_id=str(device.id))

        async def companion_goes_silent(_seconds):
            invocation = await db_session.scalar(
                select(LocalAgentInvocation).where(
                    LocalAgentInvocation.task_id == task.id
                )
            )
            if invocation.status == "pending":
                invocation.status = "running"
                invocation.heartbeat_at = (
                    datetime.now(UTC) - image_runtime._HEARTBEAT_GAP * 2
                )
                await db_session.commit()

        monkeypatch.setattr(image_runtime.asyncio, "sleep", companion_goes_silent)
        with pytest.raises(ConflictError) as excinfo:
            await run_local_image(
                db_session,
                task=task,
                novel_id=test_project_id,
                owner_id=str(project.owner_id),
                executor=executor,
                prompt="a red circle",
                width=64,
                height=64,
            )
        assert excinfo.value.code == "local_image_failed"
