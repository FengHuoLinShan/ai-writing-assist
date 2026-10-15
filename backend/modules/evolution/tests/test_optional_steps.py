from types import MappingProxyType

from modules.evolution.optional_steps import (
    OPTIONAL_READING_STEPS,
    optional_step_enabled,
)
from modules.evolution.workflow import ReadingRequest


def test_optional_step_registry_is_pure_immutable_data():
    assert isinstance(OPTIONAL_READING_STEPS, MappingProxyType)
    assert OPTIONAL_READING_STEPS["details"].request_field == "discover_details"
    assert OPTIONAL_READING_STEPS["details"].journal_prefix == "scene_discovery"
    assert OPTIONAL_READING_STEPS["spatial"].request_field == "discover_spatial"
    assert OPTIONAL_READING_STEPS["spatial"].journal_prefix == "scene_spatial"


def test_details_flag_keeps_legacy_api_default_and_explicit_opt_in():
    base = {
        "operation_id": "f16f8017-f7b1-4d0a-a88e-7cffb6759f6a",
        "end_chapter": 1,
        "budget_mode": "bounded",
        "request_limit": 10,
    }
    disabled = ReadingRequest(**base)
    enabled = ReadingRequest(**{**base, "discover_details": True})

    assert disabled.discover_details is False
    assert optional_step_enabled(disabled, "details") is False
    assert optional_step_enabled(enabled, "details") is True
    assert optional_step_enabled(disabled, "spatial") is False
