"""Seed simulation only from exact, typed, current Scene-state references."""

from __future__ import annotations

from modules.story.rehearsals import validate_simulation_context_refs
from modules.story.simulation_v3 import (
    SimulationPosition,
    SimulationReference,
    SimulationResourceHolder,
    SimulationV3Context,
)


def _exact(item: dict) -> bool:
    provenance = item.get("provenance") or {}
    return provenance.get("status") == "exact" and bool(item.get("checkpoint_id"))


async def build_scene_simulation_context(
    db,
    *,
    novel_id: str,
    scene_id: str,
    character_ids: list[str],
    related_object_ids: list[str],
    brief: dict,
) -> SimulationV3Context:
    participants = [SimulationReference(kind="object", id=item) for item in character_ids]
    locations: dict[str, SimulationReference] = {}
    positions: dict[str, SimulationReference] = {}
    resources: dict[str, SimulationResourceHolder] = {}
    item_ids = {
        str(item.get("entity_id"))
        for item in brief.get("world_items") or []
        if item.get("entity_type") in {"item", "object", "物件"}
    }

    for fact in brief.get("continuity_items") or []:
        if not _exact(fact):
            continue
        subject_id = str(fact.get("entity_id") or "")
        value = fact.get("value")
        if fact.get("dimension") == "locations" and fact.get("field") == "location":
            target_id = value.get("location_id") if isinstance(value, dict) else None
            if subject_id not in character_ids or not target_id:
                continue
            try:
                location = SimulationReference(kind="object", id=str(target_id))
                await validate_simulation_context_refs(
                    db,
                    novel_id,
                    SimulationV3Context(locations=[location]),
                )
            except ValueError:
                try:
                    location = SimulationReference(kind="map_node", id=str(target_id))
                    await validate_simulation_context_refs(
                        db,
                        novel_id,
                        SimulationV3Context(locations=[location]),
                    )
                except ValueError:
                    continue
            locations[location.state_key] = location
            positions[subject_id] = location
        provenance = fact.get("provenance") or {}
        typed_field = provenance.get("field")
        if (
            fact.get("dimension") == "entities"
            and fact.get("field") == "custody_holder"
            and typed_field == "custody_holder"
            and subject_id in item_ids
        ):
            holder_id = value.get("custody_holder") if isinstance(value, dict) else value
            resource = SimulationReference(kind="object", id=subject_id)
            holder = (
                SimulationReference(kind="object", id=str(holder_id))
                if holder_id
                else None
            )
            try:
                await validate_simulation_context_refs(
                    db,
                    novel_id,
                    SimulationV3Context(
                        participants=participants,
                        resources=[
                            SimulationResourceHolder(resource=resource, holder=holder)
                        ],
                    ),
                )
            except ValueError:
                continue
            resources[resource.state_key] = SimulationResourceHolder(
                resource=resource,
                holder=holder,
            )

    context = SimulationV3Context(
        participants=participants,
        locations=list(locations.values()),
        positions=[
            SimulationPosition(
                subject=SimulationReference(kind="object", id=actor_id),
                location=location,
            )
            for actor_id, location in sorted(positions.items())
        ],
        resources=list(resources.values()),
        assumptions=[
            "只采用通过当前作品核验且有精确字段来源的身份、位置与保管记录；未核实路线不推断可达。"
        ],
    )
    await validate_simulation_context_refs(db, novel_id, context)
    return context
