"""Strict author-facing inputs and model output, without caller-owned identity."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkContext(StrictModel):
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    page: Literal[
        "today",
        "world",
        "writing",
        "outline",
        "scene",
        "map",
        "rag",
        "project",
        "generate",
    ] = "today"
    chapter_index: int | None = Field(default=None, ge=1)
    scene_id: UUID | None = None
    target: dict[str, Any] | None = None
    draft_id: UUID | None = None
    source_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    selection: str = Field(default="", max_length=30000)
    scope: Literal["current", "project"] = "current"
    excluded_targets: list[str] = Field(default_factory=list, max_length=200)
    context_confirmation_id: UUID | None = None
    context_confirmation_action: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def require_confirmation_action(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("请选择有效时区") from error
        if bool(self.context_confirmation_id) != bool(self.context_confirmation_action):
            raise ValueError("A frozen context requires its original action and ID")
        if self.context_confirmation_id and self.excluded_targets:
            raise ValueError("请先在参考资料中更新排除项并重新确认")
        return self


class SessionCreate(StrictModel):
    novel_id: UUID
    title: str = Field(default="项目助手", min_length=1, max_length=200)


class RunResponse(StrictModel):
    id: UUID
    session_id: UUID | None
    status: Literal[
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "waiting_approval",
        "budget_exceeded",
    ]
    result: dict[str, Any]
    usage: dict[str, Any]
    error: str | None
    task_id: UUID | None
    updated_at: datetime | None


class RunResume(StrictModel):
    novel_id: UUID
    renew_budget: bool = False
    operation_id: UUID | None = None

    @model_validator(mode="after")
    def renewal_id(self):
        if self.renew_budget != bool(self.operation_id):
            raise ValueError("A new budget requires a new operation receipt")
        return self


class BatchRecheck(StrictModel):
    novel_id: UUID
    operation_id: UUID


class RunEvent(StrictModel):
    sequence: int = Field(ge=1)
    phase: str
    at: datetime
    requests: int = Field(default=0, ge=0)
    tool_attempts: int = Field(default=0, ge=0)


class RunEventsResponse(StrictModel):
    events: list[RunEvent]
    cursor: int
    reset_required: bool
    run: RunResponse


class TurnCreate(StrictModel):
    novel_id: UUID
    operation_id: UUID
    message: str = Field(min_length=1, max_length=20000)
    context: WorkContext = Field(default_factory=WorkContext)
    allow_web: bool = True
    web_backend: Literal["searxng-v1"] | None = None


class ProposedAction(StrictModel):
    key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    capability: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,80}$")
    title: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=2000)
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def reject_identity(self):
        if {
            "novel_id",
            "owner_id",
            "account_id",
            "provider",
            "api_key",
            "confirmed",
            "authorization_confirmed",
        }.intersection(self.arguments):
            raise ValueError("Identity and authorization are server-owned")
        return self


class AgentFinding(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=3000)
    kind: Literal["issue", "suggestion", "reminder"] = "suggestion"
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    domain_finding_id: str | None = Field(default=None, max_length=128)


class AssistantAnswer(StrictModel):
    answer: str = Field(min_length=1, max_length=30000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    actions: list[ProposedAction] = Field(default_factory=list, max_length=20)
    findings: list[AgentFinding] = Field(default_factory=list, max_length=10)
    omissions: list[str] = Field(default_factory=list, max_length=20)
    next_steps: list[
        Literal[
            "project_import",
            "writing",
            "world",
            "world_review",
            "story",
            "map",
            "references",
            "model_settings",
            "project_settings",
            "world_generation",
            "writing_generation",
        ]
    ] = Field(
        default_factory=list,
        max_length=5,
        description="仅在需要受控界面或专业编辑时给出入口，不代替可直接完成的任务",
    )


CONTROLLED_DESTINATIONS = {
    "project_import": "选择文件并导入作品",
    "writing": "打开正文与历史版本",
    "world": "打开世界资料",
    "world_review": "审阅世界成果",
    "story": "打开故事结构",
    "map": "打开地图与图片工作台",
    "references": "查找与选择参考资料",
    "model_settings": "设置模型连接",
    "project_settings": "调整作品偏好",
    "world_generation": "打开世界共创工作台",
    "writing_generation": "准备正文生成与参考资料",
}


class BatchDecision(StrictModel):
    novel_id: UUID
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected: list[str] = Field(default_factory=list, max_length=20)
    confirmed: Literal[True]
    retry_operation_id: UUID | None = None


class NoticeDisposition(StrictModel):
    action: Literal["read", "snooze", "ignore", "intentional"]
    until: datetime | None = None


class NoticeDecision(NoticeDisposition):
    novel_id: UUID


class NoticeRecheck(StrictModel):
    operation_id: UUID


class ProactivePolicy(StrictModel):
    enabled: bool = False
    allow_web: bool = False
    web_backend: Literal["searxng-v1"] | None = None
    daily_limit: int = Field(default=12, ge=1, le=100)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    categories: list[Literal["writing", "world", "story", "imports", "interaction"]] = (
        Field(
            default_factory=lambda: [
                "writing",
                "world",
                "story",
                "imports",
            ]
        )
    )
    excluded_targets: list[str] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def valid_timezone(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("请选择有效时区") from error
        return self


class ProactivePolicyUpdate(StrictModel):
    novel_id: UUID
    policy: ProactivePolicy
