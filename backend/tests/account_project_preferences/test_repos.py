"""Settings repos tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.account.settings_repositories import (
    GlobalAuthorPrefsRepository,
    GlobalLLMDefaultsRepository,
)
from modules.project.settings_models import ProjectAuthorPreferences
from modules.project.settings_repository import ProjectAuthorPrefsRepository


@pytest.mark.asyncio
async def test_global_llm_defaults_upsert_creates_then_updates(db_session):
    repo = GlobalLLMDefaultsRepository()
    payload = {
        "owner_id": LOCAL_OWNER_ID,
        "provider_id": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
    }
    row = await repo.upsert(db_session, payload)
    assert row.id is not None
    rid = row.id
    row2 = await repo.upsert(
        db_session, {"owner_id": LOCAL_OWNER_ID, "provider_id": "openai-compatible"}
    )
    assert row2.id == rid
    assert row2.provider_id == "openai-compatible"


@pytest.mark.asyncio
async def test_global_llm_defaults_owner_isolation(db_session):
    repo = GlobalLLMDefaultsRepository()
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    await repo.upsert(db_session, {"owner_id": owner_a, "provider_id": "a"})
    await repo.upsert(db_session, {"owner_id": owner_b, "provider_id": "b"})
    a = await repo.get(db_session, owner_a)
    b = await repo.get(db_session, owner_b)
    assert a.provider_id == "a"
    assert b.provider_id == "b"
    assert a.id != b.id


@pytest.mark.asyncio
async def test_global_llm_defaults_get_missing_returns_none(db_session):
    repo = GlobalLLMDefaultsRepository()
    assert await repo.get(db_session, LOCAL_OWNER_ID) is None


@pytest.mark.asyncio
async def test_global_author_prefs_upsert_null_semantics(db_session):
    repo = GlobalAuthorPrefsRepository()
    row = await repo.upsert(
        db_session,
        {
            "owner_id": LOCAL_OWNER_ID,
            "daily_goal": 6000,
            "editor_font": None,
            "default_focus_mode": None,
        },
    )
    assert row.daily_goal == 6000
    assert row.editor_font is None
    assert row.default_focus_mode is None


@pytest.mark.asyncio
async def test_project_author_prefs_row_not_exist_returns_none(db_session, factory):
    repo = ProjectAuthorPrefsRepository()
    pid = await factory.create_project()
    assert await repo.get(db_session, pid) is None


@pytest.mark.asyncio
async def test_project_author_prefs_field_reset_to_null(db_session, factory):
    repo = ProjectAuthorPrefsRepository()
    pid = await factory.create_project()
    await repo.upsert(
        db_session,
        {
            "project_id": pid,
            "daily_goal": 5000,
            "editor_font": "serif",
            "default_focus_mode": True,
        },
    )
    updated = await repo.reset_field(db_session, pid, "editor_font")
    assert updated.editor_font is None
    assert updated.daily_goal == 5000
    assert updated.default_focus_mode is True


@pytest.mark.asyncio
async def test_project_author_prefs_unique_project_id(db_session, factory):
    repo = ProjectAuthorPrefsRepository()
    pid = await factory.create_project()
    await repo.upsert(db_session, {"project_id": pid, "daily_goal": 1})
    row = await repo.upsert(db_session, {"project_id": pid, "daily_goal": 2})
    assert row.daily_goal == 2
    rows = await db_session.execute(
        select(ProjectAuthorPreferences).where(ProjectAuthorPreferences.project_id == pid)
    )
    assert len(rows.scalars().all()) == 1
