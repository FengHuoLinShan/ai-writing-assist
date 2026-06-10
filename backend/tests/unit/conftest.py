from __future__ import annotations

import pytest

from core.container import reset


@pytest.fixture(autouse=True)
def _reset_di_container() -> None:
    """每个单元测试前重置 DI 容器，消除全局状态污染导致的 Heisenbug。"""
    reset()
