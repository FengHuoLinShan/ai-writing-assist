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
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import DatabaseManager, get_manager
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


def _register_container_services() -> None:
    """注册 DI 容器服务（worker 进程不会经过 main.py，需独立注册）

    所有 import 放在函数体内，避免模块级循环导入。
    幂等调用：已注册的服务不会重复注册。
    """
    from core.container import register as _reg
    from modules.context.facade import compile_structure_context as _ctx_compile
    from modules.imports.scene_entity_extraction import (
        SceneEntityExtractionService as _SceneExtSvc,
    )
    from modules.memory.services import MemoryService as _MemSvc
    from modules.outline.services import (
        ForeshadowingPlanService as _FPS,  # noqa: N814
    )
    from modules.outline.services import (
        OutlineArcService as _OAS,  # noqa: N814
    )
    from modules.outline.services import (
        PlotStructureGenerator as _PSG,  # noqa: N814
    )
    from modules.outline.services import (
        PlotThreadService as _PTS,  # noqa: N814
    )
    from modules.outline.services import (
        RevealPlanService as _RPS,  # noqa: N814
    )
    from modules.outline.services import (
        SceneService as _SceneSvc,
    )
    from modules.rag.facade import (
        get_ordered_chapter_chunks as _rag_get_chunks,
    )
    from modules.rag.facade import (
        index_chapter_with_report as _rag_index,
    )
    from modules.world.facade import (
        create_character as _w_create_char,
    )
    from modules.world.facade import (
        get_character_id_by_world_entity as _w_get_char_id,
    )
    from modules.world.facade import (
        list_characters as _w_list_chars,
    )
    from modules.world.facade import (
        list_entities as _w_list_entities,
    )
    from modules.world.facade import (
        list_entity_terms as _w_list_terms,
    )
    from modules.world.facade import (
        run_entity_extraction as _w_extract,
    )
    from modules.writing.facade import (
        get_latest_draft_for_chapter as _w_get_draft,
    )
    from modules.writing.facade import (
        list_chapter_indices as _w_list_indices,
    )

    _svc_map = {
        "world.list_characters": _w_list_chars,
        "world.list_entity_terms": _w_list_terms,
        "world.run_entity_extraction": _w_extract,
        "world.list_entities": _w_list_entities,
        "world.run_scene_entity_extraction": _SceneExtSvc().extract_by_scenes,
        "world.run_alias_relation_extraction": _SceneExtSvc().extract_alias_relations,
        "world.create_character": _w_create_char,
        "world.get_character_id_by_world_entity": _w_get_char_id,
        "rag.index_chapter": _rag_index,
        "rag.get_ordered_chapter_chunks": _rag_get_chunks,
        "writing.list_chapter_indices": _w_list_indices,
        "writing.get_latest_draft_for_chapter": _w_get_draft,
        "outline.generate_structure": _PSG().generate,
        "outline.arc_service": _OAS(),
        "outline.thread_service": _PTS(),
        "outline.scene_service": _SceneSvc(),
        "outline.foreshadowing_service": _FPS(),
        "outline.reveal_service": _RPS(),
        "context.compile": _ctx_compile,
        "memory.service": _MemSvc(),
        "memory.capture_snapshot": _MemSvc().capture_snapshot,
    }

    for name, svc in _svc_map.items():
        try:
            _reg(name, svc)
        except ValueError:
            pass  # 已在 main.py 中注册（测试/开发模式共用进程时）


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
            "TaskWorker started — poll_interval=%.1fs, heartbeat_interval=%.1fs",
            self._poll_interval,
            self._heartbeat_interval,
        )

        try:
            try:
                await self._maybe_recover_stale_tasks(force=True)
            except Exception as e:
                logger.error("TaskWorker startup stale scan failed: %s", e, exc_info=True)

            while self._running:
                try:
                    async with self._db_manager.session_factory() as session:
                        task = await self._claim_task(session)
                        if task is None:
                            await self._maybe_recover_stale_tasks()
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
            await session.rollback()
            task.mark_cancelled()
            await session.commit()
            self._stats["cancelled"] += 1
            logger.info("Task cancelled: %s (type=%s)", task.id, task.task_type)

        except Exception as e:
            await session.rollback()
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
                            .values(heartbeat_at=datetime.now(UTC))
                        )
                        await hb_session.execute(stmt)
                        await hb_session.commit()
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
        cutoff = datetime.now(UTC) - timedelta(seconds=self._max_heartbeat_gap)
        async with self._db_manager.session_factory() as session:
            deep_imports = await self._mark_stale_deep_imports(session, cutoff)

            result = await session.execute(
                update(AsyncTask)
                .where(
                    AsyncTask.status == "running",
                    AsyncTask.task_type != "deep_import",
                    AsyncTask.heartbeat_at < cutoff,
                )
                .values(
                    status="pending",
                    error_message="Task recovered: heartbeat timeout",
                )
            )
            await session.commit()
            recovered = result.rowcount if result.rowcount is not None else 0
            if recovered > 0:
                logger.info("Recovered %d stale tasks", recovered)
            if deep_imports > 0:
                logger.info("Marked %d stale deep_import tasks recoverable", deep_imports)
            return recovered

    async def _mark_stale_deep_imports(
        self,
        session: AsyncSession,
        cutoff: datetime,
    ) -> int:
        """标记 stale deep_import 为可恢复，但不改回 pending。"""
        result = await session.execute(
            select(AsyncTask)
            .where(
                AsyncTask.status == "running",
                AsyncTask.task_type == "deep_import",
                AsyncTask.heartbeat_at < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        tasks = result.scalars().all()
        interrupted_at = datetime.now(UTC).isoformat()
        marked = 0

        for task in tasks:
            result_data = dict(task.result or {})
            meta_data = dict(task.meta or {})
            if (
                result_data.get("recovery_required") is True
                and meta_data.get("recovery_required") is True
            ):
                continue

            last_heartbeat_at = (
                task.heartbeat_at.isoformat() if task.heartbeat_at is not None else None
            )
            recovery_summary = {
                "reason": "heartbeat_timeout",
                "message": (
                    "Deep import worker heartbeat timed out; "
                    "user recovery required."
                ),
            }
            recovery_flags = {
                "interrupted": True,
                "recoverable": True,
                "recovery_required": True,
                "interrupted_at": interrupted_at,
                "last_heartbeat_at": last_heartbeat_at,
                "recovery_summary": recovery_summary,
            }

            task.result = {**result_data, **recovery_flags}
            task.meta = {**meta_data, **recovery_flags}
            task.error_message = (
                "Task interrupted: heartbeat timeout; recovery required"
            )
            marked += 1

        return marked
