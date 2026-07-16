"""Pure normalization helpers for versioned and legacy map dynamics.

``MapFact`` remains the only persisted authority.  This module deliberately
returns deterministic read projections and never writes normalized data back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from modules.world.map_schemas import MapDynamicValueV1

NormalizationState = Literal[
    "typed",
    "legacy_normalized",
    "untyped",
    "invalid",
]

_VALUE_ADAPTER = TypeAdapter(MapDynamicValueV1)

_DYNAMIC_TYPE_ALIASES = {
    "location": "location",
    "movement": "location",
    "position": "location",
    "position_change": "location",
    "journey": "location",
    "route": "route_state",
    "route_state": "route_state",
    "path_state": "route_state",
    "status": "status",
    "state": "status",
    "boundary": "boundary",
    "territory": "boundary",
    "territory_change": "boundary",
    "resource": "resource",
    "resource_control": "resource",
    "terrain": "terrain",
    "terrain_change": "terrain",
    "crisis": "crisis",
    "crisis_spread": "crisis",
    "semantic": "semantic",
    "semantic_relation": "semantic",
    "movement_explanation": "semantic",
}


@dataclass(frozen=True)
class NormalizedDynamicValue:
    state: NormalizationState
    value: dict[str, Any] | None = None
    dimension_key: str | None = None
    error: str | None = None


def canonical_dynamic_type(dynamic_type: object) -> str:
    normalized = str(dynamic_type or "").strip().lower().replace("-", "_")
    return _DYNAMIC_TYPE_ALIASES.get(normalized, normalized)


def equivalent_dynamic_types(dynamic_type: object) -> tuple[str, ...]:
    """Return every persisted alias represented by one canonical filter."""
    canonical = canonical_dynamic_type(dynamic_type)
    return tuple(
        sorted(
            key
            for key, value in _DYNAMIC_TYPE_ALIASES.items()
            if value == canonical
        )
    ) or (canonical,)


def validate_versioned_dynamic_value(
    dynamic_type: str,
    value_json: dict[str, Any] | None,
) -> None:
    """Validate only explicitly versioned payloads; legacy JSON stays readable."""
    if not isinstance(value_json, dict) or "schema_version" not in value_json:
        return
    if value_json.get("payload_kind") == "proposal":
        return
    normalized = normalize_dynamic_value(dynamic_type, value_json, None)
    if normalized.state != "typed":
        raise ValueError(normalized.error or "invalid versioned map dynamic value")


def normalize_dynamic_value(
    dynamic_type: str,
    value_json: dict[str, Any] | None,
    spatial_anchor: dict[str, Any] | None,
) -> NormalizedDynamicValue:
    value = value_json if isinstance(value_json, dict) else {}
    anchor = spatial_anchor if isinstance(spatial_anchor, dict) else {}
    canonical_type = canonical_dynamic_type(dynamic_type)

    if value.get("payload_kind") == "proposal":
        return NormalizedDynamicValue(state="untyped")
    if "schema_version" in value:
        return _normalize_versioned(canonical_type, value)

    if canonical_type == "location":
        for key in ("location_entity_id", "path_id"):
            if value.get(key) and anchor.get(key) and value[key] != anchor[key]:
                return NormalizedDynamicValue(
                    state="invalid",
                    error=f"legacy {key} conflicts with authoritative spatial_anchor",
                )

    legacy = _legacy_payload(canonical_type, value, anchor)
    if legacy is None:
        return NormalizedDynamicValue(state="untyped")
    try:
        parsed = _VALUE_ADAPTER.validate_python(legacy)
    except PydanticValidationError as exc:
        return NormalizedDynamicValue(state="invalid", error=str(exc))
    payload = parsed.model_dump(mode="json")
    return NormalizedDynamicValue(
        state="legacy_normalized",
        value=payload,
        dimension_key=dynamic_dimension_key(payload),
    )


def _normalize_versioned(
    canonical_type: str,
    value: dict[str, Any],
) -> NormalizedDynamicValue:
    try:
        parsed = _VALUE_ADAPTER.validate_python(value)
    except PydanticValidationError as exc:
        return NormalizedDynamicValue(state="invalid", error=str(exc))
    payload = parsed.model_dump(mode="json")
    if canonical_type != payload["type"]:
        return NormalizedDynamicValue(
            state="invalid",
            error=(
                f"dynamic_type {canonical_type!r} does not match "
                f"value type {payload['type']!r}"
            ),
        )
    return NormalizedDynamicValue(
        state="typed",
        value=payload,
        dimension_key=dynamic_dimension_key(payload),
    )


def dynamic_dimension_key(value: dict[str, Any]) -> str:
    value_type = value["type"]
    if value_type == "location":
        return "location"
    if value_type == "route_state":
        return f"route:{value['path_id']}"
    if value_type == "status":
        return f"status:{value['field_key']}"
    if value_type == "boundary":
        return f"boundary:{value['controller_entity_id']}"
    if value_type == "resource":
        return f"resource:{value['resource_key']}"
    if value_type == "terrain":
        return f"terrain:{value['terrain_key']}"
    if value_type == "crisis":
        return f"crisis:{value['crisis_key']}"
    relation = value["relation_type"]
    related = ",".join(sorted(value.get("related_entity_ids") or []))
    return f"semantic:{relation}:{related}"


def _legacy_payload(
    dynamic_type: str,
    value: dict[str, Any],
    anchor: dict[str, Any],
) -> dict[str, Any] | None:
    if dynamic_type == "location":
        has_anchor = any(
            anchor.get(key) is not None
            for key in (
                "hex_q",
                "representative_q",
                "location_entity_id",
                "path_id",
            )
        )
        location_id = anchor.get("location_entity_id") or value.get(
            "location_entity_id"
        )
        path_id = anchor.get("path_id") or value.get("path_id")
        if not has_anchor and not location_id and not path_id:
            return None
        return {
            "schema_version": 1,
            "type": "location",
            "location_entity_id": location_id,
            "path_id": path_id,
            "movement_mode": value.get("movement_mode", "unknown"),
            "state": value.get("state") or value.get("new") or "present",
        }

    if dynamic_type == "route_state":
        path_id = value.get("path_id") or anchor.get("path_id")
        state = value.get("state") or value.get("new")
        if not path_id or state not in {"open", "restricted", "blocked"}:
            return None
        return {
            "schema_version": 1,
            "type": "route_state",
            "path_id": path_id,
            "state": state,
            "reason": value.get("reason"),
        }

    if dynamic_type == "status":
        field_key = value.get("field_key") or value.get("field")
        has_value = "value" in value or "new" in value or "state" in value
        if not field_key or not has_value:
            return None
        current = value.get("value")
        if "value" not in value:
            current = value.get("new") if "new" in value else value.get("state")
        if not isinstance(current, str | int | float | bool) and current is not None:
            return None
        return {
            "schema_version": 1,
            "type": "status",
            "field_key": str(field_key),
            "value": current,
        }

    if dynamic_type == "boundary":
        controller = value.get("controller_entity_id")
        hexes = _legacy_hexes(value.get("hexes"))
        if not controller or hexes is None:
            return None
        return {
            "schema_version": 1,
            "type": "boundary",
            "controller_entity_id": controller,
            "hexes": hexes,
        }

    if dynamic_type == "resource":
        resource_key = value.get("resource_key") or value.get("field")
        if not resource_key:
            return None
        return {
            "schema_version": 1,
            "type": "resource",
            "resource_key": str(resource_key),
            "controller_entity_id": value.get("controller_entity_id"),
            "status": value.get("status"),
            "amount": value.get("amount"),
        }

    if dynamic_type == "terrain":
        terrain_key = value.get("terrain_key") or value.get("field")
        state = value.get("state") or value.get("new")
        hexes = _legacy_hexes(value.get("hexes"))
        if not terrain_key or state is None or hexes is None:
            return None
        return {
            "schema_version": 1,
            "type": "terrain",
            "terrain_key": str(terrain_key),
            "state": str(state),
            "hexes": hexes,
        }

    if dynamic_type == "crisis":
        severity = value.get("severity")
        if severity is None:
            return None
        hexes = _legacy_hexes(value.get("hexes"))
        if hexes is None:
            return None
        return {
            "schema_version": 1,
            "type": "crisis",
            "crisis_key": str(value.get("crisis_key") or value.get("field") or "crisis"),
            "severity": severity,
            "hexes": hexes,
        }

    if dynamic_type == "semantic":
        relation_type = value.get("relation_type")
        if not relation_type:
            return None
        return {
            "schema_version": 1,
            "type": "semantic",
            "relation_type": str(relation_type),
            "related_entity_ids": value.get("related_entity_ids") or [],
            "summary": value.get("summary"),
        }
    return None


def _legacy_hexes(raw: Any) -> list[dict[str, int]] | None:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 20000:
        return None
    result: list[dict[str, int]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        q = item.get("hex_q", item.get("q"))
        r = item.get("hex_r", item.get("r"))
        if not isinstance(q, int) or not isinstance(r, int):
            return None
        result.append({"hex_q": q, "hex_r": r})
    return [
        {"hex_q": q, "hex_r": r}
        for q, r in sorted({(item["hex_q"], item["hex_r"]) for item in result})
    ]
