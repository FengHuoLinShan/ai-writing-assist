"""Stable task lifecycle contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

RecoveryPolicy = Literal[
    "auto_requeue",
    "manual_resume",
    "restart_origin",
    "never_retry",
]
TaskAction = Literal[
    "cancel",
    "retry",
    "resume",
    "abandon",
    "restart_origin",
    "dismiss",
]
TaskCoalescingMode = Literal["reuse_active", "one_pending_follower"]
TaskOwnerScope = Literal["project", "global"]


@dataclass(frozen=True)
class TaskDefinition:
    task_type: str
    handler: Any
    recovery_policy: RecoveryPolicy = "restart_origin"
    max_attempts: int = 1
    generic_submit_schema: type[BaseModel] | None = None
    owner_scope: TaskOwnerScope = "project"
    retry_transient_llm_errors: bool = False
    # 领域按 L0 = min(A, H) 冻结的一次 run 请求额度：静态 int，或从任务冻结
    # 输入（meta/plan）计算 A 的同步 callable。None 表示该任务尚未迁移出
    # 过渡计量额度，不得据此放行无限请求。
    run_request_limit: int | Any = None
    # 一次 run 的 deadline（秒）：静态 float，或从冻结输入计算的同步 callable。
    # None 表示无统一 deadline，既有更短 provider/step timeout 继续生效。
    run_deadline_seconds: float | Any = None


@dataclass(frozen=True)
class CoalescedTaskContract:
    """Secret-free result of one keyed enqueue/lookup operation."""

    task_id: str
    status: str
    reused: bool


@dataclass(frozen=True)
class TaskLifecycleContract:
    task_id: str
    task_type: str
    status: str
    attempt: int
    max_attempts: int
    recovery_policy: str
    lease_id: str | None = None
    heartbeat_at: str | None = None
    stale_detected_at: str | None = None
    transition_reason: str | None = None
    stale: bool = False
    recovery_required: bool = False
    available_actions: list[TaskAction] = field(default_factory=list)


@dataclass(frozen=True)
class TaskOwnerContract:
    """Minimal owner projection for authorization checks outside tasks."""

    novel_id: str


@dataclass(frozen=True)
class CompletedTaskPayloadContract:
    """Detached source payload for a novel-scoped completed task.

    Business modules use this projection when an explicit apply operation must
    validate the frozen task result without importing the task ORM. Only the
    small, stable apply context below crosses the infrastructure boundary;
    arbitrary task metadata remains private to the task subsystem.
    """

    task_id: str
    task_type: str
    novel_id: str
    result: dict[str, Any] = field(default_factory=dict)
    revision_token: datetime | None = None
    context_confirmation_id: str | None = None
    action: str | None = None
    context_provenance: dict[str, Any] = field(default_factory=dict)
    start_chapter: int | None = None
    end_chapter: int | None = None
