"""Shared worldbuilding constants and profile registry."""

from __future__ import annotations

import re
from dataclasses import dataclass

from modules.world.models import (
    FactionProfile,
    ItemProfile,
    LocationProfile,
    RuleProfile,
    SecretProfile,
    SpeciesProfile,
)

CONFIRMED_STATUSES = {"canonical", "confirmed"}
STRONG_PROFILE_TYPES = {"species", "faction", "location", "rule", "item", "secret"}
GENERIC_PROFILE_TYPES = {
    "group",
    "creature",
    "skill",
    "other",
    "concept",
    "resource",
    "legend",
    "power_system",
}

_PROFESSION_SLUG_RE = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True)
class ProfileBinding:
    model: type
    fields: tuple[str, ...]


PROFILE_REGISTRY: dict[str, ProfileBinding] = {
    "species": ProfileBinding(
        SpeciesProfile,
        (
            "origin_summary",
            "physiology_summary",
            "lifespan",
            "abilities_json",
            "weaknesses_json",
            "culture_summary",
            "language_summary",
            "public_baseline",
        ),
    ),
    "faction": ProfileBinding(
        FactionProfile,
        (
            "ideology_summary",
            "leader_entity_ids_json",
            "member_rules",
            "territory_refs_json",
            "resources_json",
            "public_baseline",
        ),
    ),
    "location": ProfileBinding(
        LocationProfile,
        (
            "map_refs_json",
            "climate",
            "population_summary",
            "resources_json",
            "hazards_json",
            "controlling_faction_ids_json",
        ),
    ),
    "rule": ProfileBinding(
        RuleProfile,
        (
            "rule_domain",
            "principle_summary",
            "constraints_json",
            "exceptions_json",
            "consequences_json",
        ),
    ),
    "item": ProfileBinding(
        ItemProfile,
        (
            "item_class",
            "powers_json",
            "limitations_json",
            "owner_entity_ids_json",
            "origin_summary",
        ),
    ),
    "secret": ProfileBinding(
        SecretProfile,
        (
            "truth_summary",
            "holder_entity_ids_json",
            "risk_level",
            "reveal_status",
            "linked_target_refs_json",
        ),
    ),
}


def normalize_profession_slug(label: str) -> str:
    slug = _PROFESSION_SLUG_RE.sub("_", label.strip().lower()).strip("_")
    return slug[:128]

__all__ = [
    "CONFIRMED_STATUSES",
    "GENERIC_PROFILE_TYPES",
    "PROFILE_REGISTRY",
    "STRONG_PROFILE_TYPES",
    "ProfileBinding",
    "normalize_profession_slug",
]
