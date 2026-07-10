"""
集成测试 / API 测试共享 conftest

复用 backend/conftest.py 的 SQLite 数据库和 API client，并提供额外测试数据。
"""

from __future__ import annotations

from conftest import test_character_id, test_entity_id, test_project_id  # noqa: F401
