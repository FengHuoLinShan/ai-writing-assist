"""Project-scoped pairing and outbound companion transport."""

from __future__ import annotations

import hashlib
import hmac
import io
import secrets
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from core.dependencies import DbSession
from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.tasks.models import AsyncTask
from modules.account.facade import current_account_id, require_account_active
from modules.local_agent.facade import save_executor, selected_executor
from modules.local_agent.models import (
    LocalAgentDevice,
    LocalAgentInvocation,
    LocalAgentToolCall,
)
from modules.project.facade import require_active_project

router = APIRouter(prefix="/api/local-agent", tags=["local-agent"])


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class PairStart(BaseModel):
    novel_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)


class ExecutorUpdate(BaseModel):
    novel_id: uuid.UUID
    kind: str = Field(pattern="^(gateway|codex|claude|kimi|dsh|pi)$")
    device_id: uuid.UUID | None = None


class LocalApproval(BaseModel):
    novel_id: uuid.UUID
    acknowledge_full_host_access: bool


class PairFinish(BaseModel):
    code: str = Field(min_length=40, max_length=100)


class LeaseUpdate(BaseModel):
    lease_id: uuid.UUID


class EventUpdate(LeaseUpdate):
    sequence: int = Field(ge=1)
    kind: str = Field(pattern="^(text|tool|usage)$")
    text: str = Field(default="", max_length=30000)
    tool_name: str = Field(default="", max_length=100)
    usage: dict[str, int] | None = None


class ToolRequest(LeaseUpdate):
    call_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,99}$")
    arguments: dict


class FinishRequest(LeaseUpdate):
    status: str = Field(pattern="^(completed|failed)$")
    answer: str = Field(default="", max_length=100000)
    error: str = Field(default="", max_length=2000)
    tool_attempts: int = Field(default=0, ge=0)
    usage: dict[str, int] | None = None


async def _device(db: DbSession, authorization: str | None) -> LocalAgentDevice:
    if not authorization or not authorization.startswith("Bearer "):
        raise NotFoundError("本机设备凭据无效")
    try:
        device_id, secret = authorization[7:].split(".", 1)
        parsed_id = uuid.UUID(device_id)
    except (TypeError, ValueError) as exc:
        raise NotFoundError("本机设备凭据无效") from exc
    device = await db.get(LocalAgentDevice, parsed_id)
    if (
        device is None
        or device.revoked_at is not None
        or device.token_digest is None
        or not hmac.compare_digest(device.token_digest, _digest(secret))
    ):
        raise NotFoundError("本机设备凭据无效")
    await require_account_active(db, device.owner_id)
    from modules.project.models import Project

    project = await db.get(Project, device.novel_id)
    if (
        project is None
        or project.deleted_at is not None
        or project.owner_id != device.owner_id
    ):
        raise NotFoundError("本机设备所属作品不可用")
    return device


