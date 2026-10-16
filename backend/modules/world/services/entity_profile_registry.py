"""CoreEntity 强 Profile 类型注册表 — world 内共享词汇。

AO-5 / ADR-0031：实体类型 → Profile 模型绑定是 CoreEntity 领域的共享词汇，
core（实体类型迁移）与 worldbuilding（Profile CRUD）两侧都消费。原放在
``services/worldbuilding/shared.py`` 迫使 core 反向依赖 worldbuilding；
现上移到 world services 共享根，两侧平级导入，不计入子包方向流量。
"""

from __future__ import annotations

from dataclasses import dataclass

from modules.world.models import (
    FactionProfile,
    ItemProfile,
    LocationProfile,
    RuleProfile,
    SecretProfile,
    SpeciesProfile,
)


@dataclass(frozen=True)
class ProfileBinding:
    model: type
    fields: tuple[str, ...]
    dossier_fields: dict[str, tuple[str, str]]


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
        {
            "origin_summary": ("history", "public"),
            "physiology_summary": ("physiology_lifespan", "public"),
            "lifespan": ("physiology_lifespan", "public"),
            "abilities_json": ("abilities_weaknesses", "public"),
            "weaknesses_json": ("abilities_weaknesses", "public"),
            "culture_summary": ("culture_customs", "public"),
            "language_summary": ("language", "public"),
        },
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
        {
            "ideology_summary": ("ideology", "public"),
            "leader_entity_ids_json": ("structure_positions", "public"),
            "member_rules": ("rules", "public"),
            "territory_refs_json": ("resources", "public"),
            "resources_json": ("resources", "public"),
        },
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
        {
            "map_refs_json": ("geography", "public"),
            "climate": ("sensory_details", "public"),
            "population_summary": ("appearance_people", "public"),
            "resources_json": ("resources", "public"),
            "hazards_json": ("dangers", "public"),
        },
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
        {
            "rule_domain": ("known_scope", "public"),
            "principle_summary": ("principle", "public"),
            "constraints_json": ("constraints", "public"),
            "exceptions_json": ("exceptions", "public"),
            "consequences_json": ("consequences", "public"),
        },
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
        {
            "item_class": ("form_appearance", "public"),
            "powers_json": ("abilities_limits", "public"),
            "limitations_json": ("abilities_limits", "public"),
            "origin_summary": ("origin", "public"),
        },
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
        {
            "truth_summary": ("truth", "secret"),
            "risk_level": ("risk", "secret"),
            "linked_target_refs_json": ("reveal_plan", "secret"),
        },
    ),
}

__all__ = ["PROFILE_REGISTRY", "ProfileBinding"]
