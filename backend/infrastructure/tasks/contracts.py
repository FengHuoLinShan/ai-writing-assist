"""Stable task lifecycle contracts."""

from __future__ import annotations

from collections.abc import Callable
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
TaskSubmissionMode = Literal[
    "append",
    "exact_operation",
    "reuse_active",
    "one_pending_follower",
    "legacy",
]
TaskOwnerScope = Literal["project", "global"]
TASK_SUBMISSION_MODE_META_KEY = "_task_submission_mode"


class TaskOperationProjectionV1(BaseModel):
    """Versioned, author-safe projection for one asynchronous operation."""

    version: Literal[1] = 1
    submission_mode: TaskSubmissionMode
    stage: str
    error_code: str | None
    retryable: bool
    possible_charge: bool
    partial_result: bool
    available_actions: list[TaskAction]


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
    # 输入（meta/plan）计算 A 的同步 callable。声明 root capability 的任务
    # 必须同时提供该字段；未声明 root 的任务保持旧行为且不建立信封。
    run_request_limit: int | Any = None
    run_budget_policy: Any = None
    # 一次 run 的累计 token 用量上限：静态 int，或同步 callable；None 表示只受
    # 请求额度约束。闸门按已结算用量判定，越界后拒绝新请求。
    run_token_limit: int | Any = None
    # 一次 run 的 deadline（秒）：静态 float，或从冻结输入计算的同步 callable。
    # None 表示无统一 deadline，既有更短 provider/step timeout 继续生效。
    run_deadline_seconds: float | Any = None
    # Optional stable domain run id resolver for task types whose authoritative
    # run spans multiple queue rows. Operation id uses the same stable value.
    run_id: str | Any = None
    # Optional domain-owned mirror for a run envelope whose authoritative
    # checkpoint lives beside the queue task (for example an interaction
    # generation attempt).  The callback runs in the worker's checkpoint
    # transaction and must only write its narrow private JSON projection.
    run_envelope_checkpoint: Any = None
    # Opt-in for a bounded author R4 task. Legacy V1 task semantics stay intact.
    unknown_charge_policy: str | None | Callable[[Any], str | None] = None
    run_eighty_percent_stop: bool | Callable[[Any], bool] = False


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
    operation: TaskOperationProjectionV1
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
class TaskOverviewItemContract:
    """Author-safe projection of one in-flight or recent-terminal project task.

    Consumers on the browser path must apply the same public meta filtering as
    the single-task status API (strip underscore-prefixed keys and the
    operation fingerprint) before serializing; this contract keeps the raw meta
    so the API projection stays the single wire authority.
    """

    task_id: str
    task_type: str
    status: str
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    heartbeat_at: str | None
    attempt: int
    max_attempts: int
    stale: bool
    meta: dict[str, Any]
    operation: TaskOperationProjectionV1
    lifecycle_reason: str | None
    recovery_policy: str
    recovery_required: bool
    available_actions: list[TaskAction]
    error_message: str | None


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
