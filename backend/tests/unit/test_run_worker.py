from __future__ import annotations

import asyncio
import logging
import signal
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from run_worker import (
    BACKEND_ROOT,
    _build_task_worker,
    _configure_worker_process,
    _existing_reload_dirs,
    _guard_active_task_project_finalize,
    _require_active_task_project,
    _run_sync,
    _run_task_worker,
    _validate_worker_config,
    main,
)


def test_configure_worker_registers_domain_dependencies_and_handlers() -> None:
    from core.container import get, register, reset
    from infrastructure.tasks.registry import TaskRegistry

    sentinel = object()
    reset()
    try:
        register("memory.capture_snapshot", sentinel)
        _configure_worker_process()
        assert callable(get("writing.list_latest_drafts_for_chapters"))
        assert get("memory.capture_snapshot") is sentinel
        assert "smart_dedup_scan" in TaskRegistry().registered_types
    finally:
        reset()


def test_configure_worker_validates_llm_rate_limit_before_registration() -> None:
    settings = MagicMock(app_env="production", llm_rate_limit_per_minute=0)

    with (
        patch("run_worker.get_settings", autospec=True, return_value=settings),
        patch(
            "run_worker.validate_llm_rate_limit_config",
            autospec=True,
            side_effect=RuntimeError("invalid LLM rate limit"),
        ) as validate,
        patch(
            "app.bootstrap.register_container_services",
            autospec=True,
        ) as register_services,
        pytest.raises(RuntimeError, match="invalid LLM rate limit"),
    ):
        _configure_worker_process()

    validate.assert_called_once_with("production", 0)
    register_services.assert_not_called()


def test_non_local_worker_config_allows_disabled_llm_limiter() -> None:
    settings = MagicMock(app_env="production", llm_rate_limit_per_minute=0)

    with patch("run_worker.get_settings", autospec=True, return_value=settings):
        _validate_worker_config()


def test_reload_worker_waits_for_schema_before_starting() -> None:
    calls: list[str] = []

    def schema_ready() -> None:
        calls.append("schema_ready")

    def worker_started(worker_coro: object) -> None:
        calls.append("worker_started")
        worker_coro.close()

    with (
        patch("run_worker.setup_logging", autospec=True),
        patch(
            "run_worker.wait_for_schema_current",
            autospec=True,
            side_effect=schema_ready,
        ),
        patch(
            "run_worker.asyncio.run",
            autospec=True,
            side_effect=worker_started,
        ),
    ):
        _run_sync()

    assert calls == ["schema_ready", "worker_started"]


def test_reload_worker_watches_migrations() -> None:
    assert str(BACKEND_ROOT / "alembic") in _existing_reload_dirs()


def test_worker_composition_injects_control_loop_liveness_writer() -> None:
    from infrastructure.tasks.liveness import write_control_loop_liveness

    with patch("infrastructure.tasks.worker.TaskWorker", autospec=True) as worker_class:
        _build_task_worker()

    assert (
        worker_class.call_args.kwargs["control_loop_observer"]
        is write_control_loop_liveness
    )


@pytest.mark.asyncio
async def test_run_task_worker_turns_sigterm_into_one_graceful_drain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="run_worker")
    loop = MagicMock(spec=asyncio.AbstractEventLoop)
    worker = MagicMock()

    async def run_forever() -> None:
        handler = loop.add_signal_handler.call_args.args[1]
        handler()
        handler()

    worker.run_forever = AsyncMock(side_effect=run_forever)

    with patch(
        "run_worker.asyncio.get_running_loop",
        autospec=True,
        return_value=loop,
    ):
        await _run_task_worker(worker)

    loop.add_signal_handler.assert_called_once_with(signal.SIGTERM, ANY)
    worker.stop.assert_called_once_with()
    loop.remove_signal_handler.assert_called_once_with(signal.SIGTERM)
    assert caplog.messages.count(
        "TaskWorker received SIGTERM; draining in-flight tasks."
    ) == 1


@pytest.mark.asyncio
async def test_run_task_worker_removes_sigterm_handler_when_worker_errors() -> None:
    loop = MagicMock(spec=asyncio.AbstractEventLoop)
    worker = MagicMock()
    worker.run_forever = AsyncMock(side_effect=RuntimeError("worker failed"))

    with (
        patch(
            "run_worker.asyncio.get_running_loop",
            autospec=True,
            return_value=loop,
        ),
        pytest.raises(RuntimeError, match="worker failed"),
    ):
        await _run_task_worker(worker)

    loop.remove_signal_handler.assert_called_once_with(signal.SIGTERM)


