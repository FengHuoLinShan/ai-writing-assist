"""Worker 入口：启动任务队列 Worker 常驻循环

用法：
    python run_worker.py            # 常驻模式
    python run_worker.py --reload   # 开发模式，文件变化时自动重启
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from app.task_runtime import register_task_handlers
from core.config import get_settings, validate_llm_rate_limit_config
from scripts.dev_schema_guard import wait_for_schema_current

BACKEND_ROOT = Path(__file__).resolve().parent
RELOAD_DIRS = (
    "alembic",
    "app",
    "core",
    "shared",
    "infrastructure",
    "modules",
    "prompts",
)
logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def _require_active_task_project(db, task) -> None:
    """Non-locking worker start check; lease fencing handles later deletion."""
    novel_id = str(task.novel_id or "").strip()
    if not novel_id:
        return

    from core.errors import NotFoundError

    if str(task.task_type).startswith("interaction_"):
        from modules.project.facade import get_any_project_context

        context = await get_any_project_context(db, novel_id)
        if context is not None and context.project_kind != "interaction":
            context = None
    else:
        from modules.project.facade import get_project_context

        context = await get_project_context(db, novel_id)
    if context is None:
        raise NotFoundError(f"Project {novel_id} not found")


async def _guard_active_task_project_finalize(db, task) -> bool:
    """Linearize terminal task status before or after project deletion."""
    novel_id = str(task.novel_id or "").strip()
    if not novel_id:
        return True

    from core.errors import NotFoundError

    try:
        if str(task.task_type).startswith("interaction_"):
            from modules.project.facade import require_interaction_project

            await require_interaction_project(db, novel_id)
        else:
            from modules.project.facade import require_active_project

            await require_active_project(db, novel_id)
    except NotFoundError:
        return False
    return True


def _configure_worker_process() -> None:
    """Register domain DI and handlers at the worker composition root."""
    _validate_worker_config()

    from app.bootstrap import register_container_services

    register_container_services(ignore_existing=True)
    register_task_handlers()


def _validate_worker_config() -> None:
    """Fail closed before a worker process or reload supervisor starts."""
    settings = get_settings()
    validate_llm_rate_limit_config(
        settings.app_env,
        settings.llm_rate_limit_per_minute,
    )


def _build_task_worker():
    """Compose the generic worker with process-specific task services."""
    from infrastructure.tasks.liveness import write_control_loop_liveness
    from infrastructure.tasks.worker import TaskWorker
    from modules.imports.facade import reconcile_workflow_task_owners
    from modules.interaction.facade import reconcile_interaction_task_owners
    from modules.rag.facade import reconcile_index_task_owners
    from modules.world.map_atlas_facade import reconcile_map_atlas_task_owners

    return TaskWorker(
        task_preflight=_require_active_task_project,
        task_commit_guard=_guard_active_task_project_finalize,
        startup_reconcilers=(
            reconcile_workflow_task_owners,
            reconcile_interaction_task_owners,
            reconcile_index_task_owners,
            reconcile_map_atlas_task_owners,
        ),
        control_loop_observer=write_control_loop_liveness,
    )


async def _run_task_worker(worker) -> None:
    """Run a composed worker and translate production SIGTERM into a drain."""
    loop = asyncio.get_running_loop()
    signal_handler_installed = False
    shutdown_started = False

    def begin_graceful_shutdown() -> None:
        nonlocal shutdown_started
        if shutdown_started:
            return
        shutdown_started = True
        logger.info("TaskWorker received SIGTERM; draining in-flight tasks.")
        worker.stop()

    try:
        try:
            loop.add_signal_handler(signal.SIGTERM, begin_graceful_shutdown)
        except NotImplementedError:
            logger.warning("SIGTERM graceful shutdown handler is unavailable.")
        else:
            signal_handler_installed = True
        await worker.run_forever()
    finally:
        if signal_handler_installed:
            loop.remove_signal_handler(signal.SIGTERM)


async def main() -> None:
    _configure_worker_process()
    worker = _build_task_worker()
    await _run_task_worker(worker)


def _run_sync() -> None:
    """同步包装器（给 watchfiles.run_process 使用）"""
    setup_logging()
    wait_for_schema_current()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


def _existing_reload_dirs() -> list[str]:
    return [
        str(BACKEND_ROOT / name) for name in RELOAD_DIRS if (BACKEND_ROOT / name).exists()
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Task queue worker")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on file changes (uses watchfiles)",
    )
    args = parser.parse_args()

    if args.reload:
        # Validate in the supervisor as well as each spawned worker. Otherwise a
        # misconfigured child exits while watchfiles keeps an idle parent alive.
        _validate_worker_config()
        from watchfiles import run_process

        reload_dirs = _existing_reload_dirs() or [str(BACKEND_ROOT)]
        print(
            "Worker starting with --reload "
            f"(watching {', '.join(Path(path).name for path in reload_dirs)})..."
        )
        run_process(*reload_dirs, target=_run_sync)
    else:
        setup_logging()
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            pass
