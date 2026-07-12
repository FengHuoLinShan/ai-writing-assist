# infrastructure/tasks — 轻量任务队列
# 使用 PostgreSQL 表 + 进程内 worker，不使用 Redis/Arq
from typing import TYPE_CHECKING, Any

from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry, task_handler

if TYPE_CHECKING:
    from infrastructure.tasks.worker import TaskWorker


def __getattr__(name: str) -> Any:
    """Keep the public Worker import lazy so task models cannot form a cycle."""
    if name == "TaskWorker":
        from infrastructure.tasks.worker import TaskWorker

        return TaskWorker
    raise AttributeError(name)


__all__ = [
    "AsyncTask",
    "TaskRegistry",
    "task_handler",
    "TaskWorker",
    "enqueue_task",
]
