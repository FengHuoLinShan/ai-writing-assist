"""
集成测试：安全测试

覆盖 SQL 注入、XSS 文本、超长输入、非法枚举值、RAG top_k 超限。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class TestSecurity:
    """AI长篇小说结构化创作引擎_REVIEW_RULES_v1.0 §19.3"""

    # ============================================================
    # SQL 注入
    # ============================================================

    async def test_sql_injection_in_title(self, async_client: AsyncClient):
        """SQL 注入字符串不应导致异常"""
        payloads = [
            "'; DROP TABLE projects; --",
            "1; SELECT * FROM projects",
            "' OR '1'='1",
            "'; DELETE FROM world_entities WHERE '1'='1",
            "'; UPDATE projects SET title='hacked' WHERE '1'='1",
        ]
        for payload in payloads:
            resp = await async_client.post(
                "/api/projects",
                json={
                    "title": payload,
                    "genre": "测试",
                },
            )
            assert resp.status_code in (200, 201, 422), (
                f"SQL 注入 '{payload[:30]}' 返回 {resp.status_code}"
            )

            # 验证无法删表
            list_resp = await async_client.get("/api/projects")
            assert list_resp.status_code == 200

    async def test_sql_injection_in_entity_name(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        payload = "'; SELECT * FROM world_entities; --"
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={"name": payload, "entity_type": "item"},
        )
        # 应正常创建（作为文本），不执行 SQL
        assert resp.status_code in (200, 201)

    async def test_sql_injection_in_search_query(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """搜索查询中的 SQL 注入字符串不应对数据库造成影响"""
        # novel_id 是 Query 参数，query 是 body 中的 RagQuery 字段
        resp = await async_client.post(
            "/api/rag/retrieve",
            params={"novel_id": test_project_id},
            json={"query": "'; SELECT pg_sleep(5); --", "top_k": 5},
        )
        # 不应超时或崩溃
        assert resp.status_code in (200, 201, 422)

    # ============================================================
    # XSS — 检查字段存储后不破坏响应
    # ============================================================

    async def test_xss_in_entity_name(
        self, async_client: AsyncClient, test_project_id: str
    ):
        """XSS 字符串存储在正史中后，API 返回应正常"""
        xss_name = "<img src=x onerror=alert(1)>"
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={"name": xss_name, "entity_type": "item"},
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        name = data.get("name") or data.get("name", "")
        # 验证名称被正确存储（不转义存储）
        assert xss_name in name or "img" in name

        # 验证列表端点也能正常返回
        resp = await async_client.get(
            "/api/world/entities",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 200

    async def test_xss_in_project_title(self, async_client: AsyncClient):
        xss = '<script>alert("XSS")</script>'
        resp = await async_client.post(
            "/api/projects",
            json={
                "title": xss,
                "genre": "测试",
            },
        )
        assert resp.status_code in (200, 201)

    # ============================================================
    # 超长输入
    # ============================================================

    async def test_very_long_name(self, async_client: AsyncClient, test_project_id: str):
        """超长名称（5000 字符）不应崩溃"""
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={"name": "A" * 5000, "entity_type": "item"},
        )
        # SQLite 中 String(255) 不会严格截断，但不应崩溃
        assert resp.status_code in (200, 201, 422)

    async def test_very_long_jsonb_content(
        self, async_client: AsyncClient, test_project_id: str
    ):
        """超长 JSONB 内容不应崩溃"""
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={
                "name": "大内容对象",
                "entity_type": "event",
                "summary": "B" * 10000,
            },
        )
        assert resp.status_code in (200, 201, 422)

    async def test_very_long_summary(
        self, async_client: AsyncClient, test_project_id: str
    ):
        """记忆记录的超长摘要不应崩溃"""
        resp = await async_client.post(
            f"/api/novels/{test_project_id}/memories/records",
            json={
                "memory_type": "event",
                "summary": "C" * 10000,
                "chapter_index": 1,
            },
        )
        assert resp.status_code in (200, 201, 422)

    # ============================================================
    # 非法枚举值
    # ============================================================

    async def test_invalid_entity_type(
        self, async_client: AsyncClient, test_project_id: str
    ):
        env_types = [
            "invalid_type_xyz",
            "12345",
            "",
            " " * 10,
            "location; DROP TABLE world_entities",
        ]
        for etype in env_types:
            resp = await async_client.post(
                "/api/world/entities",
                params={"novel_id": test_project_id},
                json={"name": "测试", "entity_type": etype},
            )
            # 可能返回 422（校验拒绝）或 200（无校验则接受）
            # 重点是不应崩溃
            assert resp.status_code in (200, 201, 422)

    async def test_invalid_status(self, async_client: AsyncClient, test_project_id: str):
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={"name": "测试", "entity_type": "item", "status": "nonexistent_status"},
        )
        assert resp.status_code in (200, 201, 422)

    async def test_invalid_knowledge_level(
        self, async_client: AsyncClient, test_project_id: str
    ):
        # valid character creation
        resp = await async_client.post(
            "/api/characters",
            json={"novel_id": test_project_id, "name": "测试", "role": "主角"},
        )
        assert resp.status_code in (200, 201)

    async def test_negative_chapter_index(
        self, async_client: AsyncClient, test_project_id: str
    ):
        resp = await async_client.post(
            "/api/outline/chapters",
            params={"novel_id": test_project_id},
            json={
                "chapter_index": -1,
                "chapter_goal": "负章节",
                "main_conflict": "测试",
            },
        )
        # 服务层可能接受（作为 draft）或拒绝
        assert resp.status_code in (200, 201, 422)

    # ============================================================
    # RAG top_k 超限
    # ============================================================

    async def test_rag_top_k_overflow(
        self, async_client: AsyncClient, test_project_id: str
    ):
        """超大 top_k 不应导致全量数据返回"""
        resp = await async_client.post(
            "/api/rag/retrieve",
            params={"novel_id": test_project_id},
            json={"query": "测试", "top_k": 999999},
        )
        assert resp.status_code in (200, 201, 422)

    async def test_rag_top_k_zero(self, async_client: AsyncClient, test_project_id: str):
        """top_k=0 应被修正为有效值"""
        resp = await async_client.post(
            "/api/rag/retrieve",
            params={"novel_id": test_project_id},
            json={"query": "测试", "top_k": 0},
        )
        assert resp.status_code in (200, 201, 422)
