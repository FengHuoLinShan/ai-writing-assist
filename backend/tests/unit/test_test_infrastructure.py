"""Regression coverage for shared test-session isolation."""

from __future__ import annotations

import uuid

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
