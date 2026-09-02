"""Copyright-safe blind comparison ledger for RP source context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean

from modules.writing.contracts import SourceRangeRefContract

RUBRIC_VERSION = "rp-context-v1"
RUBRIC_DIMENSIONS = (
    "character_voice",
    "ability_boundaries",
    "relationship_consistency",
    "timeline_consistency",
    "character_knowledge",
    "spoiler_control",
    "journey_branch_consistency",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RPContextEvalCase:
    case_id: str
    corpus_hash: str
    scenario_hash: str
    source_refs: tuple[SourceRangeRefContract, ...]
    rubric_version: str = RUBRIC_VERSION


@dataclass(frozen=True)
class RPBlindReview:
    case_id: str
    candidate: str
    scores: dict[str, int]
    severe_spoiler: bool = False


def load_case(value: dict) -> RPContextEvalCase:
    if set(value) - {
        "case_id",
        "corpus_hash",
        "scenario_hash",
        "source_refs",
        "rubric_version",
    }:
        raise ValueError("RP eval cases may contain only hashes and SourceRangeRefs")
    corpus_hash = str(value.get("corpus_hash") or "")
    scenario_hash = str(value.get("scenario_hash") or "")
    if not _SHA256.fullmatch(corpus_hash) or not _SHA256.fullmatch(scenario_hash):
        raise ValueError("RP eval cases store hashes, never source or scenario text")
    refs = tuple(
        SourceRangeRefContract(**item) for item in value.get("source_refs") or []
    )
    if not refs:
        raise ValueError("RP eval case requires at least one exact SourceRangeRef")
    return RPContextEvalCase(
        case_id=str(value["case_id"]),
        corpus_hash=corpus_hash,
        scenario_hash=scenario_hash,
        source_refs=refs,
        rubric_version=str(value.get("rubric_version") or RUBRIC_VERSION),
    )


def summarize_blind_reviews(
    reviews: list[RPBlindReview],
    *,
    arm_by_candidate: dict[str, str],
) -> dict:
    by_arm: dict[str, list[float]] = {"context_on": [], "context_off": []}
    spoiler_by_arm = {"context_on": False, "context_off": False}
    for review in reviews:
        arm = arm_by_candidate.get(review.candidate)
        if arm not in by_arm:
            raise ValueError("candidate arm mapping must be revealed after blind scoring")
        if set(review.scores) != set(RUBRIC_DIMENSIONS):
            raise ValueError("blind review must score every RP rubric dimension")
        if any(score < 0 or score > 4 for score in review.scores.values()):
            raise ValueError("RP rubric scores must be between 0 and 4")
        by_arm[arm].append(mean(review.scores.values()))
        spoiler_by_arm[arm] |= review.severe_spoiler
    if not all(by_arm.values()):
        raise ValueError("both context arms require blind reviews")
    on_score = mean(by_arm["context_on"])
    off_score = mean(by_arm["context_off"])
    severe_spoiler_regression = (
        spoiler_by_arm["context_on"] and not spoiler_by_arm["context_off"]
    )
    return {
        "context_on_mean": on_score,
        "context_off_mean": off_score,
        "directional_delta": on_score - off_score,
        "severe_spoiler_regression": severe_spoiler_regression,
        "claim_allowed": on_score > off_score and not severe_spoiler_regression,
        "note": "blind comparison is directional evidence, not a completed user trial",
    }
