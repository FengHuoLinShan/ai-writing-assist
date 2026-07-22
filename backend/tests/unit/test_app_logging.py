from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import app.main as app_main
from app.main import _configure_application_logging


def test_debug_logging_does_not_enable_sdk_prompt_payload_logs() -> None:
    logger_names = ("openai", "httpcore", "httpx")
    previous = {name: logging.getLogger(name).level for name in logger_names}
    try:
        _configure_application_logging("DEBUG")

        assert (
            logging.getLogger("openai._base_client").getEffectiveLevel()
            >= logging.WARNING
        )
        assert logging.getLogger("httpcore.http11").getEffectiveLevel() >= logging.WARNING
        assert logging.getLogger("httpx").getEffectiveLevel() >= logging.INFO
    finally:
        for name, level in previous.items():
            logging.getLogger(name).setLevel(level)


class _LifespanManager:
    def __init__(self, events: list[str], *, close_error: Exception | None = None):
        self.events = events
        self.close_error = close_error

    def init(self) -> None:
        self.events.append("db.init")

    async def check_vector_extension(self) -> bool:
        self.events.append("db.check")
        return True

    async def close(self) -> None:
        self.events.append("db.close")
        if self.close_error is not None:
            raise self.close_error


def _lifespan_settings() -> SimpleNamespace:
    return SimpleNamespace(
        log_level="INFO",
        app_name="test-app",
        app_version="test-version",
        rag_prewarm_on_startup=False,
    )


@pytest.mark.asyncio
async def test_health_check_redacts_database_exception(caplog, monkeypatch) -> None:
    secret = "private-token-value"

    class _FailingManager:
        @asynccontextmanager
        async def session(self):
            raise RuntimeError(
                f"Authorization: Bearer {secret} api_key={secret}"
            )
            yield

    monkeypatch.setattr(app_main, "get_manager", _FailingManager)
    monkeypatch.setattr(app_main, "get_settings", _lifespan_settings)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        result = await app_main.health_check()

    assert result.status_code == 503
    assert b'"status":"degraded"' in result.body
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_lifespan_runtime_error_still_closes_all_resources(monkeypatch) -> None:
    events: list[str] = []
    manager = _LifespanManager(events)

    async def close_container() -> None:
        events.append("container.close")

    async def close_embedding() -> None:
        events.append("embedding.close")

    monkeypatch.setattr(app_main, "get_settings", _lifespan_settings)
    monkeypatch.setattr(app_main, "get_manager", lambda: manager)
    monkeypatch.setattr(app_main, "_configure_application_logging", lambda _level: None)
    monkeypatch.setattr(
        app_main,
        "container",
        SimpleNamespace(shutdown=close_container),
    )
    monkeypatch.setattr(
        app_main,
        "BgeEmbeddingClient",
        SimpleNamespace(close_instance=close_embedding),
    )

    with pytest.raises(RuntimeError, match="runtime failed"):
        async with app_main.lifespan(app_main.app):
            raise RuntimeError("runtime failed")

    assert events == [
        "db.init",
        "db.check",
        "container.close",
        "embedding.close",
        "db.close",
    ]


@pytest.mark.asyncio
async def test_lifespan_attempts_later_closers_after_cleanup_failure(monkeypatch) -> None:
    events: list[str] = []
    manager = _LifespanManager(events, close_error=RuntimeError("db close failed"))

    async def close_container() -> None:
        events.append("container.close")
        raise RuntimeError("container close failed")

    async def close_embedding() -> None:
        events.append("embedding.close")

    monkeypatch.setattr(app_main, "get_settings", _lifespan_settings)
    monkeypatch.setattr(app_main, "get_manager", lambda: manager)
    monkeypatch.setattr(app_main, "_configure_application_logging", lambda _level: None)
    monkeypatch.setattr(
        app_main,
        "container",
        SimpleNamespace(shutdown=close_container),
    )
    monkeypatch.setattr(
        app_main,
        "BgeEmbeddingClient",
        SimpleNamespace(close_instance=close_embedding),
    )

    with pytest.raises(ExceptionGroup) as exc_info:
        async with app_main.lifespan(app_main.app):
            pass

    assert "Errors during application shutdown" in str(exc_info.value)
    assert len(exc_info.value.exceptions) == 2
    assert events == [
        "db.init",
        "db.check",
        "container.close",
        "embedding.close",
        "db.close",
    ]