async def _invocation(
    db: DbSession, device: LocalAgentDevice, invocation_id: uuid.UUID, lease_id: uuid.UUID
) -> LocalAgentInvocation:
    invocation = (
        await db.execute(
            select(LocalAgentInvocation)
            .where(
                LocalAgentInvocation.id == invocation_id,
                LocalAgentInvocation.device_id == device.id,
                LocalAgentInvocation.novel_id == device.novel_id,
                LocalAgentInvocation.owner_id == device.owner_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if (
        invocation is None
        or invocation.lease_id != str(lease_id)
        or invocation.status != "running"
    ):
        raise ConflictError("本机任务租约已失效", code="local_agent_lease_stale")
    task = await db.get(AsyncTask, invocation.task_id)
    if (
        task is None
        or task.status != "running"
        or str(task.lease_id) != invocation.request_json.get("task_lease_id")
    ):
        raise ConflictError("原始任务已停止或被替代", code="local_agent_task_stale")
    return invocation


@router.post("/devices/pair")
async def start_pair(db: DbSession, data: PairStart):
    await require_active_project(db, str(data.novel_id))
    code = secrets.token_urlsafe(36)
    device = LocalAgentDevice(
        novel_id=data.novel_id,
        owner_id=current_account_id(),
        name=data.name,
        pair_digest=_digest(code),
        pair_expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.add(device)
    await db.commit()
    return {
        "device_id": str(device.id),
        "code": code,
        "expires_at": device.pair_expires_at,
    }


@router.post("/companion/activate")
async def finish_pair(db: DbSession, data: PairFinish):
    device = (
        await db.execute(
            select(LocalAgentDevice)
            .where(LocalAgentDevice.pair_digest == _digest(data.code))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if (
        device is None
        or device.revoked_at is not None
        or device.pair_expires_at is None
        or _utc(device.pair_expires_at) < datetime.now(UTC)
    ):
        raise ValidationError("配对码无效或已过期")
    await require_account_active(db, device.owner_id)
    token = secrets.token_urlsafe(48)
    device.token_digest = _digest(token)
    device.pair_digest = None
    device.pair_expires_at = None
    device.last_seen_at = datetime.now(UTC)
    await db.commit()
    return {"device_id": str(device.id), "token": f"{device.id}.{token}"}


@router.get("/devices")
async def list_devices(db: DbSession, novel_id: uuid.UUID):
    await require_active_project(db, str(novel_id))
    rows = (
        await db.scalars(
            select(LocalAgentDevice).where(
                LocalAgentDevice.novel_id == novel_id,
                LocalAgentDevice.owner_id == current_account_id(),
                LocalAgentDevice.revoked_at.is_(None),
            )
        )
    ).all()
    return {
        "items": [
            {
                "id": str(row.id),
                "name": row.name,
                "paired": row.token_digest is not None,
                "online": bool(
                    row.last_seen_at
                    and datetime.now(UTC) - _utc(row.last_seen_at) < timedelta(seconds=10)
                ),
                "last_seen_at": row.last_seen_at,
            }
            for row in rows
        ]
    }


@router.get("/companion/download")
async def download_companion(db: DbSession, novel_id: uuid.UUID):
    await require_active_project(db, str(novel_id))
    source = Path(__file__).resolve().parents[2]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "__main__.py", "from modules.local_agent.companion import main\nmain()\n"
        )
        for package in (
            "modules",
            "modules/local_agent",
            "infrastructure",
            "infrastructure/llm",
        ):
            archive.writestr(f"{package}/__init__.py", "")
        for module in (
            "modules/local_agent/companion.py",
            "infrastructure/llm/cli_agent.py",
        ):
            archive.write(source / module, module)
    return Response(
        stream.getvalue(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="novelcraft-agent.pyz"'},
    )


@router.get("/executor")
async def get_executor(db: DbSession, novel_id: uuid.UUID):
    await require_active_project(db, str(novel_id))
    return await selected_executor(db, str(novel_id), str(current_account_id()))


@router.get("/tasks/pending")
async def pending_approvals(db: DbSession, novel_id: uuid.UUID):
    await require_active_project(db, str(novel_id))
    rows = (
        await db.scalars(
            select(AsyncTask)
            .where(
                AsyncTask.novel_id == novel_id,
                AsyncTask.status == "pending",
                AsyncTask.meta["_local_agent"].as_boolean().is_(True),
                AsyncTask.meta["_local_approved"].as_boolean().is_(False),
            )
            .order_by(AsyncTask.created_at.desc())
            .limit(50)
        )
    ).all()
    labels = {
        "assistant_turn": "项目助手",
        "assistant_forecast": "前瞻分析",
        "collaboration_run": "创作协作",
        "interaction_continuity_review": "旅程连续性检查",
        "story_one_click": "场景排演",
    }
    return {
        "items": [
            {
                "task_id": str(row.id),
                "label": labels.get(row.task_type, "本机 Agent 任务"),
            }
            for row in rows
        ]
    }


@router.get("/tasks/{task_id}/receipts")
async def task_receipts(db: DbSession, task_id: uuid.UUID, novel_id: uuid.UUID):
    await require_active_project(db, str(novel_id))
    task = await db.get(AsyncTask, task_id)
    if (
        task is None
        or task.novel_id != novel_id
        or not (task.meta or {}).get("_local_agent")
    ):
        raise NotFoundError("本机任务不存在")
    rows = (
        await db.scalars(
            select(LocalAgentInvocation)
            .where(
                LocalAgentInvocation.task_id == task_id,
                LocalAgentInvocation.novel_id == novel_id,
                LocalAgentInvocation.owner_id == current_account_id(),
            )
            .order_by(LocalAgentInvocation.ordinal)
        )
    ).all()
    return {
        "items": [
            {
                "ordinal": row.ordinal,
                "status": (
                    "interrupted"
                    if task.status in {"failed", "cancelled"}
                    and row.status in {"pending", "running"}
                    else row.status
                ),
                "visible_text": str((row.result_json or {}).get("visible_text") or "")[
                    :100000
                ],
                "tool_attempts": (row.result_json or {}).get("tool_attempts"),
                "usage": (row.result_json or {}).get("usage"),
                "error": row.error or (
                    "原始任务已中断"
                    if task.status in {"failed", "cancelled"}
                    and row.status in {"pending", "running"}
                    else None
                ),
            }
            for row in rows
        ]
    }


@router.put("/executor")
async def update_executor(db: DbSession, data: ExecutorUpdate):
    await require_active_project(db, str(data.novel_id))
    return await save_executor(
        db,
        str(data.novel_id),
        str(current_account_id()),
        data.kind,
        str(data.device_id) if data.device_id else None,
    )


@router.delete("/devices/{device_id}")
async def revoke_device(db: DbSession, device_id: uuid.UUID, novel_id: uuid.UUID):
    await require_active_project(db, str(novel_id))
    device = await db.get(LocalAgentDevice, device_id, with_for_update=True)
    if (
        device is None
        or device.novel_id != novel_id
        or device.owner_id != current_account_id()
    ):
        raise NotFoundError("本机设备不存在")
    device.revoked_at = datetime.now(UTC)
    device.token_digest = None
    from modules.project.models import Project

    project = await db.get(Project, novel_id, with_for_update=True)
    if project and (project.settings or {}).get("agent_executor", {}).get(
        "device_id"
    ) == str(device_id):
        project.settings = {
            **(project.settings or {}),
            "agent_executor": {"kind": "gateway"},
        }
    affected = (
        await db.scalars(
            select(AsyncTask)
            .where(
                AsyncTask.novel_id == novel_id,
                AsyncTask.status.in_(("pending", "running")),
                AsyncTask.meta["_local_device_id"].as_string() == str(device_id),
            )
            .order_by(AsyncTask.id)
        )
    ).all()
    from infrastructure.tasks.lifecycle import TaskLifecycleService

    lifecycle = TaskLifecycleService()
    for task in affected:
        await lifecycle.cancel_exact(
            db,
            task_id=str(task.id),
            task_types={task.task_type},
            novel_id=str(novel_id),
            transition_reason="local_device_revoked",
        )
    await db.commit()
    return {"revoked": True}


@router.post("/tasks/{task_id}/approve")
async def approve_task(db: DbSession, task_id: uuid.UUID, data: LocalApproval):
    await require_active_project(db, str(data.novel_id))
    if not data.acknowledge_full_host_access:
        raise ValidationError("请确认本机 CLI 可使用当前 macOS 用户的文件与命令权限")
    task = await db.get(AsyncTask, task_id, with_for_update=True)
    if (
        task is None
        or task.novel_id != data.novel_id
        or task.status != "pending"
        or not (task.meta or {}).get("_local_agent")
    ):
        raise NotFoundError("待确认的本机任务不存在")
    device = await db.get(LocalAgentDevice, uuid.UUID(task.meta["_local_device_id"]))
    if (
        device is None
        or device.novel_id != data.novel_id
        or device.owner_id != current_account_id()
        or device.revoked_at is not None
    ):
        raise NotFoundError("本机设备不可用")
    ready = bool(
        device.last_seen_at
        and datetime.now(UTC) - _utc(device.last_seen_at) < timedelta(seconds=10)
    )
    task.meta = {**task.meta, "_local_approved": True, "_local_ready": ready}
    from modules.assistant.models import AssistantRun

    run = await db.scalar(
        select(AssistantRun).where(
            AssistantRun.task_id == task_id,
            AssistantRun.novel_id == data.novel_id,
            AssistantRun.owner_id == current_account_id(),
        )
    )
    if run is not None:
        run.checkpoint_json = {**(run.checkpoint_json or {}), "local_approved": True}
    from modules.interaction.models import InteractionGenerationAttempt

    attempt = await db.scalar(
        select(InteractionGenerationAttempt).where(
            InteractionGenerationAttempt.task_id == task_id,
            InteractionGenerationAttempt.novel_id == data.novel_id,
        )
    )
    if attempt is not None:
        attempt.agent_checkpoint_json = {
            **(attempt.agent_checkpoint_json or {}),
            "local_approved": True,
        }
    await db.commit()
    return {"approved": True, "waiting_device": not ready}


@router.post("/companion/claim")
async def claim_invocation(db: DbSession, authorization: str | None = Header(None)):
    device = await _device(db, authorization)
    device.last_seen_at = datetime.now(UTC)
    waiting_tasks = (
        await db.scalars(
            select(AsyncTask)
            .where(
                AsyncTask.novel_id == device.novel_id,
                AsyncTask.status == "pending",
                AsyncTask.meta["_local_agent"].as_boolean().is_(True),
                AsyncTask.meta["_local_approved"].as_boolean().is_(True),
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    for task in waiting_tasks:
        if (task.meta or {}).get("_local_device_id") == str(device.id):
            task.meta = {**task.meta, "_local_ready": True}
    invocation = (
        await db.execute(
            select(LocalAgentInvocation)
            .where(
                LocalAgentInvocation.device_id == device.id,
                LocalAgentInvocation.status == "pending",
            )
            .order_by(LocalAgentInvocation.created_at, LocalAgentInvocation.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if invocation is None:
        await db.commit()
        return {"job": None}
    task = await db.get(AsyncTask, invocation.task_id)
    if (
        task is None
        or task.status != "running"
        or str(task.lease_id) != invocation.request_json.get("task_lease_id")
    ):
        invocation.status = "failed"
        invocation.error = "原始任务已停止或被替代"
        await db.commit()
        return {"job": None}
    lease = uuid.uuid4()
    invocation.lease_id = str(lease)
    invocation.heartbeat_at = datetime.now(UTC)
    invocation.status = "running"
    await db.commit()
    return {
        "job": {
            "id": str(invocation.id),
            "lease_id": str(lease),
            "cli": invocation.cli,
            "request": invocation.request_json,
        }
    }


@router.post("/companion/jobs/{invocation_id}/heartbeat")
async def heartbeat(
    db: DbSession,
    invocation_id: uuid.UUID,
    data: LeaseUpdate,
    authorization: str | None = Header(None),
):
    device = await _device(db, authorization)
    invocation = await _invocation(db, device, invocation_id, data.lease_id)
    invocation.heartbeat_at = datetime.now(UTC)
    device.last_seen_at = invocation.heartbeat_at
    await db.commit()
    return {"active": True}


@router.post("/companion/jobs/{invocation_id}/events")
async def publish_event(
    db: DbSession,
    invocation_id: uuid.UUID,
    data: EventUpdate,
    authorization: str | None = Header(None),
):
    device = await _device(db, authorization)
    invocation = await _invocation(db, device, invocation_id, data.lease_id)
    state = dict(invocation.result_json or {})
    previous = int(state.get("sequence") or 0)
    if data.sequence != previous + 1:
        raise ConflictError("本机事件序号不连续", code="local_agent_event_gap")
    if data.kind == "text":
        text = str(state.get("visible_text") or "") + data.text
        if len(text) > 100000:
            raise ValidationError("本机答案超过上限")
        state["visible_text"] = text
    elif data.kind == "tool":
        attempts = int(state.get("tool_attempts") or 0) + 1
        if attempts > int(invocation.request_json["max_tool_attempts"]):
            raise ValidationError("本机工具调用达到上限")
        state["tool_attempts"] = attempts
    elif data.kind == "usage":
        state["usage"] = data.usage
    state["sequence"] = data.sequence
    invocation.result_json = state
    await db.commit()
    return {"sequence": data.sequence}


@router.post("/companion/jobs/{invocation_id}/tools")
async def request_tool(
    db: DbSession,
    invocation_id: uuid.UUID,
    data: ToolRequest,
    authorization: str | None = Header(None),
):
    device = await _device(db, authorization)
    invocation = await _invocation(db, device, invocation_id, data.lease_id)
    allowed = set(invocation.request_json.get("tools") or {})
    if data.name not in allowed:
        raise ValidationError("工具未在本次任务注册")
    if len(str(data.arguments)) > 50000:
        raise ValidationError("工具参数超过上限")
    call = await db.scalar(
        select(LocalAgentToolCall).where(
            LocalAgentToolCall.invocation_id == invocation_id,
            LocalAgentToolCall.call_id == data.call_id,
        )
    )
    if call is None:
        count = await db.scalar(
            select(func.count(LocalAgentToolCall.id)).where(
                LocalAgentToolCall.invocation_id == invocation_id
            )
        )
        if int(count or 0) >= int(invocation.request_json["max_tool_attempts"]):
            raise ValidationError("本次产品工具调用达到上限")
        call = LocalAgentToolCall(
            invocation_id=invocation_id,
            call_id=data.call_id,
            name=data.name,
            arguments_json=data.arguments,
        )
        db.add(call)
    elif call.name != data.name or call.arguments_json != data.arguments:
        raise ConflictError("工具调用标识已用于其他参数", code="local_agent_call_changed")
    await db.commit()
    return {
        "call_id": data.call_id,
        "pending": call.result_json is None and call.error is None,
    }


@router.get("/companion/jobs/{invocation_id}/tools/{call_id}")
async def tool_result(
    db: DbSession,
    invocation_id: uuid.UUID,
    call_id: str,
    lease_id: uuid.UUID,
    authorization: str | None = Header(None),
):
    device = await _device(db, authorization)
    await _invocation(db, device, invocation_id, lease_id)
    call = await db.scalar(
        select(LocalAgentToolCall).where(
            LocalAgentToolCall.invocation_id == invocation_id,
            LocalAgentToolCall.call_id == call_id,
        )
    )
    if call is None:
        raise NotFoundError("工具调用不存在")
    return {
        "pending": call.status in {"pending", "running"},
        "result": call.result_json,
        "error": call.error,
    }


@router.post("/companion/jobs/{invocation_id}/finish")
async def finish_invocation(
    db: DbSession,
    invocation_id: uuid.UUID,
    data: FinishRequest,
    authorization: str | None = Header(None),
):
    device = await _device(db, authorization)
    invocation = await _invocation(db, device, invocation_id, data.lease_id)
    if data.tool_attempts > int(invocation.request_json["max_tool_attempts"]):
        raise ValidationError("本机工具调用超过上限")
    invocation.status = data.status
    invocation.error = data.error or None
    invocation.result_json = {
        **(invocation.result_json or {}),
        "answer": data.answer if data.status == "completed" else "",
        "tool_attempts": data.tool_attempts,
        "usage": data.usage,
    }
    await db.commit()
    return {"accepted": True}
