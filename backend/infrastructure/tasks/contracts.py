"""Stable task lifecycle contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

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


@dataclass(frozen=True)
class TaskDefinition:
    task_type: str
    handler: Any
    recovery_policy: RecoveryPolicy = "restart_origin"
    max_attempts: int = 1


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
