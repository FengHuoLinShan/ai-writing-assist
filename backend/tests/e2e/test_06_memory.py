"""
记忆记录与提案确认 E2E 测试
"""
from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene


class TestMemoryRecord:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_create_record(self, ctx):
        client, pid = ctx
        resp = await client.post(f"/api/novels/{pid}/memories/records", json={
            "novel_id": pid, "memory_type": "event", "summary": "克莱恩穿越事件",
            "chapter_index": 1, "visibility": "author_safe",
        })
        assert resp.status_code == 201

    async def test_list_records(self, ctx):
        client, pid = ctx
        await client.post(f"/api/novels/{pid}/memories/records", json={
            "novel_id": pid, "memory_type": "event", "summary": "记忆1",
            "chapter_index": 1,
        })
        await client.post(f"/api/novels/{pid}/memories/records", json={
            "novel_id": pid, "memory_type": "event", "summary": "记忆2",
            "chapter_index": 2,
        })
        resp = await client.get(f"/api/novels/{pid}/memories/records")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        assert len(items) >= 2

    async def test_filter_before_chapter(self, ctx):
        client, pid = ctx
        resp = await client.get(f"/api/novels/{pid}/memories/records?before_chapter=10")
        assert resp.status_code == 200


class TestMemoryMissingFlows:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        pid = meta["project_id"]
        pid_uuid = uuid.UUID(pid)
        from modules.memory.models import MemoryUpdateProposal
        proposal = MemoryUpdateProposal(
            novel_id=pid_uuid,
            proposal_type="create_memory",
            payload={
                "memory_type": "event",
                "summary": "AI提取的记忆提案",
                "chapter_index": 1,
            },
            chapter_index=1,
            confidence=0.85,
            reason="从章节文本中提取",
            decision="pending",
        )
        db_session.add(proposal)
        await db_session.flush()
        return async_client, pid, str(proposal.id), db_session

    async def test_pending_proposals_list(self, ctx):
        client, pid, _, _ = ctx
        resp = await client.get(f"/api/novels/{pid}/memories/proposals/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 1
        assert any(p["decision"] == "pending" for p in data["items"])

    async def test_confirm_proposal(self, ctx):
        client, pid, proposal_id, _ = ctx
        resp = await client.post(
            f"/api/novels/{pid}/memories/proposals/{proposal_id}/decide",
            json={"decision": "approved"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "approved"

    async def test_reject_proposal(self, ctx):
        client, pid, _, db_session = ctx
        pid_uuid = uuid.UUID(pid)
        from modules.memory.models import MemoryUpdateProposal
        proposal = MemoryUpdateProposal(
            novel_id=pid_uuid,
            proposal_type="create_memory",
            payload={
                "memory_type": "event",
                "summary": "待拒绝的提案",
                "chapter_index": 2,
            },
            chapter_index=2,
            confidence=0.6,
            decision="pending",
        )
        db_session.add(proposal)
        await db_session.flush()
        proposal_id = str(proposal.id)
        resp = await client.post(
            f"/api/novels/{pid}/memories/proposals/{proposal_id}/decide",
            json={"decision": "rejected"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "rejected"