@pytest.mark.asyncio
async def test_run_task_worker_runs_without_signal_handler_when_unsupported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    loop = MagicMock(spec=asyncio.AbstractEventLoop)
    loop.add_signal_handler.side_effect = NotImplementedError
    worker = MagicMock()
    worker.run_forever = AsyncMock()

    with patch(
        "run_worker.asyncio.get_running_loop",
        autospec=True,
        return_value=loop,
    ):
        await _run_task_worker(worker)

    worker.run_forever.assert_awaited_once_with()
    loop.remove_signal_handler.assert_not_called()
    assert "SIGTERM graceful shutdown handler is unavailable." in caplog.messages


@pytest.mark.asyncio
async def test_run_task_worker_fails_closed_when_signal_registration_errors() -> None:
    loop = MagicMock(spec=asyncio.AbstractEventLoop)
    loop.add_signal_handler.side_effect = RuntimeError("not on main thread")
    worker = MagicMock()
    worker.run_forever = AsyncMock()

    with (
        patch(
            "run_worker.asyncio.get_running_loop",
            autospec=True,
            return_value=loop,
        ),
        pytest.raises(RuntimeError, match="not on main thread"),
    ):
        await _run_task_worker(worker)

    worker.run_forever.assert_not_awaited()
    loop.remove_signal_handler.assert_not_called()


@pytest.mark.asyncio
async def test_main_composes_worker_through_sigterm_drain_wrapper() -> None:
    worker = MagicMock()

    with (
        patch("run_worker._configure_worker_process", autospec=True) as configure,
        patch("run_worker._build_task_worker", autospec=True, return_value=worker),
        patch("run_worker._run_task_worker", autospec=True) as run_worker,
    ):
        await main()

    configure.assert_called_once_with()
    run_worker.assert_awaited_once_with(worker)


@pytest.mark.asyncio
async def test_project_preflight_skips_global_tasks() -> None:
    db = AsyncMock()
    task = MagicMock()
    task.meta = {}

    with patch(
        "modules.project.facade.get_project_context",
        autospec=True,
    ) as get_context:
        await _require_active_task_project(db, task)

    get_context.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_preflight_guards_novel_scoped_tasks() -> None:
    db = AsyncMock()
    task = MagicMock()
    task.meta = {"novel_id": "novel-1"}

    with patch(
        "modules.project.facade.get_project_context",
        autospec=True,
        return_value=MagicMock(),
    ) as get_context:
        await _require_active_task_project(db, task)

    get_context.assert_awaited_once_with(db, "novel-1")
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_preflight_rejects_deleted_project_without_row_lock() -> None:
    from core.errors import NotFoundError

    db = AsyncMock()
    task = MagicMock()
    task.meta = {"novel_id": "novel-1"}

    with (
        patch(
            "modules.project.facade.get_project_context",
            autospec=True,
            return_value=None,
        ),
        pytest.raises(NotFoundError),
    ):
        await _require_active_task_project(db, task)


@pytest.mark.asyncio
async def test_interaction_preflight_rejects_author_project_kind() -> None:
    from core.errors import NotFoundError

    db = AsyncMock()
    task = MagicMock()
    task.task_type = "interaction_story_generate"
    task.meta = {"novel_id": "novel-1"}

    with (
        patch(
            "modules.project.facade.get_any_project_context",
            autospec=True,
            return_value=MagicMock(project_kind="author"),
        ) as get_context,
        pytest.raises(NotFoundError),
    ):
        await _require_active_task_project(db, task)

    get_context.assert_awaited_once_with(db, "novel-1")


@pytest.mark.asyncio
async def test_interaction_finalize_guard_requires_interaction_kind() -> None:
    db = AsyncMock()
    task = MagicMock()
    task.task_type = "interaction_summary_refresh"
    task.meta = {"novel_id": "novel-1"}

    with patch(
        "modules.project.facade.require_interaction_project",
        autospec=True,
    ) as require_interaction:
        assert await _guard_active_task_project_finalize(db, task) is True

    require_interaction.assert_awaited_once_with(db, "novel-1")


@pytest.mark.asyncio
async def test_finalize_guard_allows_active_or_global_task() -> None:
    db = AsyncMock()
    global_task = MagicMock()
    global_task.meta = {}
    project_task = MagicMock()
    project_task.meta = {"novel_id": "novel-1"}

    assert await _guard_active_task_project_finalize(db, global_task) is True
    with patch(
        "modules.project.facade.require_active_project",
        autospec=True,
    ) as require_active:
        assert await _guard_active_task_project_finalize(db, project_task) is True

    require_active.assert_awaited_once_with(db, "novel-1")


@pytest.mark.asyncio
async def test_finalize_guard_rejects_deleted_project() -> None:
    from core.errors import NotFoundError

    db = AsyncMock()
    task = MagicMock()
    task.meta = {"novel_id": "novel-1"}

    with patch(
        "modules.project.facade.require_active_project",
        autospec=True,
        side_effect=NotFoundError("not found"),
    ):
        assert await _guard_active_task_project_finalize(db, task) is False
