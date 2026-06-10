"""Import 模块测试配置 — 使用根 conftest 的 db_session"""

from __future__ import annotations

import uuid

import pytest

from modules.imports.repositories import ImportRecordRepository
from modules.imports.services import ImportService


@pytest.fixture
def repo():
    return ImportRecordRepository()


@pytest.fixture
def service():
    return ImportService()


@pytest.fixture
def sample_txt_content() -> bytes:
    return (
        "序章\n"
        "这是一个序章的内容。\n\n"
        "第一章\n"
        "这是第一章的内容，主角出现了。\n\n"
        "第二章 新的旅程\n"
        "这是第二章，主角踏上了旅程。\n\n"
        "第3章\n"
        "这是第三章。\n"
    ).encode("utf-8")


@pytest.fixture
def sample_txt_no_chapters() -> bytes:
    return "这是一篇没有分章的纯文本内容。只有一段话。".encode("utf-8")


@pytest.fixture
def test_project_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_novel_id() -> str:
    return str(uuid.uuid4())
