"""Memory 模块测试配置 — 使用根 conftest 的 db_session"""

from __future__ import annotations

import uuid

import pytest_asyncio


@pytest_asyncio.fixture
async def novel_id() -> str:
    """返回固定测试项目 ID"""
    return str(uuid.uuid4())
