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
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text as sql_text, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import DatabaseManager, get_manager
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from shared.constants import TASK_HEARTBEAT_INTERVAL, TASK_MAX_HEARTBEAT_GAP, TASK_POLL_INTERVAL

logger = logging.getLogger(__name__)


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
        self._poll_interval = poll_interval
        self._heartbeat_interval = heartbeat_interval
        self._max_heartbeat_gap = max_heartbeat_gap
        self._running = False
        self._current_task: AsyncTask | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
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
        async with self._db_manager.session_factory() as session:
            task = await self._claim_task(session)
            if task is None:
                return None
            await self._execute_task(task, session)
            return task

    async def run_forever(self) -> None:
        """常驻循环：持续领取并执行任务"""
        self._running = True
        logger.info(
            "TaskWorker started — poll_interval=%.1fs, heartbeat_interval=%.1fs",
            self._poll_interval,
            self._heartbeat_interval,
        )

        try:
            while self._running:
                try:
                    async with self._db_manager.session_factory() as session:
                        task = await self._claim_task(session)
                        if task is None:
                            await asyncio.sleep(self._poll_interval)
                            continue
                        await self._execute_task(task, session)
                except asyncio.CancelledError:
                    logger.info("TaskWorker received cancel signal, shutting down...")
                    self._running = False
                    break
                except Exception as e:
                    logger.error("TaskWorker loop error: %s", e, exc_info=True)
                    await asyncio.sleep(self._poll_interval)
        finally:
            self._running = False
            logger.info(
                "TaskWorker stopped — processed=%d, succeeded=%d, failed=%d, cancelled=%d",
                self._stats["processed"],
                self._stats["succeeded"],
                self._stats["failed"],
                self._stats["cancelled"],
            )

    def stop(self) -> None:
        """停止 worker 循环"""
        self._running = False

    async def _claim_task(self, session: AsyncSession) -> AsyncTask | None:
        """使用 FOR UPDATE SKIP LOCKED 领取一个 pending 任务"""
        stmt = (
            select(AsyncTask)
            .where(AsyncTask.status == "pending")
            .order_by(AsyncTask.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()
        if task is not None:
            task.mark_running()
            await session.commit()
            self._current_task = task
            logger.info("Task claimed: %s (type=%s)", task.id, task.task_type)
        return task

    async def _execute_task(self, task: AsyncTask, session: AsyncSession) -> None:
        """执行任务的完整生命周期"""
        self._stats["processed"] += 1

        # 启动心跳协程（使用独立 session，避免与主执行共享连接）
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(task.id),
        )

        try:
            handler = self._registry.get_handler(task.task_type)
            if handler is None:
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
            result_data = result if isinstance(result, dict) else {"result": str(result)}
            task.mark_done(result_data)
            await session.commit()
            self._stats["succeeded"] += 1
            logger.info("Task completed: %s (type=%s)", task.id, task.task_type)

        except asyncio.CancelledError:
            task.mark_cancelled()
            await session.commit()
            self._stats["cancelled"] += 1
            logger.info("Task cancelled: %s (type=%s)", task.id, task.task_type)

        except Exception as e:
            task.mark_failed(f"{type(e).__name__}: {e}")
            await session.commit()
            self._stats["failed"] += 1
            logger.error(
                "Task failed: %s (type=%s) — %s: %s",
                task.id,
                task.task_type,
                type(e).__name__,
                e,
                exc_info=True,
            )

        finally:
            self._current_task = None
            # 取消心跳协程
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                self._heartbeat_task = None

    async def _heartbeat_loop(self, task_id: Any) -> None:
        """定期更新心跳（使用独立 session，避免与主执行共享）"""
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval)
                try:
                    async with self._db_manager.session_factory() as hb_session:
                        stmt = (
                            update(AsyncTask)
                            .where(AsyncTask.id == task_id)
                            .values(heartbeat_at=datetime.now(timezone.utc))
                        )
                        await hb_session.execute(stmt)
                        await hb_session.commit()
                except Exception:
                    logger.warning("Heartbeat update failed for task %s", task_id, exc_info=True)
        except asyncio.CancelledError:
            pass

    async def recover_stale_tasks(self) -> int:
        """恢复超时未心跳的任务（将 running 状态重置为 pending）

        修复：移除 ORM stmt 死代码，使用参数化查询替代 f-string
        （Bug C3: 死代码 + SQL 注入风险）

        Returns:
            恢复的任务数量
        """
        async with self._db_manager.session_factory() as session:
            result = await session.execute(
                sql_text(
                    "UPDATE async_tasks "
                    "SET status = 'pending', error_message = 'Task recovered: heartbeat timeout' "
                    "WHERE status = 'running' "
                    "AND heartbeat_at < NOW() - make_interval(secs => :gap)"
                ),
                {"gap": self._max_heartbeat_gap},
            )
            await session.commit()
            recovered = result.rowcount if result.rowcount is not None else 0
            if recovered > 0:
                logger.info("Recovered %d stale tasks", recovered)
            return recovered
