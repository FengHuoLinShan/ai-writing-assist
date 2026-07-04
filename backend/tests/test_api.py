"""
API 分层测试 — 覆盖全部 11 个业务模块 + 系统端点

测试策略：
1. happy path：正 JSON 请求 → 200/201
2. error path：缺必填字段 → 422，无效 UUID → 422
3. novel_id 校验：跨小说访问 → 404
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.api]


# ============================================================
# System
# ============================================================


class TestApiSystem:
    """System API 层测试 — 覆盖 health / root 端点"""

    async def test_api_system_health_check_returns_200_or_503(
        self,
        async_client: AsyncClient,
    ):
        """健康检查端点返回 200 或 503（降级模式允许）"""
        # Arrange
        ...

        # Act
        resp = await async_client.get("/api/health")

        # Assert
        assert resp.status_code in (200, 503)

    async def test_api_llm_health_returns_sanitized_result(
        self,
        async_client: AsyncClient,
    ):
        """LLM health endpoint returns diagnostics without secrets."""
        from infrastructure.llm.health import LLMHealthResult

        with patch(
            "infrastructure.llm.health.check_llm_health",
            AsyncMock(
                return_value=LLMHealthResult(
                    ok=True,
                    model="deepseek-v4-flash",
                    base_url_host="opencode.ai",
                    message="LLM health check passed",
                )
            ),
        ):
            resp = await async_client.get("/api/health/llm")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["model"] == "deepseek-v4-flash"
        assert "key" not in str(data).lower()

    async def test_api_system_root_returns_modules_list(
        self,
        async_client: AsyncClient,
    ):
        """根端点返回包含 modules 列表的响应"""
        # Arrange
        ...

        # Act
        resp = await async_client.get("/")

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert "modules" in data
        assert len(data["modules"]) >= 7

    async def test_api_debug_frontend_errors_store_list_and_clear(
        self,
        async_client: AsyncClient,
    ):
        """前端错误调试端点保留最近错误并支持清空。"""
        await async_client.delete("/api/debug/frontend-errors")

        payload = {
            "frontendId": 7,
            "level": "error",
            "type": "runtime",
            "message": "Uncaught TypeError: failed",
            "view": "map",
            "request": {"method": "POST", "Authorization": "Bearer secret-token"},
        }

        created = await async_client.post("/api/debug/frontend-errors", json=payload)
        assert created.status_code == 202
        assert created.json()["stored"] is True

        listed = await async_client.get("/api/debug/frontend-errors")
        assert listed.status_code == 200
        data = listed.json()
        assert data["total"] == 1
        assert data["items"][0]["message"] == "Uncaught TypeError: failed"
        assert data["items"][0]["request"]["Authorization"] == "[redacted]"

        cleared = await async_client.delete("/api/debug/frontend-errors")
        assert cleared.status_code == 200
        assert cleared.json()["cleared"] == 1

    async def test_api_debug_frontend_errors_rejects_warning_level(
        self,
        async_client: AsyncClient,
    ):
        """后端只接收真正的前端 error，warning 留给前端用户提示。"""
        resp = await async_client.post(
            "/api/debug/frontend-errors",
            json={"level": "warning", "message": "当前项目暂无地图"},
        )

        assert resp.status_code == 422


# ============================================================
# Project
# ============================================================


class TestApiProject:
    """Project API 层测试 — 覆盖 happy path / error path / 边界条件"""

    async def test_api_project_create_with_valid_data_returns_201(
        self,
        async_client: AsyncClient,
    ):
        """使用有效数据创建项目返回 201"""
        # Arrange
        payload = {"title": "新小说", "genre": "奇幻"}

        # Act
        resp = await async_client.post("/api/projects", json=payload)

        # Assert
        assert resp.status_code in (200, 201)

    async def test_api_project_list_returns_items(
        self,
        async_client: AsyncClient,
    ):
        """项目列表端点返回包含 items 的响应"""
        # Arrange
        ...

        # Act
        resp = await async_client.get("/api/projects")

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data or isinstance(data, list)

    async def test_api_project_create_missing_title_returns_422(
        self,
        async_client: AsyncClient,
    ):
        """缺少必填字段 title 时创建项目返回 422"""
        # Arrange
        payload = {"genre": "奇幻"}

        # Act
        resp = await async_client.post("/api/projects", json=payload)

        # Assert
        assert resp.status_code == 422

    async def test_api_project_get_not_found_returns_404(
        self,
        async_client: AsyncClient,
    ):
        """获取不存在的项目返回 404"""
        # Arrange
        missing_id = "00000000-0000-0000-0000-000000000000"

        # Act
        resp = await async_client.get(f"/api/projects/{missing_id}")

        # Assert
        assert resp.status_code == 404

    async def test_api_project_get_invalid_uuid_returns_422(
        self,
        async_client: AsyncClient,
    ):
        """使用无效 UUID 格式获取项目返回 422"""
        # Arrange
        invalid_id = "not-a-uuid"

        # Act
        resp = await async_client.get(f"/api/projects/{invalid_id}")

        # Assert
        assert resp.status_code == 422

    async def test_api_project_update_with_valid_data_returns_200_or_204(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """使用有效数据更新项目返回 200 或 204"""
        # Arrange
        payload = {"title": "改"}

        # Act
        resp = await async_client.put(f"/api/projects/{test_project_id}", json=payload)

        # Assert
        assert resp.status_code in (200, 204)

    async def test_api_project_delete_existing_returns_200_or_204(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """删除存在的项目返回 200 或 204"""
        # Arrange
        ...

        # Act
        resp = await async_client.delete(f"/api/projects/{test_project_id}")

        # Assert
        assert resp.status_code in (200, 204)


# ============================================================
# World — 世界对象
# ============================================================


class TestApiWorld:
    """World API 层测试 — 覆盖 happy path / error path / 边界条件"""

    async def test_api_world_create_entity_with_valid_data_returns_201(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """使用有效数据创建世界实体返回 201"""
        # Arrange
        payload = {"name": "测试王国", "entity_type": "faction"}

        # Act
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json=payload,
        )

        # Assert
        assert resp.status_code in (200, 201)

    async def test_api_world_create_entity_missing_name_returns_422(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """缺少必填字段 name 时创建世界实体返回 422"""
        # Arrange
        payload = {"entity_type": "faction"}

        # Act
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json=payload,
        )

        # Assert
        assert resp.status_code == 422

    async def test_api_world_list_entities_returns_200(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """列出世界实体返回 200"""
        # Arrange
        ...

        # Act
        resp = await async_client.get(
            "/api/world/entities",
            params={"novel_id": test_project_id},
        )

        # Assert
        assert resp.status_code == 200

    async def test_api_world_get_entity_not_found_returns_404(
        self,
        async_client: AsyncClient,
    ):
        """获取不存在的实体返回 404"""
        # Arrange
        missing_id = "00000000-0000-0000-0000-000000000000"
        missing_novel_id = "00000000-0000-0000-0000-000000000000"

        # Act
        resp = await async_client.get(
            f"/api/world/entities/{missing_id}",
            params={"novel_id": missing_novel_id},
        )

        # Assert
        assert resp.status_code == 404

    async def test_api_world_get_entity_invalid_uuid_returns_422(
        self,
        async_client: AsyncClient,
    ):
        """使用无效 UUID 获取实体返回 422"""
        # Arrange
        invalid_id = "bad-id"
        invalid_novel_id = "bad-id"

        # Act
        resp = await async_client.get(
            f"/api/world/entities/{invalid_id}",
            params={"novel_id": invalid_novel_id},
        )

        # Assert
        assert resp.status_code == 422

    async def test_api_world_dedup_not_found_returns_404(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """对不存在候选实体执行去重返回 404"""
        # Arrange
        missing_id = "00000000-0000-0000-0000-000000000000"

        # Act
        resp = await async_client.post(
            f"/api/world/candidates/{missing_id}/dedup",
            params={"novel_id": test_project_id},
        )

        # Assert
        assert resp.status_code == 404

    async def test_api_world_create_relationship_with_valid_data_returns_201(
        self,
        async_client: AsyncClient,
        test_project_id: str,
        test_entity_id: str,
    ):
        """使用有效数据创建关系返回 201"""
        # Arrange
        target_resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={"name": "目标势力", "entity_type": "faction"},
        )
        assert target_resp.status_code in (200, 201)
        target_id = target_resp.json().get("id") or target_resp.json()["entity_id"]

        payload = {
            "source_id": test_entity_id,
            "target_id": target_id,
            "relation_type": "ally_of",
        }

        # Act
        resp = await async_client.post(
            "/api/world/relations",
            params={"novel_id": test_project_id},
            json=payload,
        )

        # Assert
        assert resp.status_code in (200, 201)


# ============================================================
# Memory — 事件溯源世界全景
# ============================================================


class TestApiMemory:
    """Memory API 层测试 — 覆盖 happy path / error path / 边界条件"""

    async def test_api_memory_get_panorama_empty_returns_empty_entities_and_relations(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """无数据时获取全景返回空的实体和关系列表"""
        # Arrange
        ...

        # Act
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/panorama?chapter_index=1",
        )

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities"] == []
        assert data["relations"] == []

    async def test_api_memory_list_events_empty_returns_empty_items_and_zero_total(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """无事件时列表返回空 items 且 total 为 0"""
        # Arrange
        ...

        # Act
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/events",
        )

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] == 0

    async def test_api_memory_entity_timeline_not_found_returns_zero_total(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """查询不存在实体的时间线返回空结果（total 为 0）"""
        # Arrange
        missing_id = "00000000-0000-0000-0000-000000000000"

        # Act
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/events/{missing_id}/timeline",
        )

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    async def test_api_memory_capture_snapshot_returns_201(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """捕获快照端点返回 201"""
        # Arrange
        ...

        # Act
        resp = await async_client.post(
            f"/api/novels/{test_project_id}/memories/snapshots/capture?chapter_index=1",
        )

        # Assert
        assert resp.status_code == 201

    async def test_api_memory_list_snapshots_empty_returns_empty_items(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """无快照时列表返回空 items"""
        # Arrange
        ...

        # Act
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/snapshots",
        )

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] == 0

    async def test_api_memory_trigger_rebuild_returns_200(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """触发重建端点返回 200"""
        # Arrange
        ...

        # Act
        resp = await async_client.post(
            f"/api/novels/{test_project_id}/memories/rebuild?from_chapter=1",
        )

        # Assert
        assert resp.status_code == 200

    async def test_api_memory_get_status_returns_correct_structure(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """获取状态端点返回包含 has_stale 和 latest_chapter 的结构"""
        # Arrange
        ...

        # Act
        resp = await async_client.get(
            f"/api/novels/{test_project_id}/memories/status",
        )

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert "has_stale" in data
        assert "latest_chapter" in data


# ============================================================
# RAG — 检索增强
# ============================================================


class TestApiRag:
    """RAG API 层测试 — 覆盖 happy path / error path / 边界条件"""

    async def test_api_rag_create_chunk_with_valid_data_returns_201(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """使用有效数据创建文本片段返回 201"""
        # Arrange
        payload = {
            "source_type": "world_entity",
            "text": "测试文本片段",
        }

        # Act
        resp = await async_client.post(
            "/api/rag/chunks",
            params={"novel_id": test_project_id},
            json=payload,
        )

        # Assert
        assert resp.status_code in (200, 201)

    async def test_api_rag_list_chunks_returns_200(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """列出文本片段返回 200"""
        # Arrange
        ...

        # Act
        resp = await async_client.get(
            "/api/rag/chunks",
            params={"novel_id": test_project_id},
        )

        # Assert
        assert resp.status_code == 200

    async def test_api_rag_retrieve_with_valid_query_returns_chunks(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """使用有效查询检索返回包含 chunks 的响应"""
        # Arrange
        payload = {"query": "测试", "top_k": 5}

        # Act
        resp = await async_client.post(
            "/api/rag/retrieve",
            params={"novel_id": test_project_id},
            json=payload,
        )

        # Assert
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "chunks" in data

    async def test_api_rag_retrieve_top_k_zero_returns_acceptable_status(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """top_k 为 0 时检索返回可接受的状态码"""
        # Arrange
        payload = {"query": "测试", "top_k": 0}

        # Act
        resp = await async_client.post(
            "/api/rag/retrieve",
            params={"novel_id": test_project_id},
            json=payload,
        )

        # Assert
        assert resp.status_code in (200, 201, 422)

    async def test_api_rag_split_text_returns_200_or_201(
        self,
        async_client: AsyncClient,
    ):
        """文本拆分端点返回 200 或 201"""
        # Arrange
        ...

        # Act
        resp = await async_client.post(
            "/api/rag/chunks/split",
            params={"text": "测试" + "a" * 100, "method": "paragraph"},
        )

        # Assert
        assert resp.status_code in (200, 201)


# ============================================================
# Context — 上下文编译
# ============================================================


class TestApiContext:
    """Context API 层测试 — 覆盖 happy path / error path / 边界条件"""

    async def test_api_context_compile_with_valid_data_returns_task_in_response(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """使用有效数据编译上下文返回包含 task 的响应"""
        # Arrange
        payload = {
            "novel_id": test_project_id,
            "task": "测试任务",
            "scope": "project",
        }

        # Act
        resp = await async_client.post(
            "/api/context/compile",
            json=payload,
        )

        # Assert
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "task" in data

    async def test_api_context_compile_invalid_scope_returns_400(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """使用无效 scope 编译上下文返回 400"""
        # Arrange
        payload = {
            "novel_id": test_project_id,
            "task": "测试",
            "scope": "invalid_scope",
        }

        # Act
        resp = await async_client.post(
            "/api/context/compile",
            json=payload,
        )

        # Assert
        assert resp.status_code == 400

    async def test_api_context_render_with_valid_data_returns_markdown(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """使用有效数据渲染上下文返回包含 markdown 的响应"""
        # Arrange
        payload = {
            "novel_id": test_project_id,
            "task": "生成章节",
            "scope": "world",
        }

        # Act
        resp = await async_client.post(
            "/api/context/render",
            json=payload,
        )

        # Assert
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "markdown" in data


# ============================================================
# Writing — 草稿
# ============================================================


class TestApiWriting:
    """Writing API 层测试 — 覆盖 happy path / error path / 边界条件"""

    async def test_api_writing_create_draft_with_valid_data_returns_201(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """使用有效数据创建草稿返回 201"""
        # Arrange
        payload = {
            "novel_id": test_project_id,
            "chapter_index": 1,
            "content": "第一章正文...",
        }

        # Act
        resp = await async_client.post(
            "/api/writing/drafts",
            json=payload,
        )

        # Assert
        assert resp.status_code in (200, 201)

    async def test_api_writing_get_latest_draft_returns_200_or_404(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """获取最新草稿返回 200 或 404"""
        # Arrange
        chapter_index = 1

        # Act
        resp = await async_client.get(
            f"/api/writing/chapters/{chapter_index}/draft",
            params={"novel_id": test_project_id},
        )

        # Assert
        assert resp.status_code in (200, 404)

    async def test_api_writing_get_draft_not_found_returns_404_or_422(
        self,
        async_client: AsyncClient,
    ):
        """获取不存在的草稿返回 404 或 422"""
        # Arrange
        missing_id = "00000000-0000-0000-0000-000000000000"

        # Act
        resp = await async_client.get(
            f"/api/writing/drafts/{missing_id}",
        )

        # Assert
        assert resp.status_code in (404, 422)


# ============================================================
# Tasks — 任务队列
# ============================================================


class TestApiTasks:
    """Tasks API 层测试 — 覆盖 happy path / error path / 边界条件"""

    async def test_api_tasks_create_with_valid_type_returns_acceptable_status(
        self,
        async_client: AsyncClient,
    ):
        """使用有效任务类型创建任务返回可接受的状态码"""
        # Arrange
        payload = {"task_type": "embedding_build"}

        # Act
        resp = await async_client.post(
            "/api/tasks",
            json=payload,
        )

        # Assert
        assert resp.status_code in (200, 201, 400)

    async def test_api_tasks_get_not_found_returns_404(
        self,
        async_client: AsyncClient,
    ):
        """获取不存在的任务返回 404"""
        # Arrange
        missing_id = "00000000-0000-0000-0000-000000000000"

        # Act
        resp = await async_client.get(
            f"/api/tasks/{missing_id}",
            params={"novel_id": "00000000-0000-0000-0000-000000000001"},
        )

        # Assert
        assert resp.status_code == 404
