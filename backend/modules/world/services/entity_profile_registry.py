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

__all__ = ["PROFILE_REGISTRY", "ProfileBinding"]
