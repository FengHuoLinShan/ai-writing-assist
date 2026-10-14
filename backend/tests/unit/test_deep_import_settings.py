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


def test_codex_defaults_preserve_explicit_limits_and_frozen_settings(monkeypatch):
    from shared.deep_import_settings import (
        DEEP_IMPORT_FROZEN_SETTINGS_KEY,
        materialize_effective_deep_import_settings,
    )

    api = materialize_effective_deep_import_settings({}, provider_id="deepseek")
    codex = materialize_effective_deep_import_settings({}, provider_id="codex")
    assert api["phase2"]["parallel_provider_timeout_seconds"] == 360
    assert codex["phase2"]["parallel_provider_timeout_seconds"] == 900
    assert codex["phase2"]["parallel_llm_timeout_seconds"] == 1800
    assert codex["phase2"]["alias_relation_llm_timeout_seconds"] == 900
    explicit = {"deep_import": {"phase2": {"parallel_provider_timeout_seconds": 42}}}
    assert (
        materialize_effective_deep_import_settings(explicit, provider_id="codex")[
            "phase2"
        ]["parallel_provider_timeout_seconds"]
        == 42
    )
    monkeypatch.setenv("PHASE2_PARALLEL_PROVIDER_TIMEOUT_SECONDS", "1200")
    assert (
        materialize_effective_deep_import_settings({}, provider_id="codex")["phase2"][
            "parallel_provider_timeout_seconds"
        ]
        == 1200
    )
    frozen = {"deep_import": api, DEEP_IMPORT_FROZEN_SETTINGS_KEY: True}
    assert materialize_effective_deep_import_settings(frozen, provider_id="codex") == api


@pytest.mark.parametrize(
    "settings", [{"deep_import": []}, {"deep_import": {"phase2": 7}}]
)
def test_codex_defaults_accept_legacy_malformed_settings(settings):
    from shared.deep_import_settings import materialize_effective_deep_import_settings

    result = materialize_effective_deep_import_settings(settings, provider_id="codex")
    assert result["phase2"]["parallel_provider_timeout_seconds"] == 900
