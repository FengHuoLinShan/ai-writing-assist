"""Task-scoped automatic approval; no client-supplied approval receipt."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

APPROVAL_POLICY = "author-task-approval-v1"
APPROVAL_CAPABILITY = "assistant.approval.judge"


class ApprovalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApprovalTarget(ApprovalModel):
    kind: Literal["world_entity", "world_relation", "writing_chapter", "creation_slot"]
    id: str = Field(min_length=1, max_length=128)


class TaskApprovalRequest(ApprovalModel):
    preserve: list[str] = Field(default_factory=list, max_length=20)
    max_judgments: int = Field(default=5, ge=1, le=30)
    timeout_seconds: int = Field(default=30, ge=5, le=120)

    @model_validator(mode="after")
    def bounded_requirements(self):
        if any(not item.strip() or len(item) > 1000 for item in self.preserve):
            raise ValueError("每项保留要求须为 1–1000 个字符")
        return self


class ApprovalJudgment(ApprovalModel):
    decision: Literal["allow", "ask", "deny"]
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=500)

    @classmethod
    def for_fingerprint(cls, value: str) -> type[ApprovalJudgment]:
        return create_model(
            "BoundApprovalJudgment", __base__=cls, fingerprint=(Literal[value], ...)
        )


class ApprovalRevocation(ApprovalModel):
    expected_version: int = Field(ge=1)
