"""Worker 入口：启动任务队列 Worker 常驻循环

用法：
    python run_worker.py            # 常驻模式
    python run_worker.py --reload   # 开发模式，文件变化时自动重启
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
import sys
from pathlib import Path

from core.config import get_settings, validate_llm_rate_limit_config

BACKEND_ROOT = Path(__file__).resolve().parent
RELOAD_DIRS = (
    "app",
    "core",
    "shared",
    "infrastructure",
    "modules",
    "prompts",
)
TASK_HANDLER_MODULES = (
    "modules.imports.tasks",
    "modules.outline.tasks",
    "modules.project.tasks",
    "modules.rag.tasks",
    "modules.world.tasks",
    "modules.writing.tasks",
)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def _require_active_task_project(db, task) -> None:
    """Non-locking worker start check; lease fencing handles later deletion."""
    novel_id = str((task.meta or {}).get("novel_id") or "").strip()
    if not novel_id:
        return

    from core.errors import NotFoundError
    from modules.project.facade import get_project_context

    if await get_project_context(db, novel_id) is None:
        raise NotFoundError(f"Project {novel_id} not found")


async def _guard_active_task_project_finalize(db, task) -> bool:
    """Linearize terminal task status before or after project deletion."""
    novel_id = str((task.meta or {}).get("novel_id") or "").strip()
    if not novel_id:
        return True

    from core.errors import NotFoundError
    from modules.project.facade import require_active_project

    try:
        await require_active_project(db, novel_id)
    except NotFoundError:
        return False
    return True


def _configure_worker_process() -> None:
    """Register domain DI and handlers at the worker composition root."""
    _validate_worker_config()

    from app.bootstrap import register_container_services

    register_container_services(ignore_existing=True)
    for module_name in TASK_HANDLER_MODULES:
        importlib.import_module(module_name)


def _validate_worker_config() -> None:
    """Fail closed before a worker process or reload supervisor starts."""
    settings = get_settings()
    validate_llm_rate_limit_config(
        settings.app_env,
        settings.llm_rate_limit_per_minute,
    )


async def main() -> None:
    from infrastructure.tasks.worker import TaskWorker

    _configure_worker_process()
    worker = TaskWorker(
        task_preflight=_require_active_task_project,
        task_commit_guard=_guard_active_task_project_finalize,
    )
    await worker.run_forever()


def _run_sync() -> None:
    """同步包装器（给 watchfiles.run_process 使用）"""
    setup_logging()
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
