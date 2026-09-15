"""知识治理 LLM 步骤的结构化输出 schema（导演分片 / 审查裁决）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from modules.evidence.compilation.knowledge.contracts import (
    AUDIT_FINDING_KINDS,
    DIRECTOR_DISPOSITIONS,
)


class DirectorShardDisposition(BaseModel):
    """导演对单个来源 key 的处置；reason 只允许短说明。"""

    source_key: str = Field(min_length=1)
    disposition: Literal[
        "required_for_generation",
        "allowed_for_generation",
        "director_audit_only",
        "forbidden",
    ]
    reason: str = Field(default="", max_length=200)


class DirectorShardPlan(BaseModel):
    """单个 manifest 分片的处置结果。"""

    dispositions: list[DirectorShardDisposition] = Field(default_factory=list)


class AuditFindingOutput(BaseModel):
    """审查发现；message 不得复述隐藏事实原文，excerpt 只定位生成输出。"""

    kind: Literal[
        "missing_required",
        "unsupported_fact",
        "out_of_scope_knowledge",
        "premature_reveal",
        "irrelevant_content",
        "conflict",
        "unchecked",
    ]
    severity: Literal["blocker", "major", "minor"]
    message: str = Field(min_length=1, max_length=1000)
    excerpt: str = Field(default="", max_length=500)
    source_key: str | None = None


class AuditDimensionCheck(BaseModel):
    dimension: str = Field(min_length=1, max_length=64)
    checked: bool = True
    note: str = Field(default="", max_length=500)


class AuditVerdictOutput(BaseModel):
    """审查者裁决；最终 verdict 由服务端按 finding 强制收口。"""

    findings: list[AuditFindingOutput] = Field(default_factory=list)
    dimensions: list[AuditDimensionCheck] = Field(default_factory=list)
    verdict: Literal["pass", "blocked", "not_checked", "unverifiable"]


assert set(DIRECTOR_DISPOSITIONS) == {
    "required_for_generation",
    "allowed_for_generation",
    "director_audit_only",
    "forbidden",
}
assert set(AUDIT_FINDING_KINDS) == {
    "missing_required",
    "unsupported_fact",
    "out_of_scope_knowledge",
    "premature_reveal",
    "irrelevant_content",
    "conflict",
    "unchecked",
}
