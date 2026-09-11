"""轻量 DI 容器 — 消除模块间 facade 直连的循环依赖。

服务在 main.py 启动时注册，模块间通过 container.get() 获取依赖，
不再直接 import 其他模块的 facade/service。
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


@dataclass
class _Registration:
    instance: Any

    @classmethod
    def for_instance(cls, instance: Any) -> _Registration:
        return cls(instance=instance)

    def resolve(self) -> Any:
        return self.instance

    def shutdown_instance(self) -> Any | None:
        return self.instance


_container: dict[str, _Registration] = {}


def register(name: str, instance: Any) -> None:
    if name in _container:
        raise ValueError(f"Service {name!r} already registered")
    _container[name] = _Registration.for_instance(instance)


def get(name: str) -> Any:
    if name not in _container:
        available = ", ".join(sorted(_container))
        raise KeyError(f"Service {name!r} not registered. Available: {available}")
    return _container[name].resolve()


def reset() -> None:
    _container.clear()


@contextmanager
def container_scope(overrides: dict[str, Any] | None = None) -> Iterator[None]:
    """Temporarily override registered services with singleton instances."""
    overrides = overrides or {}
    previous = {name: _container.get(name) for name in overrides}
    try:
        for name, service in overrides.items():
            _container[name] = _Registration.for_instance(service)
        yield
    finally:
        for name in overrides:
            old_registration = previous[name]
            if old_registration is None:
                _container.pop(name, None)
            else:
                _container[name] = old_registration


async def shutdown() -> None:
    """Close created singleton services in reverse registration order."""
    errors: list[Exception] = []
    registrations = list(_container.items())
    try:
        for name, registration in reversed(registrations):
            service = registration.shutdown_instance()
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
