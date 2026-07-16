"""Regression coverage for shared test-session isolation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from core.dependencies import get_db
from modules.project.models import Project


@pytest.mark.asyncio
async def test_savepoint_commit_is_undone_by_outer_transaction(test_engine) -> None:
    """Application commits must not leak from one SQLite test session to another."""
    project_id = uuid.uuid4()

    async with test_engine.connect() as connection:
        outer_transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            session.add(
                Project(id=project_id, title="savepoint isolation", language="zh")
            )
            await session.commit()
            assert await session.get(Project, project_id) is not None
        finally:
            await session.close()
            await outer_transaction.rollback()

    async with test_engine.connect() as verify_connection:
        result = await verify_connection.execute(
            select(Project.id).where(Project.id == project_id)
        )
        assert result.scalar_one_or_none() is None


def test_root_fixture_clears_dependency_overrides_before_each_test() -> None:
    """The autouse fixture gives every test an initially clean FastAPI app."""
    assert app.dependency_overrides == {}
    app.dependency_overrides[get_db] = lambda: None


@pytest.mark.asyncio
async def test_project_factory_persists_common_and_override_fields(
    db_session: AsyncSession,
    project_factory,
) -> None:
    deleted_at = datetime(2026, 1, 2, tzinfo=UTC)
    project_id = await project_factory.create_project(
        title="shared factory",
        genre="mystery",
        deleted_at=deleted_at,
    )

    project = await db_session.get(Project, project_id)

    assert project is not None
    assert project.title == "shared factory"
    assert project.language == "zh"
    assert project.default_reveal_policy == "author_safe"
    assert project.settings == {}
    assert project.genre == "mystery"
    assert project.deleted_at is not None
    assert project.deleted_at.replace(tzinfo=UTC) == deleted_at
