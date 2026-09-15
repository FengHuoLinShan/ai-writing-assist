"""
任务注册中心

提供 TaskRegistry 单例，用于注册和查找任务处理器。
业务模块通过 @task_handler 装饰器注册任务处理函数。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from infrastructure.tasks.contracts import RecoveryPolicy, TaskDefinition, TaskOwnerScope

logger = logging.getLogger(__name__)

_ROOT_CAPABILITY_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,160}$")


def normalize_root_capability_id(value: Any) -> str | None:
    """Validate one task's canonical run capability before it reaches the ledger."""
    if value is None:
        return None
    if not isinstance(value, str) or not _ROOT_CAPABILITY_RE.fullmatch(value):
        raise ValueError(
            "root_capability_id must be a canonical capability token of "
            "1-160 [A-Za-z0-9_.:-] characters"
        )
    return value


class TaskRegistry:
    """任务处理器注册中心（单例）

    业务模块通过注册处理器来声明自己能处理哪些任务类型。
    """

    _instance: TaskRegistry | None = None
    _handlers: dict[str, Callable[..., Any]]
    _definitions: dict[str, TaskDefinition]
    _root_capabilities: dict[str, str]

    def __new__(cls) -> TaskRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers = {}
            cls._instance._definitions = {}
            cls._instance._root_capabilities = {}
        return cls._instance

    def register(
        self,
        task_type: str,
        handler: Callable[..., Any],
        *,
        recovery_policy: RecoveryPolicy = "restart_origin",
        max_attempts: int = 1,
        generic_submit_schema: type[BaseModel] | None = None,
        owner_scope: TaskOwnerScope = "project",
        retry_transient_llm_errors: bool = False,
        root_capability_id: str | None = None,
        run_request_limit: int | Any = None,
        run_deadline_seconds: float | Any = None,
    ) -> None:
        """注册一个任务类型的处理器

        Args:
            task_type: 任务类型标识
            handler: 处理异步函数（接受 (db, task) 参数）
            root_capability_id: 一次权威 run 的 canonical capability；声明后
                worker 才为该任务建立运行信封（opt-in）。
            run_request_limit: 按 L0 = min(A, H) 冻结的请求额度；静态 int 或
                从任务冻结输入计算 A 的同步 callable。
            run_deadline_seconds: 一次 run 的 deadline 秒数；静态 float 或
                同步 callable。

        Raises:
            ValueError: 该任务类型已注册
        """
        if task_type in self._handlers:
            raise ValueError(f"Handler already registered for task type: {task_type}")
        if recovery_policy not in {
            "auto_requeue",
            "manual_resume",
            "restart_origin",
            "never_retry",
        }:
            raise ValueError(f"Unknown recovery policy: {recovery_policy}")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if owner_scope not in {"project", "global"}:
            raise ValueError(f"Unknown task owner scope: {owner_scope}")
        if generic_submit_schema is not None and (
            not isinstance(generic_submit_schema, type)
            or not issubclass(generic_submit_schema, BaseModel)
        ):
            raise TypeError("generic_submit_schema must be a Pydantic BaseModel class")
        normalized_capability = normalize_root_capability_id(root_capability_id)
        self._handlers[task_type] = handler
        self._definitions[task_type] = TaskDefinition(
            task_type=task_type,
            handler=handler,
            recovery_policy=recovery_policy,
            max_attempts=max_attempts,
            generic_submit_schema=generic_submit_schema,
            owner_scope=owner_scope,
            retry_transient_llm_errors=retry_transient_llm_errors,
            run_request_limit=run_request_limit,
            run_deadline_seconds=run_deadline_seconds,
        )
        if normalized_capability is not None:
            self._root_capabilities[task_type] = normalized_capability
        logger.info("Task handler registered: %s -> %s", task_type, handler.__name__)

    def get_handler(self, task_type: str) -> Callable[..., Any] | None:
        """获取指定任务类型的处理器

        Args:
            task_type: 任务类型标识

        Returns:
            处理器函数，如果未注册则返回 None
        """
        return self._handlers.get(task_type)

    def get_definition(self, task_type: str) -> TaskDefinition | None:
        return self._definitions.get(task_type)

    def get_root_capability(self, task_type: str) -> str | None:
        """返回该任务声明的一次权威运行 root capability（如有）。"""
        return self._root_capabilities.get(task_type)

    @staticmethod
    def _resolve_run_value(resolver: Any, task: Any, *, field: str) -> Any:
        if resolver is None or isinstance(resolver, (int, float)):
            return resolver
        if callable(resolver):
            return resolver(task)
        raise ValueError(f"{field} must be a number or a callable")

    def resolve_run_request_limit(self, task_type: str, task: Any) -> int | None:
        """解析该任务一次 run 的请求额度；未声明返回 None（不建立信封）。"""
        definition = self._definitions.get(task_type)
        if definition is None:
            return None
        value = self._resolve_run_value(
            definition.run_request_limit, task, field="run_request_limit"
        )
        if value is None:
            return None
        value = int(value)
        if value < 1:
            raise ValueError("run_request_limit must be positive")
        return value

    def resolve_run_deadline_seconds(self, task_type: str, task: Any) -> float | None:
        """解析该任务一次 run 的 deadline 秒数；未声明返回 None。"""
        definition = self._definitions.get(task_type)
        if definition is None:
            return None
        value = self._resolve_run_value(
            definition.run_deadline_seconds, task, field="run_deadline_seconds"
        )
        if value is None:
            return None
        value = float(value)
        if value <= 0:
            raise ValueError("run_deadline_seconds must be positive")
        return value

    def unregister(self, task_type: str) -> None:
        """注销一个任务类型的处理器（主要用于测试）"""
        self._handlers.pop(task_type, None)
        self._definitions.pop(task_type, None)
        self._root_capabilities.pop(task_type, None)
        logger.info("Task handler unregistered: %s", task_type)

    @property
    def registered_types(self) -> list[str]:
        """返回所有已注册的任务类型"""
        return list(self._handlers.keys())

    def __contains__(self, task_type: str) -> bool:
        return task_type in self._handlers


# 全局单例
_registry = TaskRegistry()


def get_registry() -> TaskRegistry:
    """获取全局 TaskRegistry 单例"""
    return _registry


def task_handler(
    task_type: str,
    *,
    recovery_policy: RecoveryPolicy = "restart_origin",
    max_attempts: int = 1,
    generic_submit_schema: type[BaseModel] | None = None,
    owner_scope: TaskOwnerScope = "project",
    retry_transient_llm_errors: bool = False,
    root_capability_id: str | None = None,
    run_request_limit: int | Any = None,
    run_deadline_seconds: float | Any = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰器：将函数注册为指定任务类型的处理器

    用法:
        @task_handler("embedding_build")
        async def handle_embedding_build(db, task):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _registry.register(
            task_type,
            func,
            recovery_policy=recovery_policy,
            max_attempts=max_attempts,
            generic_submit_schema=generic_submit_schema,
            owner_scope=owner_scope,
            retry_transient_llm_errors=retry_transient_llm_errors,
            root_capability_id=root_capability_id,
            run_request_limit=run_request_limit,
            run_deadline_seconds=run_deadline_seconds,
        )
        return func

    return decorator
