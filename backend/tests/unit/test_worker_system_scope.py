"""TaskWorker 执行入口必须处于 worker/system 执行范围内。

公开模式下 worker 进程不绑定 principal，项目门禁依赖 system scope 保留
显式无主身份；任何绕过 run_once/run_forever 的执行都会失去该身份。
"""

from __future__ import annotations

import pytest

from core.execution_context import is_system_execution
from infrastructure.tasks.worker import TaskWorker

pytestmark = pytest.mark.asyncio


def _stub_db_manager():
    from unittest.mock import AsyncMock, MagicMock

    db_manager = MagicMock()
    db_manager.session_factory = MagicMock(return_value=AsyncMock())
    db_manager.session_factory.return_value.__aenter__ = AsyncMock(
        return_value=AsyncMock()
    )
    db_manager.session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return db_manager


async def test_run_once_runs_inside_system_execution_scope() -> None:
    """run_once 的领取阶段处于 system scope 内，退出后不泄漏。"""
    from unittest.mock import patch

    worker = TaskWorker(db_manager=_stub_db_manager())
    captured: dict[str, bool] = {}

    async def fake_claim(_self, _session, *args, **kwargs):
        captured["in_scope"] = is_system_execution()
        return None

    with patch.object(TaskWorker, "_claim_task", autospec=True) as claim_mock:
        claim_mock.side_effect = fake_claim
        assert await worker.run_once() is None

    assert captured["in_scope"] is True
    assert is_system_execution() is False


async def test_run_forever_runs_inside_system_execution_scope() -> None:
    """run_forever 的领取循环同样处于 system scope 内。"""
    from unittest.mock import patch

    worker = TaskWorker(db_manager=_stub_db_manager())
    captured: dict[str, bool] = {}

    async def fake_recovery(_self, **kwargs):
        return 0

    async def fake_claim_runner(_self):
        captured["in_scope"] = is_system_execution()
        worker.stop()
        return None

    with (
        patch.object(
            TaskWorker,
            "_run_recovery_or_fail_closed",
            autospec=True,
        ) as recovery_mock,
        patch.object(
            TaskWorker,
            "_claim_task_runner",
            autospec=True,
        ) as claim_runner_mock,
    ):
        recovery_mock.side_effect = fake_recovery
        claim_runner_mock.side_effect = fake_claim_runner
        await worker.run_forever()

    assert captured["in_scope"] is True
    assert is_system_execution() is False
