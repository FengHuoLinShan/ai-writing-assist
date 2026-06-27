"""
时间线事件 E2E 测试
"""

from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene, create_timeline_events


class TestTimelineCRUD:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_create_event(self, ctx):
        client, pid = ctx
        resp = await client.post(
            f"/api/novels/{pid}/timeline/events",
            json={
                "novel_id": pid,
                "title": "克莱恩穿越",
                "summary": "从灰雾之上穿越",
                "order_index": 1,
                "chapter_index": 1,
                "event_type": "plot",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "克莱恩穿越"

    async def test_list_events(self, ctx):
        client, pid = ctx
        for i in range(3):
            await client.post(
                f"/api/novels/{pid}/timeline/events",
                json={
                    "novel_id": pid,
                    "title": f"事件{i}",
                    "summary": f"摘要{i}",
                    "order_index": i + 1,
                    "chapter_index": i + 1,
                },
            )
        resp = await client.get(f"/api/novels/{pid}/timeline/events")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        assert len(items) >= 3

    async def test_update_event(self, ctx):
        client, pid = ctx
        create = await client.post(
            f"/api/novels/{pid}/timeline/events",
            json={
                "novel_id": pid,
                "title": "原标题",
                "summary": "摘要",
                "order_index": 1,
                "chapter_index": 1,
            },
        )
        eid = create.json()["id"]
        update = await client.put(
            f"/api/novels/{pid}/timeline/events/{eid}",
            json={
                "title": "新标题",
                "visibility": "reader_known",
            },
        )
        assert update.status_code == 200
        assert update.json()["title"] == "新标题"

    async def test_delete_event(self, ctx):
        client, pid = ctx
        create = await client.post(
            f"/api/novels/{pid}/timeline/events",
            json={
                "novel_id": pid,
                "title": "待删除",
                "summary": "摘要",
                "order_index": 99,
                "chapter_index": 5,
            },
        )
        eid = create.json()["id"]
        del_resp = await client.delete(f"/api/novels/{pid}/timeline/events/{eid}")
        assert del_resp.status_code == 204

    async def test_filter_by_event_type(self, ctx):
        client, pid = ctx
        resp = await client.get(f"/api/novels/{pid}/timeline/events?event_type=plot")
        assert resp.status_code == 200

    async def test_filter_by_before_chapter(self, ctx):
        client, pid = ctx
        resp = await client.get(f"/api/novels/{pid}/timeline/events?before_chapter=10")
        assert resp.status_code == 200


class TestTimelineMissingFlows:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        pid = meta["project_uuid"]
        events = await create_timeline_events(db_session, pid)
        await db_session.flush()
        return async_client, meta["project_id"], events["event_ids"]

    async def test_deprecate_event(self, ctx):
        client, pid, event_ids = ctx
        eid = event_ids["克莱恩穿越"]
        resp = await client.put(
            f"/api/novels/{pid}/timeline/events/{eid}",
            json={"status": "deprecated"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deprecated"
