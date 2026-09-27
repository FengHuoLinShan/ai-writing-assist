"""Strict author-facing inputs and model output, without caller-owned identity."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


TASK_HINTS = (
    "unknown",
    "continue",
    "polish",
    "revise",
    "design",
    "retrieve",
    "review",
    "organize",
    "roleplay",
)
"""作者意图封闭集（R00）。turn 与 forecast 共用；"polish" 在 forecast 侧
还会收窄能力集（runtime 只保留非扩情节项）。"""

TaskHint = Literal[
    "unknown",
    "continue",
    "polish",
    "revise",
    "design",
    "retrieve",
    "review",
    "organize",
    "roleplay",
]

TASK_HINT_DIRECTIVES = {
    "continue": "续写：只推进作者指定方向的下文，不回改已发布内容。",
    "polish": "只润色：仅改进指定内容的文字表达，不得扩大情节、新增设定或改动事实。",
    "revise": "修改：按作者要求改动指定内容，改法先说明再动手。",
    "design": "设定设计：只产出设定草案与理由，不直接改正文。",
    "retrieve": "查证：优先检索并给出出处，不确定就明说。",
    "review": "检查：逐条给出问题与依据，不主动改写。",
    "organize": "整理：归纳现状与待办，不新增创作决定。",
    "roleplay": "演绎：保持角色视角与已建立的世界事实。",
}
"""意图 → 模型输入中的行为边界（R00：作者意图实际进入模型输入）。"""


def work_directive(work: WorkContext) -> str:
    """turn 最终 user 消息里的意图指令行；unknown 不注入。"""
    if work.task_hint in TASK_HINT_DIRECTIVES:
        return f"作者意图：{TASK_HINT_DIRECTIVES[work.task_hint]}"
    return ""


def verify_selection_range(draft_content: str, work: WorkContext) -> None:
    """服务端 SourceRange 一致性（R00）：选区文本必须逐字来自绑定草稿
    的声称偏移范围——漂移即失败关闭，不带着失真的选区进模型。

    偏移按 Unicode 码点计数（与前端 ``Array.from`` 计数一致）。
    """
    if work.selection_start is None and work.selection_end is None:
        return
    if work.draft_id is None:
        raise ValueError("选区偏移必须绑定正文草稿")
    start, end = work.selection_start, work.selection_end
    if len(work.selection) != end - start or end > len(draft_content):
        raise ValueError("选区偏移与选区文本不一致")
    if draft_content[start:end] != work.selection:
        raise ValueError("选区与当前正文不一致，请重新选择")


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
    task_hint: TaskHint = "unknown"
    selection_start: int | None = Field(default=None, ge=0)
    selection_end: int | None = Field(default=None, ge=0)
    scope: Literal["current", "project"] = "current"
    excluded_targets: list[str] = Field(default_factory=list, max_length=200)
    context_confirmation_id: UUID | None = None
    context_confirmation_action: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def require_selection_range_pair(self):
        # R00：偏移成对出现，且必须绑定草稿与非空选区；逐字一致性在
        # submit 载入草稿后经 verify_selection_range 复核（码点计数）。
        start, end = self.selection_start, self.selection_end
        if (start is None) != (end is None):
            raise ValueError("选区偏移必须成对")
        if start is None:
            return self
        if not self.selection:
            raise ValueError("选区偏移需要非空选区")
        if self.draft_id is None:
            raise ValueError("选区偏移必须绑定正文草稿")
        if len(self.selection) != end - start:
            raise ValueError("选区偏移与选区文本长度不一致")
        return self

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
    can_resume: bool = False
    updated_at: datetime | None
    local_agent: dict[str, Any] | None = None


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
    review_after: bool = False


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
