"""Boundary tests for shared deep-import runtime settings."""

from __future__ import annotations

import pytest

from shared.deep_import_settings import (
    clean_deep_import_settings,
    deep_import_float_setting,
)


@pytest.mark.parametrize("invalid", ["nan", "inf", "-inf"])
def test_project_float_settings_reject_non_finite_values(invalid: str) -> None:
    cleaned = clean_deep_import_settings(
        {"phase0": {"max_tokens_per_input_char": invalid}}
    )

    assert cleaned["phase0"]["max_tokens_per_input_char"] == 1.0


@pytest.mark.parametrize("invalid", ["nan", "inf", "-inf"])
def test_environment_float_settings_reject_non_finite_values(
    invalid: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_PHASE0_RATIO", invalid)

    result = deep_import_float_setting(
        None,
        "phase0",
        "max_tokens_per_input_char",
        env_name="TEST_PHASE0_RATIO",
        default=1.0,
    )

    assert result == 1.0
