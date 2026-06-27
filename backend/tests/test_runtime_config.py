"""Runtime configuration behavior tests."""

from __future__ import annotations

from core.config import Settings
from infrastructure.llm.schemas import LLMCallRequest


def test_settings_default_to_opencodego_dsv4flash(monkeypatch) -> None:
    """Default runtime LLM config points at the project test provider."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    settings = Settings()

    assert (
        settings.database_url
        == "postgresql+asyncpg://novelist:novel_dev_pass@localhost:5207/ai_novel_engine"
    )
    assert settings.llm_base_url == "https://opencode.ai/zen/go/v1"
    assert settings.llm_model == "deepseek-v4-flash"


def test_llm_call_request_default_model_matches_runtime_default() -> None:
    """Ad-hoc LLM requests use the same default model as runtime config."""
    assert LLMCallRequest().model == "deepseek-v4-flash"


def test_e2e_database_url_uses_environment_override(monkeypatch) -> None:
    """E2E tests can follow the configured database instead of hardcoded 5432."""
    from tests.e2e.conftest import get_e2e_database_url

    expected = (
        "postgresql+asyncpg://novelist:novel_dev_pass@localhost:5207/ai_novel_engine"
    )
    monkeypatch.setenv("DATABASE_URL", expected)

    assert get_e2e_database_url() == expected
