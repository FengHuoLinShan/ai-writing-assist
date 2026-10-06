from __future__ import annotations

import asyncio
import json
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


class _MissingVectorManager(_LifespanManager):
    async def check_vector_extension(self) -> bool:
        self.events.append("db.check")
        return False


class _FailingVectorManager(_LifespanManager):
    async def check_vector_extension(self) -> bool:
        self.events.append("db.check")
        raise RuntimeError("vector probe failed")


def _lifespan_settings(app_env: str = "development") -> SimpleNamespace:
    return SimpleNamespace(
        log_level="INFO",
        app_name="test-app",
        app_version="test-version",
        rag_prewarm_on_startup=False,
        app_env=app_env,
    )


async def _run_lifespan_once(
    monkeypatch,
    manager,
    *,
    app_env: str = "development",
) -> None:
    async def close_container() -> None:
        manager.events.append("container.close")

    async def close_embedding() -> None:
        manager.events.append("embedding.close")

    monkeypatch.setattr(app_main, "get_settings", lambda: _lifespan_settings(app_env))
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

    async with app_main.lifespan(app_main.app):
        manager.events.append("served")


@pytest.mark.asyncio
async def test_health_check_redacts_database_exception(caplog, monkeypatch) -> None:
    secret = "private-token-value"

    class _FailingManager:
        @asynccontextmanager
        async def session(self):
            raise RuntimeError(f"Authorization: Bearer {secret} api_key={secret}")
            yield

    monkeypatch.setattr(app_main, "get_manager", _FailingManager)
    monkeypatch.setattr(app_main, "get_settings", _lifespan_settings)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        result = await app_main.health_check()

    assert result.status_code == 503
    assert b'"status":"degraded"' in result.body
    assert secret not in caplog.text
    assert secret.encode() not in result.body


@pytest.mark.asyncio
async def test_health_check_keeps_healthy_response_shape(monkeypatch) -> None:
    class _Result:
        def scalar(self) -> int:
            return 1

    class _HealthyManager:
        @asynccontextmanager
        async def session(self):
            yield self

        async def execute(self, _statement):
            return _Result()

    monkeypatch.setattr(app_main, "get_manager", _HealthyManager)
    monkeypatch.setattr(app_main, "get_settings", _lifespan_settings)

    result = await app_main.health_check()

    assert result == {
        "status": "healthy",
        "database": "connected",
        "version": "test-version",
        "app_name": "test-app",
    }


@pytest.mark.asyncio
async def test_health_check_deadline_cancels_query_and_closes_session(
    monkeypatch,
) -> None:
    class _BlockingManager:
        def __init__(self) -> None:
            self.query_started = asyncio.Event()
            self.query_cancelled = asyncio.Event()
            self.session_closed = asyncio.Event()

        @asynccontextmanager
        async def session(self):
            try:
                yield self
            finally:
                self.session_closed.set()

        async def execute(self, _statement):
            self.query_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.query_cancelled.set()

    manager = _BlockingManager()
    monkeypatch.setattr(app_main, "get_manager", lambda: manager)
    monkeypatch.setattr(app_main, "get_settings", _lifespan_settings)
    monkeypatch.setattr(app_main, "_DATABASE_HEALTH_TIMEOUT_SECONDS", 0.05)

    result = await asyncio.wait_for(app_main.health_check(), timeout=1)

    assert manager.query_started.is_set()
    assert manager.query_cancelled.is_set()
    assert manager.session_closed.is_set()
    assert result.status_code == 503
    assert json.loads(result.body) == {
        "status": "degraded",
        "database": "unreachable",
        "version": "test-version",
        "app_name": "test-app",
    }


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


@pytest.mark.asyncio
async def test_lifespan_fails_closed_when_pgvector_missing_in_production(
    monkeypatch,
) -> None:
    events: list[str] = []
    manager = _MissingVectorManager(events)

    with pytest.raises(RuntimeError, match="pgvector"):
        await _run_lifespan_once(monkeypatch, manager, app_env="production")

    assert events == ["db.init", "db.check"]


@pytest.mark.asyncio
async def test_lifespan_fails_closed_when_pgvector_probe_errors_in_production(
    monkeypatch,
) -> None:
    events: list[str] = []
    manager = _FailingVectorManager(events)

    with pytest.raises(RuntimeError, match="pgvector extension check failed") as exc_info:
        await _run_lifespan_once(monkeypatch, manager, app_env="production")

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "vector probe failed"
    assert events == ["db.init", "db.check"]


@pytest.mark.asyncio
async def test_lifespan_warns_and_starts_when_pgvector_missing_outside_production(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    manager = _MissingVectorManager(events)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        await _run_lifespan_once(monkeypatch, manager, app_env="development")

    assert "pgvector extension NOT detected" in caplog.text
    assert events == [
        "db.init",
        "db.check",
        "served",
        "container.close",
        "embedding.close",
        "db.close",
    ]


@pytest.mark.asyncio
async def test_lifespan_warns_and_starts_when_pgvector_probe_errors_outside_production(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    manager = _FailingVectorManager(events)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        await _run_lifespan_once(monkeypatch, manager, app_env="test")

    assert "Could not check pgvector extension" in caplog.text
    assert events == [
        "db.init",
        "db.check",
        "served",
        "container.close",
        "embedding.close",
        "db.close",
    ]
