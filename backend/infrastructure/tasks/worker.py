"""
轻量任务队列 Worker

使用 PostgreSQL FOR UPDATE SKIP LOCKED 实现并发安全的任务领取。
支持 run_forever() 常驻循环和 run_once() 单次执行。

Worker 流程:
1. SELECT ... FOR UPDATE SKIP LOCKED 领取一个 pending 任务
2. 标记为 running, 设置 started_at
3. 从 registry 获取任务处理器
4. 执行处理器
5. 标记为 done 或 failed
6. 定期更新 heartbeat
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from time import monotonic
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bootstrap import register_container_services
from core.config import get_settings
from core.database import DatabaseManager, get_manager
from infrastructure.llm.agent_step_harness import (
    managed_llm_provenance_scope,
    merge_managed_llm_provenance,
)
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from shared.constants import (
    TASK_HEARTBEAT_INTERVAL,
    TASK_MAX_HEARTBEAT_GAP,
    TASK_POLL_INTERVAL,
)

logger = logging.getLogger(__name__)

# 注册 projects 表（NovelMixin FK 依赖）
import modules.imports.models  # noqa: E402, F401
import modules.imports.tasks  # noqa: E402, F401
import modules.outline.tasks  # noqa: E402, F401
import modules.project.models  # noqa: E402, F401
import modules.project.tasks  # noqa: E402, F401
import modules.rag.tasks  # noqa: E402, F401

# 注册所有任务处理器（与 app/main.py 同步）
import modules.world.tasks  # noqa: E402, F401
import modules.writing.tasks  # noqa: E402, F401

_TASK_DB_ERROR_MESSAGE = "后台任务遇到数据库临时错误，请稍后重试。"


def _public_task_error_message(exc: Exception) -> str:
    """Return a task error safe to expose through the task status API."""
    raw = f"{type(exc).__name__}: {exc}"
    raw_lower = raw.lower()
    if isinstance(exc, SQLAlchemyError) or any(
        marker in raw_lower
        for marker in (
            "dbapierror",
            "sqlalchemy",
            "asyncpg",
            "current transaction is aborted",
            "[sql:",
        )
    ):
        return _TASK_DB_ERROR_MESSAGE
    return redact_diagnostic(raw, limit=1000)


def _register_container_services() -> None:
    """Register worker process-singleton DI services without replacing objects."""
    register_container_services(ignore_existing=True)


def _task_result_snapshot(task: AsyncTask) -> dict[str, Any]:
    result = task.result
    return dict(result) if isinstance(result, Mapping) else {}


class TaskWorker:
    """轻量任务队列 Worker

    进程内 worker，使用 PostgreSQL asyncpg + FOR UPDATE SKIP LOCKED。
    支持常驻循环和单次执行两种模式。

    用法:
        worker = TaskWorker()
        # 常驻循环
        await worker.run_forever()
        # 单次执行
        result = await worker.run_once()
    """

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        poll_interval: float = TASK_POLL_INTERVAL,
        heartbeat_interval: float = TASK_HEARTBEAT_INTERVAL,
        max_heartbeat_gap: float = TASK_MAX_HEARTBEAT_GAP,
    ) -> None:
        self._db_manager = db_manager or get_manager()
        self._registry = TaskRegistry()
        self._lifecycle = TaskLifecycleService()
        self._poll_interval = poll_interval
        self._heartbeat_interval = heartbeat_interval
        self._max_heartbeat_gap = max_heartbeat_gap
        self._max_concurrent_tasks = max(
            1,
            int(get_settings().task_worker_max_concurrent_tasks),
        )
        self._running = False
        self._running_task_ids: set[Any] = set()
        self._heartbeat_tasks: dict[Any, asyncio.Task[None]] = {}
        self._runner_tasks: dict[Any, asyncio.Task[Any]] = {}
        self._last_stale_scan_at: float | None = None
        self._stats: dict[str, int] = {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled": 0,
        }

    @property
    def stats(self) -> dict[str, int]:
        """获取 worker 统计信息"""
        return dict(self._stats)

    async def run_once(self) -> AsyncTask | None:
        """单次执行：领取一个任务并执行

        Returns:
            执行完成的任务对象，如果没有 pending 任务则返回 None
        """
        _register_container_services()
        async with self._db_manager.session_factory() as session:
            task = await self._claim_task(session)
            if task is None:
                return None
            await self._execute_task(task, session)
            return task

    async def run_forever(self) -> None:
        """常驻循环：持续领取并执行任务"""
        _register_container_services()
        self._running = True
        logger.info(
            "TaskWorker started — poll_interval=%.1fs, heartbeat_interval=%.1fs, "
            "max_concurrent_tasks=%d",
            self._poll_interval,
            self._heartbeat_interval,
            self._max_concurrent_tasks,
        )
        in_flight: set[asyncio.Task[None]] = set()

        try:
            try:
                await self._maybe_recover_stale_tasks(force=True)
            except Exception as e:
                logger.error("TaskWorker startup stale scan failed: %s", e, exc_info=True)

            while self._running or in_flight:
                try:
                    while self._running and len(in_flight) < self._max_concurrent_tasks:
                        runner = await self._claim_task_runner()
                        if runner is None:
                            break
                        in_flight.add(runner)

                    if in_flight:
                        timeout = self._poll_interval if self._running else None
                        done, pending = await asyncio.wait(
                            in_flight,
                            timeout=timeout,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        in_flight = pending
                        self._log_finished_task_runners(done)
                        if not done and self._running:
                            await self._maybe_recover_stale_tasks()
                        continue

                    if self._running:
                        await self._maybe_recover_stale_tasks()
                        await asyncio.sleep(self._poll_interval)
                except asyncio.CancelledError:
                    logger.info("TaskWorker received cancel signal, shutting down...")
                    self._running = False
                    for runner in in_flight:
                        runner.cancel()
                    await asyncio.gather(*in_flight, return_exceptions=True)
                    in_flight.clear()
                    break
                except Exception as e:
                    logger.error("TaskWorker loop error: %s", e, exc_info=True)
                    await asyncio.sleep(self._poll_interval)
        finally:
            self._running = False
            logger.info(
                "TaskWorker stopped — processed=%d, succeeded=%d, "
                "failed=%d, cancelled=%d",
                self._stats["processed"],
                self._stats["succeeded"],
                self._stats["failed"],
                self._stats["cancelled"],
            )

    def stop(self) -> None:
        """停止 worker 循环"""
        self._running = False

    async def _claim_task_runner(self) -> asyncio.Task[None] | None:
        """Claim one task and return a runner that owns its DB session."""
        session_context = self._db_manager.session_factory()
        session = await session_context.__aenter__()
        try:
            task = await self._claim_task(session)
            if task is None:
                await session_context.__aexit__(None, None, None)
                return None
        except BaseException as exc:
            await session_context.__aexit__(type(exc), exc, exc.__traceback__)
            raise

        async def runner() -> None:
            try:
                await self._execute_task(task, session)
            finally:
                await session_context.__aexit__(None, None, None)

        return asyncio.create_task(runner())

    def _log_finished_task_runners(self, done: set[asyncio.Task[None]]) -> None:
        for runner in done:
            try:
                runner.result()
            except asyncio.CancelledError:
                logger.info("Task runner cancelled")
            except Exception as exc:
                logger.error(
                    "Task runner failed unexpectedly: %s",
                    _public_task_error_message(exc),
                )

    async def _claim_task(self, session: AsyncSession) -> AsyncTask | None:
        """使用 FOR UPDATE SKIP LOCKED 领取一个 pending 任务"""
        task = await self._lifecycle.claim_next(session)
        if task is not None:
            self._running_task_ids.add(task.id)
            logger.info("Task claimed: %s (type=%s)", task.id, task.task_type)
        return task

    async def _execute_task(self, task: AsyncTask, session: AsyncSession) -> None:
        """执行任务的完整生命周期"""
        self._stats["processed"] += 1
        lease_id = str(task.lease_id or "")
        current_runner = asyncio.current_task()
        if current_runner is not None:
            self._runner_tasks[task.id] = current_runner

        # 启动心跳协程（使用独立 session，避免与主执行共享连接）
        self._running_task_ids.add(task.id)
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(task.id, lease_id))
        self._heartbeat_tasks[task.id] = heartbeat_task

        with managed_llm_provenance_scope() as managed_llm_steps:
            terminal_recovery_policy: str | None = None
            try:
                handler = self._registry.get_handler(task.task_type)
                if handler is None:
                    terminal_recovery_policy = "never_retry"
                    raise ValueError(
                        f"No handler registered for task type: {task.task_type}. "
                        f"Registered types: {self._registry.registered_types}"
                    )

                logger.info(
                    "Executing task %s (type=%s) with handler %s",
                    task.id,
                    task.task_type,
                    handler.__name__,
                )

                # 执行任务处理器
                result = await handler(task=task, db=session)

                # 更新任务为完成
                result_data = (
                    result if isinstance(result, dict) else {"result": str(result)}
                )
                if managed_llm_steps:
                    result_data = merge_managed_llm_provenance(
                        result_data,
                        managed_llm_steps,
                    )
                accepted = await self._lifecycle.finalize(
                    session,
                    task_id=task.id,
                    lease_id=lease_id,
                    status="done",
                    result_data=result_data,
                )
                if accepted:
                    await session.refresh(task)
                    self._stats["succeeded"] += 1
                    logger.info("Task completed: %s (type=%s)", task.id, task.task_type)
                else:
                    logger.warning("Discarded completion from stale lease: %s", task.id)

            except asyncio.CancelledError:
                failure_result = (
                    merge_managed_llm_provenance(
                        _task_result_snapshot(task),
                        managed_llm_steps,
                    )
                    if managed_llm_steps
                    else None
                )
                await session.rollback()
                accepted = await self._lifecycle.finalize(
                    session,
                    task_id=task.id,
                    lease_id=lease_id,
                    status="cancelled",
                    result_data=failure_result,
                )
                if accepted:
                    await session.refresh(task)
                    self._stats["cancelled"] += 1
                logger.info(
                    "Task cancelled: %s (type=%s, accepted=%s)",
                    task.id,
                    task.task_type,
                    accepted,
                )

            except Exception as e:
                failure_result = (
                    merge_managed_llm_provenance(
                        _task_result_snapshot(task),
                        managed_llm_steps,
                    )
                    if managed_llm_steps
                    else None
                )
                await session.rollback()
                finalize_kwargs = {
                    "task_id": task.id,
                    "lease_id": lease_id,
                    "status": "failed",
                    "result_data": failure_result,
                    "error_message": _public_task_error_message(e),
                }
                if terminal_recovery_policy is not None:
                    finalize_kwargs["recovery_policy"] = terminal_recovery_policy
                accepted = await self._lifecycle.finalize(
                    session,
                    **finalize_kwargs,
                )
                if accepted:
                    await session.refresh(task)
                    self._stats["failed"] += 1
                logger.error(
                    "Task failed: %s (type=%s, accepted=%s) — %s",
                    task.id,
                    task.task_type,
                    accepted,
                    _public_task_error_message(e),
                )

            finally:
                self._running_task_ids.discard(task.id)
                self._runner_tasks.pop(task.id, None)
                heartbeat_task = self._heartbeat_tasks.pop(task.id, None)
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

    async def _heartbeat_loop(self, task_id: Any, lease_id: str = "") -> None:
        """定期更新心跳（使用独立 session，避免与主执行共享）"""
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval)
                try:
                    async with self._db_manager.session_factory() as hb_session:
                        accepted = await self._lifecycle.heartbeat(
                            hb_session,
                            task_id=task_id,
                            lease_id=lease_id,
                        )
                        if not accepted:
                            runner = self._runner_tasks.get(task_id)
                            if runner is not None and not runner.done():
                                runner.cancel()
                            return
                except Exception:
                    logger.warning(
                        "Heartbeat update failed for task %s", task_id, exc_info=True
                    )
        except asyncio.CancelledError:
            pass

    async def _maybe_recover_stale_tasks(self, *, force: bool = False) -> int:
        """按轮询间隔节流 stale scan，启动时可强制扫描一次。"""
        now = monotonic()
        if (
            not force
            and self._last_stale_scan_at is not None
            and now - self._last_stale_scan_at < self._poll_interval
        ):
            return 0

        recovered = await self.recover_stale_tasks()
        self._last_stale_scan_at = now
        return recovered

    async def recover_stale_tasks(self) -> int:
        """处理超时未心跳的任务。

        deep_import 任务只标记为可恢复，由用户显式继续；其他任务沿用
        自动恢复为 pending 的行为。

        Returns:
            自动恢复为 pending 的任务数量，不包含 stale deep_import
        """
        async with self._db_manager.session_factory() as session:
            counts = await self._lifecycle.recover_stale(
                session,
                max_heartbeat_gap=self._max_heartbeat_gap,
            )
            recovered = counts["auto_requeued"]
            if recovered > 0:
                logger.info("Recovered %d stale tasks", recovered)
            if counts["manual_resume"] > 0:
                logger.info(
                    "Marked %d stale import tasks recoverable",
                    counts["manual_resume"],
                )
            return recovered
