"""Typed judgments are evidence claims, never persistence authorization."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = "imports.review_resolution.v1"
MAX_GROUP_REQUESTS = 3


class ReviewResolutionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    version: Literal["imports.review_resolution.v1"] = VERSION
    repair_scenes: bool = True


class ReviewResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    novel_id: str
    start_chapter: int = Field(default=1, ge=1)
    end_chapter: int = Field(default=0, ge=0)
    asset_keys: list[str] = Field(default_factory=list, max_length=10000)
    repair_scenes: bool = True
    authorization_confirmed: Literal[True]

    @model_validator(mode="after")
    def validate_range(self):
        if self.end_chapter and self.end_chapter < self.start_chapter:
            raise ValueError("结束章节不能早于起始章节")
        if len(set(self.asset_keys)) != len(self.asset_keys):
            raise ValueError("整理范围含重复资料")
        return self


class ReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_key: str
    quote: str = Field(min_length=1, max_length=4000)


class CandidateJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_key: str
    support: Literal["explicit", "inference", "unsupported", "conflict", "uncertain"]
    identity: Literal["unique", "ambiguous", "secret", "local", "generic"]
    persistence: Literal["stable", "episodic", "changed", "ended", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    field_evidence: dict[str, list[ReviewEvidence]] = Field(default_factory=dict)
    counter_evidence: list[ReviewEvidence] = Field(default_factory=list, max_length=32)
    uncertainties: list[str] = Field(default_factory=list, max_length=16)
    explanation: str = Field(min_length=1, max_length=1500)
    question: str = Field(default="", max_length=500)
    missing_evidence: list[str] = Field(default_factory=list, max_length=8)


class ReviewProblemGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_keys: list[str] = Field(min_length=2, max_length=32)
    question: str = Field(min_length=1, max_length=500)
    common_basis: str = Field(min_length=1, max_length=1000)


class ReviewJudgments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    judgments: list[CandidateJudgment] = Field(max_length=32)
    groups: list[ReviewProblemGroup] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [item.candidate_key for item in self.judgments]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate candidate judgment")
        return self


def judgment_outcome(
    judgment: CandidateJudgment, *, required_fields: set[str], valid_evidence: bool
) -> tuple[str, str]:
    """Fail closed on source failure; uncertainty is not an execution failure."""
    if not valid_evidence:
        return "incomplete", "source_unverified"
    if (
        judgment.identity in {"ambiguous", "secret"}
        or judgment.support == "conflict"
        or judgment.persistence in {"changed", "ended"}
    ):
        return "decision", "identity_or_fact_conflict"
    if judgment.identity in {"local", "generic"} or judgment.persistence == "episodic":
        return "optional", "scene_local_observation"
    if (
        judgment.support != "explicit"
        or judgment.persistence != "stable"
        or judgment.confidence < 0.90
        or judgment.uncertainties
        or judgment.missing_evidence
        or judgment.counter_evidence
    ):
        return "optional", "insufficient_support"
    if not required_fields <= {
        key for key, refs in judgment.field_evidence.items() if refs
    }:
        return "optional", "unverified_fields"
    return "eligible", "explicit_supported_fact"


class ReviewResolutionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_keys: list[str] = Field(min_length=1, max_length=32)
    expected_fingerprints: dict[str, str]
    confirmed: Literal[True]


class SceneResolutionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_fingerprint: str = Field(min_length=64, max_length=64)
    confirmed: Literal[True]
