"""Import write risk classifier for Worldbuilding Workspace v1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LOW_RISK_TARGETS = {
    "core_entity",
    "profile",
    "generic_profile",
    "relation_candidate",
    "material_page",
}

HIGH_RISK_TARGETS = {
    "character_knowledge",
    "visibility_policy",
    "reader_reveal",
    "private_tag",
    "manual_tag",
    "triggered_tag",
    "narrative_secret_grant",
}

CONFIRMED_STATUSES = {"canonical", "confirmed"}


@dataclass(frozen=True)
class ImportRiskDecision:
    risk_level: str
    reason: str
    target_type: str


class ImportWriteRiskClassifier:
    """Classify imported worldbuilding candidates before persistence."""

    def classify(self, candidate: dict[str, Any]) -> ImportRiskDecision:
        target_type = str(candidate.get("target_type") or "unknown")
        if target_type in LOW_RISK_TARGETS:
            return ImportRiskDecision(
                "low",
                "objective draft/candidate asset",
                target_type,
            )
        if target_type in HIGH_RISK_TARGETS:
            return ImportRiskDecision("high", "narrative knowledge choice", target_type)
        if target_type == "derived_public_tag":
            source_status = str(candidate.get("source_status") or "")
            blocked = bool(candidate.get("exclusion_blocked"))
            profession_confirmed = bool(candidate.get("profession_confirmed", True))
            if (
                source_status in CONFIRMED_STATUSES
                and not blocked
                and profession_confirmed
            ):
                return ImportRiskDecision(
                    "medium",
                    "confirmed derived public tag",
                    target_type,
                )
            return ImportRiskDecision(
                "high",
                "derived tag source is not confirmed or is blocked",
                target_type,
            )
        return ImportRiskDecision("high", "unknown import target type", target_type)
