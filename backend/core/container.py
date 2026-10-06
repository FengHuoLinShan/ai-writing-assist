"""轻量 DI 容器 — 消除模块间 facade 直连的循环依赖。

服务在 main.py 启动时注册，模块间通过 container.get() 获取依赖，
不再直接 import 其他模块的 facade/service。

AO-10：键类型化为 :class:`ServiceKey` 常量（登记表见
``core/service_keys.py``），``get(ServiceKey[T])`` 静态返回 ``T``；
字符串键保留为过渡期兼容路径（deprecated），键名字符串本身不变。
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, overload


@dataclass(frozen=True)
class ServiceKey[T]:
    """类型化 DI 键常量。

    ``name`` 是容器内的字符串键（行为契约，登记后不得改名）；类型参数
    ``T`` 仅服务于静态检查与 IDE 导航，运行期零开销。
    """

    name: str

    def __str__(self) -> str:
        return self.name


_container: dict[str, Any] = {}


def _key_name(key: ServiceKey[Any] | str) -> str:
    return key.name if isinstance(key, ServiceKey) else key


def register(key: ServiceKey[Any] | str, instance: Any) -> None:
    name = _key_name(key)
    if name in _container:
        raise ValueError(f"Service {name!r} already registered")
    _container[name] = instance


@overload
def get[T](key: ServiceKey[T]) -> T: ...


@overload
def get(key: str) -> Any: ...


def get(key: ServiceKey[Any] | str) -> Any:
    """按键解析已注册服务。

    传 :class:`ServiceKey` 常量时静态返回声明的 ``T``；传字符串键是
    过渡期兼容路径（deprecated：生产代码请改用 ``core.service_keys``
    键常量），运行期行为不变。
    """
    name = _key_name(key)
    if name not in _container:
        available = ", ".join(sorted(_container))
        raise KeyError(f"Service {name!r} not registered. Available: {available}")
    return _container[name]


def ensure_registered(keys: Iterable[ServiceKey[Any] | str]) -> None:
    """启动校验：声明的键全部已注册，缺失即 raise（防拼写/漏注册）。"""
    missing = sorted(name for name in map(_key_name, keys) if name not in _container)
    if missing:
        raise RuntimeError(
            "DI container missing required services: " + ", ".join(missing)
        )


def reset() -> None:
    _container.clear()


@contextmanager
def container_scope(
    overrides: dict[str | ServiceKey[Any], Any] | None = None,
) -> Iterator[None]:
    """Temporarily override registered services with singleton instances."""
    normalized = {_key_name(key): service for key, service in (overrides or {}).items()}
    previous = {name: _container.get(name) for name in normalized}
    try:
        for name, service in normalized.items():
            _container[name] = service
        yield
    finally:
        for name in normalized:
            old_service = previous[name]
            if old_service is None:
                _container.pop(name, None)
            else:
                _container[name] = old_service


async def shutdown() -> None:
    """Close created singleton services in reverse registration order."""
    errors: list[Exception] = []
    services = list(_container.items())
    try:
        for name, service in reversed(services):
            if service is None:
                continue
            try:
                await _close_service(service)
            except Exception as exc:
                exc.add_note(f"while closing service {name!r}")
                errors.append(exc)
    finally:
        _container.clear()

    if errors:
        raise ExceptionGroup("Errors during container shutdown", errors)


async def _close_service(service: Any) -> None:
    close = getattr(service, "aclose", None)
    if not callable(close):
        close = getattr(service, "close", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await result
