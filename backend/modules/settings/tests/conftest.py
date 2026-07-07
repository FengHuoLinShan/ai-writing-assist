"""Settings tests shared fixtures."""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest_asyncio

from modules.project.models import Project


@pytest_asyncio.fixture
async def factory(db_session):
    """Create a real Project row in the SQLite session.

    Exposes ``await factory.create_project(title="T")`` returning a uuid.UUID.
    """

    async def create_project(
        title: str = "T",
        *,
        created_at: datetime | None = None,
        deleted_at: datetime | None = None,
    ) -> uuid.UUID:
        payload = {
            "title": title,
            "language": "zh",
            "default_reveal_policy": "author_safe",
            "settings": {},
        }
        if created_at is not None:
            payload["created_at"] = created_at
        if deleted_at is not None:
            payload["deleted_at"] = deleted_at
        p = Project(**payload)
        db_session.add(p)
        await db_session.flush()
        return p.id

    return SimpleNamespace(create_project=create_project)
