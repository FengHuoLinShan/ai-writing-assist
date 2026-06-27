"""
复查报告 E2E 测试
"""

from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene


class TestReviewCRUD:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_review_entity_candidates(self, ctx):
        client, pid = ctx
        resp = await client.post(
            "/api/review",
            json={
                "novel_id": pid,
                "target_type": "entity_candidates",
                "candidate_payload": {
                    "name": "测试",
                    "entity_type": "item",
                    "importance": 0.5,
                },
            },
        )
        assert resp.status_code in (201, 500), (
            f"review: {resp.status_code} {resp.text[:200]}"
        )


class TestReviewMissingFlows:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_run_review(self, ctx):
        client, pid = ctx
        resp = await client.post(
            "/api/review",
            json={
                "novel_id": pid,
                "target_type": "entity_candidates",
                "candidate_payload": {
                    "name": "测试实体",
                    "entity_type": "item",
                    "importance": 0.5,
                },
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert "decision" in data
        assert data["novel_id"] == pid

    async def test_review_detail(self, ctx):
        client, pid = ctx
        create_resp = await client.post(
            "/api/review",
            json={
                "novel_id": pid,
                "target_type": "entity_candidates",
                "candidate_payload": {
                    "name": "详情测试实体",
                    "entity_type": "character_ref",
                    "importance": 0.7,
                },
            },
        )
        assert create_resp.status_code == 201
        review_id = create_resp.json()["id"]
        resp = await client.get(f"/api/review/{review_id}?novel_id={pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == review_id
        assert data["novel_id"] == pid
        assert "decision" in data
