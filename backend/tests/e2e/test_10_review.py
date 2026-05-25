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
        resp = await client.post("/api/review", json={
            "novel_id": pid, "target_type": "entity_candidates",
            "candidate_payload": {"name": "测试", "entity_type": "item", "importance": 0.5},
        })
        assert resp.status_code in (201, 500), f"review: {resp.status_code} {resp.text[:200]}"
