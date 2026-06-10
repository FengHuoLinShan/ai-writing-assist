"""
Unit tests for temporary entity expiration filtering in get_world_context().

Tests the current_chapter filtering logic exposed via
modules.world.facade :: get_world_context().
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.project import Project
from modules.world.facade import get_world_context
from modules.world.models import CoreEntity

pytestmark = [pytest.mark.asyncio]


# ============================================================
# Helpers
# ============================================================


async def _create_entity(
    db: AsyncSession,
    novel_id: str,
    name: str,
    entity_type: str = "character",
    status: str = "canonical",
    content_json: dict | None = None,
) -> CoreEntity:
    e = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        name=name,
        entity_type=entity_type,
        status=status,
        content_json=content_json,
    )
    db.add(e)
    await db.flush()
    return e


# ============================================================
# Fixtures
# ============================================================


@pytest_asyncio.fixture
async def novel_id(db_session: AsyncSession) -> str:
    """Create a project with default expiry settings (30 chapters)."""
    pid = uuid.uuid4()
    p = Project(
        id=pid,
        title="测试小说",
        settings={"temporary_entity_expiry_chapters": 30},
    )
    db_session.add(p)
    await db_session.flush()
    return str(pid)


# ============================================================
# Tests
# ============================================================


class TestTemporaryEntityFilter:
    """临时实体过期过滤单元测试 — 验证 get_world_context 按 current_chapter 正确过滤"""

    async def test_get_world_context_with_no_current_chapter_returns_all_entities(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ):
        """未提供 current_chapter 时返回所有实体（不过滤临时实体）"""
        # Arrange
        await _create_entity(
            db_session,
            novel_id,
            name="临时角色",
            content_json={
                "_meta": {"temporary": True, "source_chapter_index": 1},
            },
        )
        await _create_entity(
            db_session,
            novel_id,
            name="永久角色",
        )

        # Act
        bundle = await get_world_context(db_session, novel_id)

        # Assert
        names = {e.name for e in bundle.entities}
        assert names == {"临时角色", "永久角色"}, (
            f"Expected both entities without filtering, got {names}"
        )

    async def test_get_world_context_with_expired_temporary_entity_excludes_it(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ):
        """超出默认 30 章有效期的临时实体应被排除"""
        # Arrange
        await _create_entity(
            db_session,
            novel_id,
            name="临时角色",
            content_json={
                "_meta": {"temporary": True, "source_chapter_index": 1},
            },
        )
        await _create_entity(
            db_session,
            novel_id,
            name="永久角色",
        )

        # Act
        bundle = await get_world_context(
            db_session, novel_id, current_chapter=40,
        )

        # Assert
        names = {e.name for e in bundle.entities}
        assert names == {"永久角色"}, (
            f"Expected only permanent entity (40-1=39 > default 30), "
            f"got {names}"
        )

    async def test_get_world_context_with_temporary_within_expiry_keeps_it(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ):
        """在默认 30 章有效期内的临时实体应被保留"""
        # Arrange
        await _create_entity(
            db_session,
            novel_id,
            name="临时角色",
            content_json={
                "_meta": {"temporary": True, "source_chapter_index": 1},
            },
        )
        await _create_entity(
            db_session,
            novel_id,
            name="永久角色",
        )

        # Act
        bundle = await get_world_context(
            db_session, novel_id, current_chapter=5,
        )

        # Assert
        names = {e.name for e in bundle.entities}
        assert names == {"临时角色", "永久角色"}, (
            f"Expected both entities (5-1=4 <= 30), got {names}"
        )

    async def test_get_world_context_with_custom_expiry_respects_project_settings(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ):
        """项目 settings 中的自定义 expiry 值应被正确应用"""
        # Arrange
        pid = uuid.UUID(novel_id)
        p = await db_session.get(Project, pid)
        p.settings = {"temporary_entity_expiry_chapters": 5}

        await _create_entity(
            db_session,
            novel_id,
            name="临时角色",
            content_json={
                "_meta": {"temporary": True, "source_chapter_index": 1},
            },
        )
        await _create_entity(
            db_session,
            novel_id,
            name="永久角色",
        )

        # Act
        bundle = await get_world_context(
            db_session, novel_id, current_chapter=7,
        )

        # Assert
        names = {e.name for e in bundle.entities}
        assert names == {"永久角色"}, (
            f"Expected only permanent entity (7-1=6 > custom 5), "
            f"got {names}"
        )
