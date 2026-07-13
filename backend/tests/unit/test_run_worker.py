from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from run_worker import (
    _configure_worker_process,
    _guard_active_task_project_finalize,
    _require_active_task_project,
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
