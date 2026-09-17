"""Offline gate for adjudicated World design review pairs.

配对只要求相同的"名义冻结上限"（token_budget 标签、模型与 context hash）；
两臂的真实 request cap 与实际累计用量分别记录并分别报告——名义上限不是
运行时累计闸门，报告不得据此宣称"同预算"。
"""


from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorldDesignArmScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    token_budget: int = Field(gt=0)
    """名义冻结上限标签（如 66 x 131072）；不是运行时累计闸门。"""
    request_limit: int = Field(ge=1)
    """该臂真实冻结的请求额度（两臂允许不同）。"""
    requests_used: int = Field(ge=0)
    """该臂实际发出的 provider 请求数（含 transport 重试）。"""
    tokens_used: int = Field(ge=0)
    """该臂实际结算的累计 token 用量；未知用量按 possible 计入请求数。"""
    reasoning_effort: str | None = None
    """该臂实际生效的 reasoning effort（evaluator provenance）。"""
    adjudicated: bool
    severe_goal_errors: int = Field(ge=0)
    severe_causal_errors: int = Field(ge=0)
    false_positive_issues: int = Field(ge=0)
    unnecessary_author_decisions: int = Field(ge=0)
    knowledge_boundary_regressions: int = Field(ge=0)
    project_isolation_regressions: int = Field(ge=0)


class WorldDesignReviewPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    baseline: WorldDesignArmScore
    candidate: WorldDesignArmScore

    @model_validator(mode="after")
    def validate_blind_pair(self) -> WorldDesignReviewPair:
        for field in ("model", "context_hash", "token_budget"):
            if getattr(self.baseline, field) != getattr(self.candidate, field):
                raise ValueError(f"paired arms must share {field}")
        if not self.baseline.adjudicated or not self.candidate.adjudicated:
            raise ValueError("paired arms require completed adjudication")
        return self


def evaluate_world_design_review_pairs(
    pairs: list[WorldDesignReviewPair],
) -> dict[str, object]:
    if not pairs:
        raise ValueError("at least one adjudicated pair is required")
    if len({pair.case_id for pair in pairs}) != len(pairs):
        raise ValueError("duplicate world design review case_id")

    def total(arm: str, field: str) -> int:
        return sum(getattr(getattr(pair, arm), field) for pair in pairs)

    baseline_severe = total("baseline", "severe_goal_errors") + total(
        "baseline", "severe_causal_errors"
    )
    candidate_severe = total("candidate", "severe_goal_errors") + total(
        "candidate", "severe_causal_errors"
    )
    baseline_friction = total("baseline", "false_positive_issues") + total(
        "baseline", "unnecessary_author_decisions"
    )
    candidate_friction = total("candidate", "false_positive_issues") + total(
        "candidate", "unnecessary_author_decisions"
    )
    candidate_boundary_regressions = total(
        "candidate", "knowledge_boundary_regressions"
    ) + total("candidate", "project_isolation_regressions")
    gates = {
        "severe_errors_reduced": candidate_severe < baseline_severe,
        "false_positives_not_increased": candidate_friction <= baseline_friction,
        "knowledge_and_project_isolation_zero_regression": (
            candidate_boundary_regressions == 0
        ),
    }
    return {
        "case_count": len(pairs),
        "baseline_requests_used": total("baseline", "requests_used"),
        "candidate_requests_used": total("candidate", "requests_used"),
        "baseline_tokens_used": total("baseline", "tokens_used"),
        "candidate_tokens_used": total("candidate", "tokens_used"),
        "baseline_severe_errors": baseline_severe,
        "candidate_severe_errors": candidate_severe,
        "baseline_review_friction": baseline_friction,
        "candidate_review_friction": candidate_friction,
        "candidate_boundary_regressions": candidate_boundary_regressions,
        "gates": gates,
        "enabled": all(gates.values()),
    }
