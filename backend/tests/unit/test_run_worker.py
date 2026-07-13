from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from run_worker import _configure_worker_process, _require_active_task_project


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
        "modules.project.facade.require_active_project",
        autospec=True,
    ) as require_active:
        await _require_active_task_project(db, task)

    require_active.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_preflight_guards_novel_scoped_tasks() -> None:
    db = AsyncMock()
    task = MagicMock()
    task.meta = {"novel_id": "novel-1"}

    with patch(
        "modules.project.facade.require_active_project",
        autospec=True,
    ) as require_active:
        await _require_active_task_project(db, task)

    require_active.assert_awaited_once_with(db, "novel-1")
