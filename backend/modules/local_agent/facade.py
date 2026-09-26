"""Project-owned selection of a paired local Agent executor."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

from core.errors import NotFoundError, ValidationError
from infrastructure.llm.cli_agent import CLI_KINDS, CLIKind
from modules.local_agent.models import LocalAgentDevice
from modules.project.models import Project


@dataclass(frozen=True)
class AgentExecutor:
    kind: str = "gateway"
    device_id: str | None = None


def local_task_meta(snapshot: dict | None) -> dict:
    local = (snapshot or {}).get("local_agent") or {}
    if not local.get("device_id"):
        return {}
    return {
        "_local_agent": True,
        "_local_ready": False,
        "_local_approved": False,
        "_local_device_id": local["device_id"],
    }


async def task_snapshot_client(db, task, settings, *, budget, checkpoint=None):
    """Open the frozen project executor for one lease-fenced task."""
    local = settings.get("_local_agent") or {}
    if not local:
        from modules.project.facade import create_project_snapshot_llm_client

        return create_project_snapshot_llm_client(settings, novel_id=str(task.novel_id))
    from modules.local_agent.client import LocalCLIClient

    project = await db.get(Project, task.novel_id)
    if project is None:
        raise NotFoundError("作品不可访问")
    return LocalCLIClient(
        db,
        task_id=str(task.id),
        novel_id=str(task.novel_id),
        owner_id=str(project.owner_id),
        device_id=local["device_id"],
        kind=local["kind"],
        budget=budget,
        checkpoint=checkpoint,
    )


@asynccontextmanager
async def open_task_snapshot_client(db, task, snapshot, *, budget, checkpoint=None):
    from modules.project.facade import restore_project_llm_execution_settings

    settings = await restore_project_llm_execution_settings(
        db, str(task.novel_id), snapshot
    )
    client = await task_snapshot_client(
        db, task, settings, budget=budget, checkpoint=checkpoint
    )
    try:
        yield client
    finally:
        await client.close()


async def selected_executor(db, novel_id: str, owner_id: str) -> AgentExecutor:
    project = await db.get(Project, uuid.UUID(novel_id))
    if (
        project is None
        or project.deleted_at is not None
        or str(project.owner_id) != owner_id
    ):
        raise NotFoundError("作品不可访问")
    selection = (project.settings or {}).get("agent_executor") or {}
    kind = selection.get("kind", "gateway")
    if kind == "gateway":
        return AgentExecutor()
    if kind not in CLI_KINDS:
        raise ValidationError("项目 Agent 执行器不可用")
    device_id = str(selection.get("device_id") or "")
    try:
        device = await db.get(LocalAgentDevice, uuid.UUID(device_id))
    except ValueError as exc:
        raise ValidationError("项目本机设备无效") from exc
    if (
        device is None
        or device.novel_id != project.id
        or device.owner_id != project.owner_id
        or device.revoked_at is not None
        or device.token_digest is None
    ):
        raise ValidationError("项目本机设备未配对或已撤销")
    return AgentExecutor(kind=kind, device_id=device_id)


async def save_executor(
    db, novel_id: str, owner_id: str, kind: CLIKind | str, device_id: str | None
) -> AgentExecutor:
    project = await db.get(Project, uuid.UUID(novel_id), with_for_update=True)
    if (
        project is None
        or project.deleted_at is not None
        or str(project.owner_id) != owner_id
    ):
        raise NotFoundError("作品不可访问")
    if kind == "gateway":
        selected = {"kind": "gateway"}
    elif kind in CLI_KINDS and device_id:
        device = await db.get(LocalAgentDevice, uuid.UUID(device_id))
        if (
            device is None
            or device.novel_id != project.id
            or device.owner_id != project.owner_id
            or device.revoked_at is not None
            or device.token_digest is None
        ):
            raise ValidationError("本机设备未配对或已撤销")
        selected = {"kind": kind, "device_id": device_id}
    else:
        raise ValidationError("请选择已配对的本机设备和 CLI")
    project.settings = {**(project.settings or {}), "agent_executor": selected}
    await db.commit()
    return AgentExecutor(**selected)
