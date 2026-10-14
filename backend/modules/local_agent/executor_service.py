"""Project-owned selection of a paired local Agent executor."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from core.errors import NotFoundError, ValidationError
from infrastructure.llm.cli_agent import CLI_KINDS, CLIKind
from modules.local_agent.image_runtime import run_local_image
from modules.local_agent.images import (
    ReviewedImage,
    fit_cover,
    limit_edge,
    review_generated_image,
)
from modules.local_agent.models import LocalAgentDevice
from modules.project.facade import get_any_project_context, save_agent_executor_settings

__all__ = [
    "AgentExecutor",
    "ReviewedImage",
    "fit_cover",
    "limit_edge",
    "local_image_task_meta",
    "review_generated_image",
    "run_local_image",
    "save_executor",
    "selected_executor",
    "task_awaiting_local_approval",
]


@dataclass(frozen=True)
class AgentExecutor:
    kind: str = "gateway"
    device_id: str | None = None


def local_image_task_meta(executor: AgentExecutor) -> dict:
    """Task meta the world module attaches so image jobs gate through the same
    per-task local-device approval flow as text jobs did."""
    if executor.kind == "gateway" or not executor.device_id:
        return {}
    return {
        "_local_agent": True,
        "_local_ready": False,
        "_local_approved": False,
        "_local_device_id": executor.device_id,
    }


async def task_awaiting_local_approval(db, task_id: str) -> bool:
    """Whether one task is a pending, not-yet-approved local-agent task.

    Callers outside this module (e.g. the world object image and map atlas
    review views) use this to show an "awaiting host approval" state without
    reaching into the task ORM's ``meta`` payload directly.
    """
    from infrastructure.tasks.models import AsyncTask

    try:
        task = await db.get(AsyncTask, uuid.UUID(str(task_id)))
    except ValueError:
        return False
    if task is None:
        return False
    meta = task.meta or {}
    return bool(
        task.status == "pending"
        and meta.get("_local_agent")
        and not meta.get("_local_approved")
    )


async def selected_executor(db, novel_id: str, owner_id: str) -> AgentExecutor:
    project = await get_any_project_context(db, novel_id)
    if project is None or str(project.owner_id) != owner_id:
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
        or str(device.novel_id) != project.novel_id
        or str(device.owner_id) != project.owner_id
        or device.revoked_at is not None
        or device.token_digest is None
    ):
        raise ValidationError("项目本机设备未配对或已撤销")
    return AgentExecutor(kind=kind, device_id=device_id)


async def save_executor(
    db, novel_id: str, owner_id: str, kind: CLIKind | str, device_id: str | None
) -> AgentExecutor:
    project = await get_any_project_context(db, novel_id, for_update=True)
    if project is None or str(project.owner_id) != owner_id:
        raise NotFoundError("作品不可访问")
    if kind == "gateway":
        selected = {"kind": "gateway"}
    elif kind in CLI_KINDS and device_id:
        device = await db.get(LocalAgentDevice, uuid.UUID(device_id))
        if (
            device is None
            or str(device.novel_id) != project.novel_id
            or str(device.owner_id) != project.owner_id
            or device.revoked_at is not None
            or device.token_digest is None
        ):
            raise ValidationError("本机设备未配对或已撤销")
        selected = {"kind": kind, "device_id": device_id}
    else:
        raise ValidationError("请选择已配对的本机设备和 CLI")
    await save_agent_executor_settings(db, novel_id, owner_id, selected)
    await db.commit()
    return AgentExecutor(**selected)
