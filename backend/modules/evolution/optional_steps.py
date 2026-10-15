"""Pure registration data for optional Evolution reading steps."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class OptionalReadingStep:
    key: str
    request_field: str
    extraction_capability: str
    review_capability: str
    journal_prefix: str
    method_version_field: str
    output_domain: str
    write_port: str
    invalidation_consumer: str


OPTIONAL_READING_STEPS: Mapping[str, OptionalReadingStep] = MappingProxyType(
    {
        "details": OptionalReadingStep(
            key="details",
            request_field="discover_details",
            extraction_capability="evolution.details_discover",
            review_capability="evolution.details_review",
            journal_prefix="scene_discovery",
            method_version_field="discovery_version",
            output_domain="evolution.ledger",
            write_port="apply_discovery",
            invalidation_consumer="evolution.ledger",
        ),
        "spatial": OptionalReadingStep(
            key="spatial",
            request_field="discover_spatial",
            extraction_capability="evolution.spatial_discover",
            review_capability="evolution.spatial_review",
            journal_prefix="scene_spatial",
            method_version_field="spatial_version",
            output_domain="world.map_atlas",
            write_port="world.stage_spatial_discovery",
            invalidation_consumer="map_atlas",
        ),
    }
)


def optional_step_enabled(request: object, key: str) -> bool:
    """Read a registered opt-in flag without changing old request defaults."""
    spec = OPTIONAL_READING_STEPS[key]
    return getattr(request, spec.request_field, False) is True


__all__ = [
    "OPTIONAL_READING_STEPS",
    "OptionalReadingStep",
    "optional_step_enabled",
]
