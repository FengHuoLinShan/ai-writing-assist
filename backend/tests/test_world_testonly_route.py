"""
测试 /api/world/_test/entities/{entity_id}/text-archive 路由的环境隔离与所有权校验
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.utils import _create_entity

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """每次测试前清除 get_settings 缓存，确保 APP_ENV 环境变量生效"""
    from core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_seed_text_archive_available_only_in_test_env(
    async_client,
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("APP_ENV", "development")
    nid = uuid4()
    entity = await _create_entity(db_session, nid, "item", "seed-target")
    resp = await async_client.post(
        f"/api/world/_test/entities/{entity.id.hex}/text-archive",
        json={
            "novel_id": nid.hex,
            "text_content": "archived",
            "scene_index": 5,
        },
    )
    assert resp.status_code == 404


async def test_seed_text_archive_requires_matching_novel_id(
    async_client,
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("APP_ENV", "test")
    nid = uuid4()
    entity = await _create_entity(db_session, nid, "item", "seed-target")
    wrong_novel_id = uuid4().hex
    resp = await async_client.post(
        f"/api/world/_test/entities/{entity.id.hex}/text-archive",
        json={
            "novel_id": wrong_novel_id,
            "text_content": "archived",
        },
    )
    assert resp.status_code == 404


async def test_seed_text_archive_creates_row(
    async_client,
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("APP_ENV", "test")
    nid = uuid4()
    entity = await _create_entity(db_session, nid, "item", "seed-target")
    resp = await async_client.post(
        f"/api/world/_test/entities/{entity.id.hex}/text-archive",
        json={
            "novel_id": nid.hex,
            "text_content": "archived summary",
            "field_name": "summary",
            "scene_index": 3,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["entity_id"] == entity.id.hex
    assert data["field_name"] == "summary"
    assert "archive_id" in data

    from sqlalchemy import select

    from modules.world.models import TextArchive

    result = await db_session.execute(
        select(TextArchive).where(TextArchive.entity_id == entity.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].text_content == "archived summary"
    assert rows[0].scene_index == 3
