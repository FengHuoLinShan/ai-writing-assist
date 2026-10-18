"""Strict wire contracts for goal-run plans and author decisions."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.assistant.approval_contracts import TaskApprovalRequest


class GoalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoalBudget(GoalModel):
    requests: int = Field(ge=2, le=100)
    possible_charge_requests: int = Field(ge=2, le=100)
    tokens: int = Field(ge=512, le=500_000)
    time_limit_seconds: int = Field(ge=60, le=7_200)

    @model_validator(mode="after")
    def charge_budget_fits_requests(self) -> GoalBudget:
        if self.possible_charge_requests > self.requests:
            raise ValueError("可能产生费用的请求数不能超过总请求数")
        return self


class GoalReference(GoalModel):
    step_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    path: list[str | int] = Field(min_length=1, max_length=8)
    value_type: Literal[
        "string", "identifier", "integer", "number", "boolean", "object", "array"
    ]
    item_type: (
        Literal["string", "identifier", "integer", "number", "boolean", "object", "array"]
        | None
    ) = None
    max_items: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def validate_type_options(self) -> GoalReference:
        if self.value_type == "array":
            if self.max_items is None:
                raise ValueError("数组引用必须声明 1–20 项的展开上限")
        elif self.item_type is not None or self.max_items is not None:
            raise ValueError("只有数组引用可以声明元素类型或展开上限")
        for part in self.path:
            if isinstance(part, str) and (
                not part or len(part) > 64 or part.startswith("_") or "__" in part
            ):
                raise ValueError("引用路径只能使用公开字段名")
            if isinstance(part, int) and part < 0:
                raise ValueError("引用列表索引不能为负数")
        return self


class GoalTarget(GoalModel):
    target_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    target_id: str | GoalReference

    @model_validator(mode="after")
    def validate_literal_target(self) -> GoalTarget:
        if isinstance(self.target_id, str) and (
            not self.target_id.strip() or len(self.target_id) > 128
        ):
            raise ValueError("目标标识不能为空且最多 128 个字符")
        return self


class GoalStep(GoalModel):
    step_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    operation_id: str = Field(min_length=3, max_length=160, pattern=r"^[a-zA-Z0-9_.-]+$")
    depends_on: list[str] = Field(default_factory=list, max_length=30)
    targets: list[GoalTarget] = Field(default_factory=list, max_length=20)
    parameters: dict[str, Any] = Field(default_factory=dict)
    intent: str = Field(min_length=1, max_length=1200)


class GoalPlan(GoalModel):
    title: str = Field(min_length=1, max_length=180)
    summary: str = Field(default="", max_length=1600)
    steps: list[GoalStep] = Field(min_length=1, max_length=30)


class GoalOperationSelection(GoalModel):
    operation_ids: list[str] = Field(min_length=1, max_length=30)


class GoalRunStart(GoalModel):
    novel_id: UUID
    request_id: UUID
    goal: str = Field(min_length=1, max_length=6000)
    budget: GoalBudget
    source_session_id: UUID | None = None

    @model_validator(mode="after")
    def validate_goal_text(self) -> GoalRunStart:
        if not self.goal.strip():
            raise ValueError("请先写下希望完成的目标")
        return self


class GoalPlanApproval(GoalModel):
    expected_revision: int = Field(ge=1)
    plan: GoalPlan
    budget: GoalBudget
    auto_r2: bool = False
    approval: TaskApprovalRequest | None = None


class GoalStepApproval(GoalModel):
    expected_revision: int = Field(ge=1)
    step_id: str = Field(min_length=1, max_length=64)
    approve: bool = True


class GoalOutcomeReconciliation(GoalModel):
    expected_revision: int = Field(ge=1)
    decision: Literal["applied", "not_applied", "still_unknown"]


class GoalWritingReceiptLocation(GoalModel):
    kind: Literal["writing_candidate"]
    candidate_id: UUID
    chapter_index: int = Field(ge=1, le=2147483647)


class GoalTaskReceiptLocation(GoalModel):
    kind: Literal["smart_dedup_scan"]
    task_id: UUID


class GoalSceneReceiptLocation(GoalModel):
    kind: Literal["scene_story_assets"]
    scene_id: UUID


GoalReceiptLocation = Annotated[
    GoalWritingReceiptLocation | GoalTaskReceiptLocation | GoalSceneReceiptLocation,
    Field(discriminator="kind"),
]


class GoalReceiptPreview(GoalModel):
    """Safe, bounded projection of the exact domain receipt for author review."""

    expected_revision: int = Field(ge=1)
    status: Literal[
        "verified_applied",
        "verified_not_applied",
        "incomplete",
        "stale",
        "unverified",
    ]
    summary: str = Field(max_length=500)
    details: list[str] = Field(default_factory=list, max_length=8)
    available_decisions: list[Literal["applied", "not_applied"]] = Field(
        default_factory=list, max_length=2
    )
    destination: GoalReceiptLocation | None = None


class GoalResume(GoalModel):
    expected_revision: int = Field(ge=1)
    budget: GoalBudget


class GoalAction(GoalModel):
    expected_revision: int = Field(ge=1)


class GoalReplanRequest(GoalModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1200)
