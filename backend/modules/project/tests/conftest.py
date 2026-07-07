"""Project tests shared fixtures."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest_asyncio

from modules.project.models import Project


@pytest_asyncio.fixture
async def factory(db_session):
    """Create a real Project row in the SQLite session.

    Exposes ``await factory.create_project(title="T")`` returning a uuid.UUID.
    """

    async def create_project(title: str = "T") -> uuid.UUID:
        p = Project(
            title=title,
            language="zh",
            default_reveal_policy="author_safe",
            settings={},
        )
        db_session.add(p)
        await db_session.flush()
        return p.id

    return SimpleNamespace(create_project=create_project)
