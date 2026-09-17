"""Offline same-budget gate for adjudicated World design review pairs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorldDesignArmScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    token_budget: int = Field(gt=0)
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
        "baseline_severe_errors": baseline_severe,
        "candidate_severe_errors": candidate_severe,
        "baseline_review_friction": baseline_friction,
        "candidate_review_friction": candidate_friction,
        "candidate_boundary_regressions": candidate_boundary_regressions,
        "gates": gates,
        "enabled": all(gates.values()),
    }
