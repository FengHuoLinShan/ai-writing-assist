"""
Unit tests for temporary entity expiration filtering in get_world_context().

Tests the current_chapter filtering logic in
modules/world/services/entity_service.py :: get_entity_context().
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.project import Project
from modules.world.models import CoreEntity


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
    """Temporary entity expiration filtering in get_world_context()."""

    async def test_no_filter_when_no_current_chapter(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ):
        """Without current_chapter, all entities are returned."""
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

        from modules.world.facade import get_world_context

        bundle = await get_world_context(db_session, novel_id)
        names = {e.name for e in bundle.entities}
        assert names == {"临时角色", "永久角色"}, (
            f"Expected both entities without filtering, got {names}"
        )

    async def test_temporary_expired_filtered(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ):
        """Temporary entity beyond default 30-chapter expiry is excluded."""
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

        from modules.world.facade import get_world_context

        bundle = await get_world_context(
            db_session, novel_id, current_chapter=40,
        )
        names = {e.name for e in bundle.entities}
        assert names == {"永久角色"}, (
            f"Expected only permanent entity (40-1=39 > default 30), "
            f"got {names}"
        )

    async def test_temporary_within_expiry_kept(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ):
        """Temporary entity within default 30-chapter expiry is kept."""
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

        from modules.world.facade import get_world_context

        bundle = await get_world_context(
            db_session, novel_id, current_chapter=5,
        )
        names = {e.name for e in bundle.entities}
        assert names == {"临时角色", "永久角色"}, (
            f"Expected both entities (5-1=4 <= 30), got {names}"
        )

    async def test_custom_expiry_from_settings(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ):
        """Custom expiry from project.settings is respected."""
        # Override project settings with a shorter expiry
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

        from modules.world.facade import get_world_context

        bundle = await get_world_context(
            db_session, novel_id, current_chapter=7,
        )
        names = {e.name for e in bundle.entities}
        assert names == {"永久角色"}, (
            f"Expected only permanent entity (7-1=6 > custom 5), "
            f"got {names}"
        )
