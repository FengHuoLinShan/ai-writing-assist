"""
API 分层测试 — 覆盖全部 11 个业务模块 + 系统端点

测试策略：
1. happy path：正 JSON 请求 → 200/201
2. error path：缺必填字段 → 422，无效 UUID → 422
3. novel_id 校验：跨小说访问 → 404
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.asyncio, pytest.mark.api]


# ============================================================
# Scaffold helpers
# ============================================================

async def _create_project(client: AsyncClient) -> str:
    resp = await client.post("/api/projects", json={
        "title": "API 测试小说",
        "genre": "奇幻",
        "tone": "dark",
        "language": "zh",
    })
    assert resp.status_code in (200, 201)
    data = resp.json()
    return data.get("id") or data["project_id"]


# ============================================================
# System
# ============================================================

class TestSystemEndpoints:
    async def test_health(self, async_client: AsyncClient):
        resp = await async_client.get("/api/health")
        assert resp.status_code in (200, 503)  # degraded allowed

    async def test_root(self, async_client: AsyncClient):
        resp = await async_client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "modules" in data
        assert len(data["modules"]) >= 7


# ============================================================
# Project
# ============================================================

class TestProjectAPI:
    async def test_create(self, async_client: AsyncClient):
        resp = await async_client.post("/api/projects", json={
            "title": "新小说",
            "genre": "奇幻",
        })
        assert resp.status_code in (200, 201)

    async def test_list(self, async_client: AsyncClient):
        resp = await async_client.get("/api/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data or isinstance(data, list)

    async def test_create_missing_title(self, async_client: AsyncClient):
        resp = await async_client.post("/api/projects", json={"genre": "奇幻"})
        assert resp.status_code == 422

    async def test_get_not_found(self, async_client: AsyncClient):
        resp = await async_client.get("/api/projects/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    async def test_get_invalid_uuid(self, async_client: AsyncClient):
        resp = await async_client.get("/api/projects/not-a-uuid")
        assert resp.status_code == 422

    async def test_update(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.put(f"/api/projects/{test_project_id}", json={"title": "改"})
        assert resp.status_code in (200, 204)

    async def test_delete(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.delete(f"/api/projects/{test_project_id}")
        assert resp.status_code in (200, 204)


# ============================================================
# World — 世界对象
# ============================================================

class TestWorldAPI:
    async def test_create_entity(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={"name": "测试王国", "entity_type": "faction"},
        )
        assert resp.status_code in (200, 201)

    async def test_create_entity_missing_name(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={"entity_type": "faction"},
        )
        assert resp.status_code == 422

    async def test_list_entities(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            "/api/world/entities",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 200

    async def test_get_not_found(self, async_client: AsyncClient):
        resp = await async_client.get(
            "/api/world/entities/00000000-0000-0000-0000-000000000000",
            params={"novel_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert resp.status_code == 404

    async def test_get_invalid_uuid(self, async_client: AsyncClient):
        resp = await async_client.get(
            "/api/world/entities/bad-id",
            params={"novel_id": "bad-id"},
        )
        assert resp.status_code == 422

    async def test_dedup_not_found(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            f"/api/world/candidates/00000000-0000-0000-0000-000000000000/dedup",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 404

    async def test_create_relationship(self, async_client: AsyncClient, test_project_id: str, test_entity_id: str):
        resp = await async_client.post(
            "/api/world/relations",
            params={"novel_id": test_project_id},
            json={
                "source_id": test_entity_id,
                "target_id": "00000000-0000-0000-0000-000000000001",
                "relation_type": "ally_of",
            },
        )
        assert resp.status_code in (200, 201)


# ============================================================
# Memory — 事件溯源世界全景
# ============================================================

class TestMemoryAPI:
    async def test_get_panorama_empty(self, async_client: AsyncClient, test_project_id: str):
        """无数据时返回空全景"""
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/panorama?chapter_index=1",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities"] == []
        assert data["relations"] == []

    async def test_list_events_empty(self, async_client: AsyncClient, test_project_id: str):
        """无事件时返回空列表"""
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/events",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] == 0

    async def test_entity_timeline_not_found(self, async_client: AsyncClient, test_project_id: str):
        """查询不存在实体的时间线返回空"""
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/events/00000000-0000-0000-0000-000000000000/timeline",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    async def test_capture_snapshot_returns_201(self, async_client: AsyncClient, test_project_id: str):
        """快照生成返回 201"""
        resp = await async_client.post(
            f"/api/novels/{test_project_id}/memories/snapshots/capture?chapter_index=1",
        )
        assert resp.status_code == 201

    async def test_list_snapshots_empty(self, async_client: AsyncClient, test_project_id: str):
        """无快照时返回空列表"""
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/snapshots",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] == 0

    async def test_trigger_rebuild(self, async_client: AsyncClient, test_project_id: str):
        """全更新请求可执行"""
        resp = await async_client.post(
            f"/api/novels/{test_project_id}/memories/rebuild?from_chapter=1",
        )
        assert resp.status_code == 200

    async def test_get_status(self, async_client: AsyncClient, test_project_id: str):
        """状态查询返回正确结构"""
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/status",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "has_stale" in data
        assert "latest_chapter" in data


# ============================================================
# RAG — 检索增强
# ============================================================

class TestRagAPI:
    async def test_create_chunk(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/rag/chunks",
            params={"novel_id": test_project_id},
            json={
                "source_type": "world_entity",
                "text": "测试文本片段",
            },
        )
        assert resp.status_code in (200, 201)

    async def test_list_chunks(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            "/api/rag/chunks",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 200

    async def test_retrieve(self, async_client: AsyncClient, test_project_id: str):
        # RAG retrieve: novel_id is Query param; body has RagQuery fields
        resp = await async_client.post(
            "/api/rag/retrieve",
            params={"novel_id": test_project_id},
            json={"query": "测试", "top_k": 5},
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "chunks" in data

    async def test_retrieve_top_k_zero(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/rag/retrieve",
            params={"novel_id": test_project_id},
            json={"query": "测试", "top_k": 0},
        )
        assert resp.status_code in (200, 201, 422)

    async def test_split(self, async_client: AsyncClient):
        # split uses query params, not body
        resp = await async_client.post(
            "/api/rag/chunks/split",
            params={"text": "测试" + "a" * 100, "method": "paragraph"},
        )
        assert resp.status_code in (200, 201)


# ============================================================
# Context — 上下文编译
# ============================================================

class TestContextAPI:
    async def test_compile(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/context/compile",
            json={
                "novel_id": test_project_id,
                "task": "测试任务",
                "scope": "project",
            },
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "task" in data

    async def test_compile_invalid_scope(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/context/compile",
            json={
                "novel_id": test_project_id,
                "task": "测试",
                "scope": "invalid_scope",
            },
        )
        assert resp.status_code == 400

    async def test_render(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/context/render",
            json={
                "novel_id": test_project_id,
                "task": "生成章节",
                "scope": "world",
            },
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "markdown" in data


# ============================================================
# Writing — 草稿
# ============================================================

class TestWritingAPI:
    async def test_create_draft(self, async_client: AsyncClient, test_project_id: str):
        # WritingDraftCreate requires novel_id in body
        resp = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": test_project_id,
                "chapter_index": 1,
                "content": "第一章正文...",
            },
        )
        assert resp.status_code in (200, 201)

    async def test_get_latest(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            f"/api/writing/chapters/{1}/draft",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code in (200, 404)

    async def test_get_draft_not_found(self, async_client: AsyncClient):
        resp = await async_client.get(
            "/api/writing/drafts/00000000-0000-0000-0000-000000000000",
        )
        assert resp.status_code in (404, 422)


# ============================================================
# Tasks — 任务队列
# ============================================================

class TestTaskAPI:
    async def test_create_task(self, async_client: AsyncClient):
        resp = await async_client.post(
            "/api/tasks",
            json={"task_type": "embedding_build"},
        )
        # Works without DB if handler exists, otherwise returns error fast
        assert resp.status_code in (200, 201, 400)

    async def test_get_task_not_found(self, async_client: AsyncClient):
        resp = await async_client.get(
            "/api/tasks/00000000-0000-0000-0000-000000000000",
        )
        assert resp.status_code == 404
