"""Keep evaluation runtime configuration out of subsequent application tests."""

import pytest

from core.config import get_settings


@pytest.fixture(autouse=True)
def isolate_evaluation_settings(monkeypatch):
    get_settings.cache_clear()
    yield
    # Restore environment first: a cached Settings must never outlive the
    # temporary model limits or feature flags from an evaluation fixture.
    monkeypatch.undo()
    get_settings.cache_clear()
