"""Native scheduling shares its bounded admission cap; API tuning is unchanged."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.config import get_settings
from modules.imports.env_helpers import bound_llm_concurrency


@pytest.mark.parametrize("cap", [2, 3, 4, 6, 8])
def test_native_import_workflow_cap_matches_provider_admission(monkeypatch, cap):
    monkeypatch.setenv(
        "LLM_MODEL_LIMITS_JSON",
        json.dumps({"subscription/codex/gpt-6-luna": {"concurrency": cap}}),
    )
    get_settings.cache_clear()
    try:
        with patch(
            "infrastructure.llm.profiles.resolve_llm_profile",
            autospec=True,
            return_value=SimpleNamespace(provider_id="codex", model="gpt-6-luna"),
        ):
            assert bound_llm_concurrency({}, 25) == cap
            assert bound_llm_concurrency({}, 1) == 1
        with patch(
            "infrastructure.llm.profiles.resolve_llm_profile",
            autospec=True,
            return_value=SimpleNamespace(provider_id="deepseek", model="deepseek-flash"),
        ):
            assert bound_llm_concurrency({}, 25) == 8
    finally:
        get_settings.cache_clear()
