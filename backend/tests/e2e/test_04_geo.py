"""
地理层级与历史时期 E2E 测试
"""
from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene


async def _any_entity_id(client, pid):
    r = await client.get(f"/api/world/entities?novel_id={pid}&limit=1")
    items = r.json().get("items", [])
    return items[0]["id"] if items else str(uuid.uuid4())


class TestGeoLocation:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_create_location(self, ctx):
        client, pid, eids = ctx
        resp = await client.post("/api/geo/locations", json={
            "novel_id": pid, "world_entity_id": eids["廷根市"],
            "location_level": "city",
        })
        assert resp.status_code == 201

    async def test_get_location_tree(self, ctx):
        client, pid, _ = ctx
        resp = await client.get(f"/api/geo/locations/tree?novel_id={pid}")
        assert resp.status_code == 200
        tree = resp.json()
        # tree should be a list of root-level locations
        assert isinstance(tree, list)

    async def test_list_locations(self, ctx):
        client, pid, _ = ctx
        resp = await client.get(f"/api/geo/locations?novel_id={pid}")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        assert len(items) >= 1


class TestGeoEdge:
    @pytest_asyncio.fixture
    async def ctx(self, async_client, db_session):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_create_edge(self, ctx):
        client, pid = ctx
        # Need existing locations first
        loc1 = await client.post("/api/geo/locations", json={
            "novel_id": pid, "world_entity_id": (await _any_entity_id(client, pid)),
            "location_level": "city",
        })
        loc2 = await client.post("/api/geo/locations", json={
            "novel_id": pid, "world_entity_id": (await _any_entity_id(client, pid)),
            "location_level": "city",
        })
        resp = await client.post("/api/geo/edges", json={
            "novel_id": pid,
            "source_location_id": loc1.json()["id"],
            "target_location_id": loc2.json()["id"],
            "relation_type": "road_to",
        })
        assert resp.status_code == 201

    async def test_get_edges_by_location(self, ctx):
        client, pid = ctx
        resp = await client.get(f"/api/geo/edges/by-location?novel_id={pid}&location_id={uuid.uuid4()}")
        assert resp.status_code == 200


class TestGeoEra:
    @pytest_asyncio.fixture
    async def ctx(self, async_client, db_session):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_create_era(self, ctx):
        client, pid = ctx
        resp = await client.post("/api/geo/eras", json={
            "novel_id": pid, "name": "古王朝时期", "order_index": 1,
        })
        assert resp.status_code == 201

    async def test_list_eras(self, ctx):
        client, pid = ctx
        await client.post("/api/geo/eras", json={"novel_id": pid, "name": "旧王朝", "order_index": 0})
        await client.post("/api/geo/eras", json={"novel_id": pid, "name": "新王朝", "order_index": 1})
        resp = await client.get(f"/api/geo/eras?novel_id={pid}")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        assert len(items) >= 1
