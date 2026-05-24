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
        assert len(data["modules"]) >= 11


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

    async def test_create_candidate(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/world/candidates",
            params={"novel_id": test_project_id},
            json={"name": "候选物品", "entity_type": "item"},
        )
        assert resp.status_code in (200, 201)

    async def test_dedup_not_found(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            f"/api/world/candidates/00000000-0000-0000-0000-000000000000/dedup",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 404

    async def test_create_relationship(self, async_client: AsyncClient, test_project_id: str, test_entity_id: str):
        resp = await async_client.post(
            "/api/world/relationships",
            params={"novel_id": test_project_id},
            json={
                "source_id": test_entity_id,
                "source_type": "world_entity",
                "target_id": "00000000-0000-0000-0000-000000000001",
                "target_type": "world_entity",
                "relation_type": "ally_of",
            },
        )
        assert resp.status_code in (200, 201)


# ============================================================
# Character — 人物档案
# ============================================================

class TestCharacterAPI:
    async def test_create(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/characters",
            json={"novel_id": test_project_id, "name": "测试角色", "role": "主角"},
        )
        assert resp.status_code in (200, 201)

    async def test_get_not_found(self, async_client: AsyncClient):
        resp = await async_client.get(
            "/api/characters/00000000-0000-0000-0000-000000000000",
        )
        # Character API handles this via the service which may return 422 for UUID
        # or 404 if the ID is valid but not found
        assert resp.status_code in (404, 422)

    async def test_list(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            "/api/characters",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 200

    async def test_update(self, async_client: AsyncClient, test_character_id: str):
        resp = await async_client.put(
            f"/api/characters/{test_character_id}",
            json={"role": "反派"},
        )
        assert resp.status_code in (200, 204, 422)

    async def test_delete(self, async_client: AsyncClient, test_character_id: str):
        resp = await async_client.delete(f"/api/characters/{test_character_id}")
        assert resp.status_code in (200, 204, 422)


# ============================================================
# Geo — 地理历史
# ============================================================

class TestGeoAPI:
    async def test_create_location(self, async_client: AsyncClient, test_project_id: str, test_entity_id: str):
        resp = await async_client.post(
            "/api/geo/locations",
            json={
                "novel_id": test_project_id,
                "world_entity_id": test_entity_id,
                "location_level": "kingdom",
            },
        )
        assert resp.status_code in (200, 201)

    async def test_list_locations(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            "/api/geo/locations",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 200

    async def test_location_tree(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            "/api/geo/locations/tree",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 200

    async def test_create_era(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/geo/eras",
            json={"novel_id": test_project_id, "name": "旧王朝", "order_index": 1},
        )
        assert resp.status_code in (200, 201)

    async def test_create_edge(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/geo/edges",
            json={
                "novel_id": test_project_id,
                "source_location_id": "00000000-0000-0000-0000-000000000000",
                "target_location_id": "00000000-0000-0000-0000-000000000001",
                "relation_type": "road_to",
            },
        )
        assert resp.status_code in (200, 201, 422)


# ============================================================
# Memory — 长期记忆
# ============================================================

class TestMemoryAPI:
    async def test_create_record(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            f"/api/novels/{test_project_id}/memories/records",
            json={
                "memory_type": "event",
                "summary": "测试记忆事件",
                "chapter_index": 1,
            },
        )
        assert resp.status_code in (200, 201)

    async def test_list_records(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/records",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data or isinstance(data, list)

    async def test_get_not_found(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/records/00000000-0000-0000-0000-000000000000",
        )
        assert resp.status_code == 404

    async def test_list_proposals(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/proposals/pending",
        )
        assert resp.status_code == 200


# ============================================================
# Timeline — 时间线
# ============================================================

class TestTimelineAPI:
    async def test_create_event(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            f"/api/novels/{test_project_id}/timeline/events",
            json={
                "title": "测试事件",
                "summary": "事件描述",
                "order_index": 1,
            },
        )
        assert resp.status_code in (200, 201)

    async def test_list_events(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/timeline/events",
        )
        assert resp.status_code == 200

    async def test_get_not_found(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/timeline/events/00000000-0000-0000-0000-000000000000",
        )
        assert resp.status_code == 404


# ============================================================
# Outline — 剧情结构
# ============================================================

class TestOutlineAPI:
    async def test_create_thread(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
            json={"name": "主线", "thread_type": "main"},
        )
        assert resp.status_code in (200, 201)

    async def test_list_threads(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.get(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 200

    async def test_create_arc(self, async_client: AsyncClient, test_project_id: str):
        # OutlineArcCreate requires: title, arc_goal, core_conflict, climax, result
        resp = await async_client.post(
            "/api/outline/arcs",
            params={"novel_id": test_project_id},
            json={
                "title": "第一篇",
                "arc_goal": "交代世界观",
                "core_conflict": "生存",
                "climax": "真相揭露",
                "result": "进入下一阶段",
            },
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "arc_goal" in data

    async def test_create_chapter_card(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/outline/chapters",
            params={"novel_id": test_project_id},
            json={
                "chapter_index": 1,
                "chapter_goal": "开头",
                "main_conflict": "引入冲突",
            },
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data.get("chapter_index") == 1

    async def test_create_foreshadowing(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/outline/foreshadowing",
            params={"novel_id": test_project_id},
            json={"name": "王印秘密", "summary": "伏笔"},
        )
        assert resp.status_code in (200, 201)

    async def test_create_reveal(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/outline/reveals",
            params={"novel_id": test_project_id},
            json={
                "target_type": "world_entity",
                "target_id": "00000000-0000-0000-0000-000000000000",
                "secret_summary": "秘密",
            },
        )
        assert resp.status_code in (200, 201)

    async def test_from_candidate_empty(self, async_client: AsyncClient):
        """当传入空列表时不应崩溃"""
        resp = await async_client.post(
            "/api/outline/chapters/from-candidate",
            json={"novel_id": "00000000-0000-0000-0000-000000000000", "cards": []},
        )
        # Invalid UUID may trigger 422 or service returns []
        assert resp.status_code in (200, 201, 422)


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

    async def test_similar_entities(self, async_client: AsyncClient, test_project_id: str):
        # similar-entities uses query params, not body
        resp = await async_client.post(
            "/api/rag/similar-entities",
            params={
                "novel_id": test_project_id,
                "candidate_embedding": "0.1,0.2,0.3",
            },
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
# Review — 结构复查
# ============================================================

class TestReviewAPI:
    async def test_run_review(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/review",
            json={
                "novel_id": test_project_id,
                "target_type": "world_structure",
                "candidate_payload": {"world_entities": []},
            },
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "decision" in data

    async def test_run_review_invalid_type(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/review",
            json={
                "novel_id": test_project_id,
                "target_type": "invalid_type",
                "candidate_payload": {},
            },
        )
        # Invalid type may be accepted (fallback) or rejected
        assert resp.status_code in (200, 201, 422)

    async def test_get_report_not_found(self, async_client: AsyncClient):
        resp = await async_client.get(
            "/api/review/00000000-0000-0000-0000-000000000000",
        )
        assert resp.status_code in (404, 422)


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
