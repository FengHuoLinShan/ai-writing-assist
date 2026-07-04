"""Context 模块集成测试配置 — 复用根 conftest 的 db_session 并提供 API client。"""

from __future__ import annotations

import pytest

from app.main import _register_container_services
from core.container import reset as reset_container


@pytest.fixture(autouse=True)
def _reset_di_container() -> None:
    """每个测试前重置 DI 容器并重新注册服务，消除全局状态污染。"""
    reset_container()
    _register_container_services()
