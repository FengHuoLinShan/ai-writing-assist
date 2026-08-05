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
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from time import monotonic
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.database import DatabaseManager, get_manager
from core.errors import DomainError
from core.logging_context import (
    current_novel_id_for_log,
    novel_log_scope,
)
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

_TASK_DB_ERROR_MESSAGE = "后台任务遇到数据库临时错误，请稍后重试。"
_TASK_PREFLIGHT_WRITE_ERROR = "Task preflight must be read-only"
_TASK_RECOVERY_FAILURE_MESSAGE = "Task worker recovery failed safely; restart required."
_TASK_TYPE_LOG_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


class _TaskWorkerRecoveryError(RuntimeError):
    """Stable, secret-free failure used when task/domain recovery cannot converge."""


class _TaskOwnerScopeInvariantError(RuntimeError):
    """A persisted task does not satisfy its registered owner boundary."""


class _TaskHandlerSession(AsyncSession):
    """AsyncSession that fences each handler commit before it becomes durable."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._task_commit_hook: Callable[[], Awaitable[bool]] | None = None
        self._task_progress_checkpoint_hook: Callable[[], Awaitable[bool]] | None = None
        self._task_preflight_active = False

    def set_task_commit_hook(
        self,
        hook: Callable[[], Awaitable[bool]],
    ) -> None:
        self._task_commit_hook = hook

    def disable_task_commit_hook(self) -> None:
        self._task_commit_hook = None

    def set_task_progress_checkpoint_hook(
        self,
        hook: Callable[[], Awaitable[bool]],
    ) -> None:
        """Install the worker-owned, independent progress checkpoint hook."""
        self._task_progress_checkpoint_hook = hook

    @property
    def task_progress_checkpoint_enabled(self) -> bool:
        """Whether progress can be persisted without committing domain writes."""
        return self._task_progress_checkpoint_hook is not None

    async def checkpoint_task_progress(self) -> bool:
        """Persist detached task progress through an independent fenced session."""
        if self._task_progress_checkpoint_hook is None:
            raise RuntimeError("task progress checkpoint hook is not configured")
        if self.in_transaction():
            raise RuntimeError(
                "task progress checkpoint requires the handler session to be idle"
            )
        return await self._task_progress_checkpoint_hook()

    def begin_task_preflight(self) -> None:
        self._task_preflight_active = True

    def end_task_preflight(self) -> None:
        self._task_preflight_active = False

    @property
    def task_checkpoint_enabled(self) -> bool:
        """Whether commit-owning task-only services may checkpoint this session."""
        return self._task_commit_hook is not None

    async def commit(self) -> None:
        if self._task_preflight_active:
            raise RuntimeError(_TASK_PREFLIGHT_WRITE_ERROR)
        if self._task_commit_hook is not None and not await self._task_commit_hook():
            await super().rollback()
            raise asyncio.CancelledError
        await super().commit()

    async def flush(self, objects: Sequence[Any] | None = None) -> None:
        if self._task_preflight_active and (self.new or self.dirty or self.deleted):
            raise RuntimeError(_TASK_PREFLIGHT_WRITE_ERROR)
        await super().flush(objects)


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


def _task_result_snapshot(task: AsyncTask) -> dict[str, Any]:
    result = task.result
    return dict(result) if isinstance(result, Mapping) else {}


def _task_type_for_log(value: Any) -> str:
    return (
        value
        if isinstance(value, str) and _TASK_TYPE_LOG_RE.fullmatch(value)
        else "<invalid>"
    )


def _task_error_for_log(exc: Exception) -> str:
    """Keep user-controlled domain details and control characters out of logs."""
    if isinstance(exc, DomainError):
        return _task_type_for_log(type(exc).__name__)
    public_message = _public_task_error_message(exc)
    return "".join(
        character if character.isprintable() else " " for character in public_message
    )


def _task_novel_id(task: AsyncTask) -> Any:
    return task.novel_id


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
        task_preflight: Callable[[AsyncSession, AsyncTask], Awaitable[None]]
        | None = None,
        task_commit_guard: Callable[[AsyncSession, AsyncTask], Awaitable[bool]]
        | None = None,
        startup_reconcilers: Sequence[Callable[[AsyncSession], Awaitable[int]]] = (),
        control_loop_observer: Callable[[], None] | None = None,
    ) -> None:
        self._db_manager = db_manager or get_manager()
        self._registry = TaskRegistry()
        self._lifecycle = TaskLifecycleService()
        self._poll_interval = poll_interval
        self._heartbeat_interval = heartbeat_interval
        self._max_heartbeat_gap = max_heartbeat_gap
        self._task_preflight = task_preflight
        self._task_commit_guard = task_commit_guard
        self._startup_reconcilers = tuple(startup_reconcilers)
        self._control_loop_observer = control_loop_observer
        self._control_loop_observer_failed = False
        self._max_concurrent_tasks = max(
            1,
            int(get_settings().task_worker_max_concurrent_tasks),
        )
        self._running = False
        self._running_task_ids: set[Any] = set()
        self._running_tasks: dict[Any, AsyncTask] = {}
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

    def _observe_control_loop(self) -> None:
        """Notify an optional process observer without changing task behavior."""
        if self._control_loop_observer is None:
            return
        try:
            self._control_loop_observer()
        except Exception as error:
            if not self._control_loop_observer_failed:
                logger.warning(
                    "TaskWorker control-loop observer failed: %s",
                    type(error).__name__,
                )
            self._control_loop_observer_failed = True
        else:
            if self._control_loop_observer_failed:
                logger.info("TaskWorker control-loop observer recovered")
            self._control_loop_observer_failed = False

    async def run_once(self) -> AsyncTask | None:
        """单次执行：领取一个任务并执行

        Returns:
            执行完成的任务对象，如果没有 pending 任务则返回 None
        """
        async with self._db_manager.session_factory() as session:
            task = await self._claim_task(session)
            if task is None:
                return None
        return await self._execute_claimed_task(task)

    async def run_forever(self) -> None:
        """常驻循环：持续领取并执行任务"""
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
            await self._run_recovery_or_fail_closed(
                force=True,
                run_all_reconcilers=True,
            )

            while self._running or in_flight:
                self._observe_control_loop()
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
                            await self._run_recovery_or_fail_closed(force=False)
                        continue

                    if self._running:
                        await self._run_recovery_or_fail_closed(force=False)
                        await asyncio.sleep(self._poll_interval)
                except _TaskWorkerRecoveryError:
                    self._running = False
                    await self._cancel_in_flight_runners(in_flight)
                    raise
                except asyncio.CancelledError:
                    logger.info("TaskWorker received cancel signal, shutting down...")
                    self._running = False
                    await self._cancel_in_flight_runners(in_flight)
                    break
                except Exception as e:
                    logger.error("TaskWorker loop error: %s", _task_error_for_log(e))
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

    @staticmethod
    async def _cancel_in_flight_runners(in_flight: set[asyncio.Task[None]]) -> None:
        """Cancel and join runners when process-level shutdown cannot drain safely."""
        for runner in in_flight:
            runner.cancel()
        await asyncio.gather(*in_flight, return_exceptions=True)
        in_flight.clear()

    async def _claim_task_runner(self) -> asyncio.Task[None] | None:
        """Claim one task and return a runner with an atomic attempt transaction."""
        async with self._db_manager.session_factory() as session:
            task = await self._claim_task(session)
            if task is None:
                return None

        async def runner() -> None:
            await self._execute_claimed_task(task)

        return asyncio.create_task(runner())

    async def _execute_claimed_task(self, task: AsyncTask) -> AsyncTask:
        """Run a claimed task with fenced handler commits and detached progress."""
        lease_id = str(task.lease_id or "")
        session = _TaskHandlerSession(
            bind=self._db_manager.engine,
            expire_on_commit=False,
            autoflush=False,
        )
        session.set_task_commit_hook(
            lambda: self._checkpoint_handler_commit(session, task, lease_id)
        )
        session.set_task_progress_checkpoint_hook(
            lambda: self._checkpoint_handler_progress(task, lease_id)
        )
        try:
            await self._execute_task(task, session)
        finally:
            await session.close()
        async with self._db_manager.session_factory() as reload_session:
            current = await reload_session.get(AsyncTask, task.id)
        return current or task

    async def _checkpoint_handler_commit(
        self,
        session: AsyncSession,
        task: AsyncTask,
        lease_id: str,
    ) -> bool:
        """Fence and merge detached progress in the handler's transaction."""
        if self._task_commit_guard is not None and not await self._task_commit_guard(
            session,
            task,
        ):
            return False
        return await self._lifecycle.checkpoint_running_attempt(
            session,
            task=task,
            lease_id=lease_id,
        )

    async def _checkpoint_handler_progress(
        self,
        task: AsyncTask,
        lease_id: str,
    ) -> bool:
        """Persist progress without sharing the handler's domain transaction."""
        async with self._db_manager.session_factory() as progress_session:
            accepted = await self._lifecycle.checkpoint_running_attempt(
                progress_session,
                task=task,
                lease_id=lease_id,
            )
            if accepted:
                await progress_session.commit()
            else:
                await progress_session.rollback()
            return accepted

    def _log_finished_task_runners(self, done: set[asyncio.Task[None]]) -> None:
        for runner in done:
            try:
                runner.result()
            except asyncio.CancelledError:
                logger.info("Task runner cancelled")
            except Exception as exc:
                logger.error(
                    "Task runner failed unexpectedly: %s",
                    _task_error_for_log(exc),
                )

    async def _claim_task(self, session: AsyncSession) -> AsyncTask | None:
        """使用 FOR UPDATE SKIP LOCKED 领取一个 pending 任务"""
        task = await self._lifecycle.claim_next(session)
        if task is not None:
            self._running_task_ids.add(task.id)
            novel_id_state = "<none>" if _task_novel_id(task) is None else "<unverified>"
            logger.info(
                "Task claimed: %s (type=%s, novel_id=%s)",
                task.id,
                _task_type_for_log(task.task_type),
                novel_id_state,
            )
        return task

    async def _execute_task(
        self,
        task: AsyncTask,
        session: AsyncSession,
    ) -> bool:
        # Do not trust task.meta merely because it contains a UUID-shaped value.
        # The composition-root preflight uses a project facade lookup, which binds
        # the canonical ID only after the active-project check succeeds.
        with novel_log_scope():
            return await self._execute_task_in_scope(task, session)

    async def _execute_task_in_scope(
        self,
        task: AsyncTask,
        session: AsyncSession,
    ) -> bool:
        """执行任务的完整生命周期"""
        self._stats["processed"] += 1
        attempt_accepted = False
        lease_id = str(task.lease_id or "")
        current_runner = asyncio.current_task()
        if current_runner is not None:
            self._runner_tasks[task.id] = current_runner

        # 启动心跳协程（使用独立 session，避免与主执行共享连接）
        self._running_task_ids.add(task.id)
        self._running_tasks[task.id] = task
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(task.id, lease_id))
        self._heartbeat_tasks[task.id] = heartbeat_task

        with managed_llm_provenance_scope() as managed_llm_steps:
            terminal_recovery_policy: str | None = None
            try:
                definition = self._registry.get_definition(task.task_type)
                if definition is not None:
                    has_project_owner = task.novel_id is not None
                    if (
                        definition.owner_scope == "project" and not has_project_owner
                    ) or (definition.owner_scope == "global" and has_project_owner):
                        terminal_recovery_policy = "never_retry"
                        raise _TaskOwnerScopeInvariantError(
                            "persisted task owner does not match registered owner scope"
                        )

                handler = self._registry.get_handler(task.task_type)
                if handler is None:
                    terminal_recovery_policy = "never_retry"
                    raise ValueError(
                        f"No handler registered for task type: {task.task_type}. "
                        f"Registered types: {self._registry.registered_types}"
                    )

                if self._task_preflight is not None:
                    if isinstance(session, _TaskHandlerSession):
                        session.begin_task_preflight()
                    try:
                        await self._task_preflight(session, task)
                        await self._finish_task_preflight(session)
                    finally:
                        if isinstance(session, _TaskHandlerSession):
                            session.end_task_preflight()

                logger.info(
                    "Executing task %s (type=%s, novel_id=%s) with handler %s",
                    task.id,
                    _task_type_for_log(task.task_type),
                    current_novel_id_for_log(),
                    handler.__name__,
                )

                # 执行任务处理器
                result = await handler(task=task, db=session)

                # 更新任务为完成
                result_data = (
                    result
                    if isinstance(result, dict)
                    else {"result": redact_diagnostic(result, limit=2000)}
                )
                if managed_llm_steps:
                    result_data = merge_managed_llm_provenance(
                        result_data,
                        managed_llm_steps,
                    )
                accepted = await self._finalize_task(
                    session,
                    task=task,
                    task_id=task.id,
                    lease_id=lease_id,
                    status="done",
                    result_data=result_data,
                )
                if accepted:
                    self._stats["succeeded"] += 1
                    logger.info(
                        "Task completed: %s (type=%s, novel_id=%s)",
                        task.id,
                        _task_type_for_log(task.task_type),
                        current_novel_id_for_log(),
                    )
                else:
                    logger.warning(
                        "Discarded completion from stale lease: %s (novel_id=%s)",
                        task.id,
                        current_novel_id_for_log(),
                    )
                attempt_accepted = accepted

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
                accepted = await self._finalize_task(
                    session,
                    task=task,
                    task_id=task.id,
                    lease_id=lease_id,
                    status="cancelled",
                    result_data=failure_result,
                )
                if accepted:
                    self._stats["cancelled"] += 1
                attempt_accepted = accepted
                logger.info(
                    "Task cancelled: %s (type=%s, accepted=%s, novel_id=%s)",
                    task.id,
                    _task_type_for_log(task.task_type),
                    accepted,
                    current_novel_id_for_log(),
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
                accepted = await self._finalize_task(
                    session,
                    task=task,
                    **finalize_kwargs,
                )
                if accepted:
                    self._stats["failed"] += 1
                attempt_accepted = accepted
                logger.error(
                    "Task failed: %s (type=%s, accepted=%s, novel_id=%s) — %s",
                    task.id,
                    _task_type_for_log(task.task_type),
                    accepted,
                    current_novel_id_for_log(),
                    _task_error_for_log(e),
                )

            finally:
                self._running_task_ids.discard(task.id)
                self._running_tasks.pop(task.id, None)
                self._runner_tasks.pop(task.id, None)
                heartbeat_task = self._heartbeat_tasks.pop(task.id, None)
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
        return attempt_accepted

    @staticmethod
    async def _finish_task_preflight(session: AsyncSession) -> None:
        """Reject preflight writes and release any read-only autobegin transaction."""
        if session.new or session.dirty or session.deleted:
            raise RuntimeError(_TASK_PREFLIGHT_WRITE_ERROR)
        if session.in_transaction():
            await session.rollback()

    async def _finalize_task(
        self,
        session: AsyncSession,
        *,
        task: AsyncTask,
        **finalize_kwargs: Any,
    ) -> bool:
        """Fence finalization against project deletion and the current lease."""
        if isinstance(session, _TaskHandlerSession):
            session.disable_task_commit_hook()
        if self._task_commit_guard is not None and not await self._task_commit_guard(
            session,
            task,
        ):
            await session.rollback()
            return False
        return await self._lifecycle.finalize(session, **finalize_kwargs)

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
                            progress=(
                                self._running_tasks[task_id].progress
                                if task_id in self._running_tasks
                                else None
                            ),
                        )
                        if not accepted:
                            runner = self._runner_tasks.get(task_id)
                            if runner is not None and not runner.done():
                                runner.cancel()
                            return
                except Exception as exc:
                    logger.warning(
                        "Heartbeat update failed for task %s: %s",
                        task_id,
                        redact_diagnostic(exc, limit=300),
                    )
        except asyncio.CancelledError:
            pass

    async def _run_recovery_or_fail_closed(
        self,
        *,
        force: bool,
        run_all_reconcilers: bool = False,
    ) -> int:
        """Run recovery without allowing split task/domain ownership to continue."""
        failure: _TaskWorkerRecoveryError | None = None
        recovered = 0
        try:
            if run_all_reconcilers:
                transition = await self._maybe_recover_stale_task_transitions(
                    force=force
                )
                recovered = transition[0]
            else:
                recovered = await self._maybe_recover_stale_tasks(force=force)
            if run_all_reconcilers:
                await self._run_startup_reconcilers()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error(
                "TaskWorker recovery failed closed: %s",
                _task_error_for_log(error),
            )
            failure = _TaskWorkerRecoveryError(_TASK_RECOVERY_FAILURE_MESSAGE)
        if failure is not None:
            raise failure
        return recovered

    async def _maybe_recover_stale_task_transitions(
        self,
        *,
        force: bool = False,
    ) -> tuple[int, bool]:
        """按轮询间隔节流 stale scan，启动时可强制扫描一次。"""
        now = monotonic()
        if (
            not force
            and self._last_stale_scan_at is not None
            and now - self._last_stale_scan_at < self._poll_interval
        ):
            return 0, False

        recovered, reconciliation_required = await self._recover_stale_task_transitions()
        self._last_stale_scan_at = now
        return recovered, reconciliation_required

    async def _maybe_recover_stale_tasks(self, *, force: bool = False) -> int:
        """Run throttled stale recovery with its required owner reconciliation."""
        transition = await self._maybe_recover_stale_task_transitions(force=force)
        recovered, reconciliation_required = transition
        if reconciliation_required:
            await self._run_startup_reconcilers()
        return recovered

    async def recover_stale_tasks(self) -> int:
        """处理超时未心跳的任务。

        deep_import 任务只标记为可恢复，由用户显式继续；其他任务沿用
        自动恢复为 pending 的行为。任何实际 stale 转换完成后都会重新
        运行领域 owner reconciler，覆盖 worker 在心跳宽限期内重启、
        直到后续扫描才确认旧 owner 已终态的时间窗。

        Returns:
            自动恢复为 pending 的任务数量，不包含 stale deep_import
        """
        recovered, reconciliation_required = await self._recover_stale_task_transitions()
        if reconciliation_required:
            await self._run_startup_reconcilers()
        return recovered

    async def _recover_stale_task_transitions(self) -> tuple[int, bool]:
        """Apply stale task transitions and report whether owners must converge."""
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
        return recovered, bool(counts["auto_requeued"] or counts["failed"])

    async def _run_startup_reconcilers(self) -> None:
        if not self._startup_reconcilers:
            return
        async with self._db_manager.session_factory() as session:
            repaired = 0
            try:
                for reconciler in self._startup_reconcilers:
                    repaired += int(await reconciler(session))
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        if repaired:
            logger.info("Reconciled %d domain task owners", repaired)
