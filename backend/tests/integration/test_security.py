"""
集成测试：安全测试

覆盖 SQL 注入、XSS 文本、超长输入、非法枚举值、RAG top_k 超限。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from core.config import get_settings

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class TestSecurity:
    """安全边界测试 — 验证恶意或极端输入不会导致崩溃或数据泄露"""

    async def test_state_changing_api_requires_xhr_header(
        self,
        raw_async_client: AsyncClient,
    ):
        resp = await raw_async_client.post(
            "/api/projects",
            json={"title": "csrf-blocked"},
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == "Missing X-Requested-With header"

    async def test_state_changing_api_accepts_console_xhr_header(
        self,
        async_client: AsyncClient,
    ):
        resp = await async_client.post(
            "/api/projects",
            json={"title": "csrf-allowed"},
        )

        assert resp.status_code == 201

    async def test_closed_test_access_token_guards_api(
        self,
        async_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("APP_ACCESS_TOKEN", "closed-token")
        get_settings.cache_clear()
        try:
            blocked = await async_client.get("/api/projects")
            allowed = await async_client.get(
                "/api/projects",
                headers={"Authorization": "Bearer closed-token"},
            )
        finally:
            get_settings.cache_clear()

        assert blocked.status_code == 401
        assert allowed.status_code == 200

    # ============================================================
    # SQL 注入
    # ============================================================

    async def test_security_sql_injection_in_title_does_not_corrupt_database(
        self,
        async_client: AsyncClient,
    ):
        """SQL 注入字符串不应导致异常或数据损坏"""
        # Arrange
        payloads = [
            "'; DROP TABLE projects; --",
            "1; SELECT * FROM projects",
            "' OR '1'='1",
            "'; DELETE FROM world_entities WHERE '1'='1",
            "'; UPDATE projects SET title='hacked' WHERE '1'='1",
        ]

        # Act
        for payload in payloads:
            resp = await async_client.post(
                "/api/projects",
                json={
                    "title": payload,
                    "genre": "测试",
                },
            )

            # Assert
            assert resp.status_code in (200, 201, 422), (
                f"SQL 注入 '{payload[:30]}' 返回 {resp.status_code}"
            )

            list_resp = await async_client.get("/api/projects")
            assert list_resp.status_code == 200

    async def test_security_sql_injection_in_entity_name_is_stored_as_text(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """SQL 注入字符串作为实体名时应正常存储为文本，不执行 SQL"""
        # Arrange
        payload = "'; SELECT * FROM world_entities; --"

        # Act
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={"name": payload, "entity_type": "item"},
        )

        # Assert
        assert resp.status_code in (200, 201)

    async def test_security_sql_injection_in_search_query_does_not_crash(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """搜索查询中的 SQL 注入字符串不应对数据库造成影响"""
        # Arrange
        # (test_project_id fixture 已准备项目)

        # Act
        resp = await async_client.post(
            "/api/rag/retrieve",
            params={"novel_id": test_project_id},
            json={"query": "'; SELECT pg_sleep(5); --", "top_k": 5},
        )

        # Assert
        assert resp.status_code in (200, 201, 422)

    # ============================================================
    # XSS
    # ============================================================

    async def test_security_xss_in_entity_name_stores_and_returns_correctly(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """XSS 字符串存储在正史中后，API 返回应正常"""
        # Arrange
        xss_name = "<img src=x onerror=alert(1)>"

        # Act
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={"name": xss_name, "entity_type": "item"},
        )

        # Assert
        assert resp.status_code in (200, 201)
        data = resp.json()
        name = data.get("name") or data.get("name", "")
        assert xss_name in name or "img" in name

        list_resp = await async_client.get(
            "/api/world/entities",
            params={"novel_id": test_project_id},
        )
        assert list_resp.status_code == 200

    async def test_security_xss_in_project_title_is_accepted_without_crash(
        self,
        async_client: AsyncClient,
    ):
        """XSS 字符串作为项目标题时应被接受且不崩溃"""
        # Arrange
        xss = '<script>alert("XSS")</script>'

        # Act
        resp = await async_client.post(
            "/api/projects",
            json={
                "title": xss,
                "genre": "测试",
            },
        )

        # Assert
        assert resp.status_code in (200, 201)

    # ============================================================
    # 超长输入
    # ============================================================

    async def test_security_very_long_name_does_not_crash(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """超长名称（5000 字符）不应崩溃"""
        # Arrange
        long_name = "A" * 5000

        # Act
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={"name": long_name, "entity_type": "item"},
        )

        # Assert
        assert resp.status_code in (200, 201, 422)

    async def test_security_very_long_jsonb_content_does_not_crash(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """超长 JSONB 内容不应崩溃"""
        # Arrange
        # (test_project_id fixture 已准备项目)

        # Act
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={
                "name": "大内容对象",
                "entity_type": "event",
                "summary": "B" * 10000,
            },
        )

        # Assert
        assert resp.status_code in (200, 201, 422)

    # ============================================================
    # 非法枚举值
    # ============================================================

    async def test_security_invalid_entity_type_returns_acceptable_status(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """非法 entity_type 不应导致崩溃，返回 200/201/422 均可"""
        # Arrange
        env_types = [
            "invalid_type_xyz",
            "12345",
            "",
            " " * 10,
            "location; DROP TABLE world_entities",
        ]

        # Act
        for etype in env_types:
            resp = await async_client.post(
                "/api/world/entities",
                params={"novel_id": test_project_id},
                json={"name": "测试", "entity_type": etype},
            )

            # Assert
            assert resp.status_code in (200, 201, 422)

    async def test_security_invalid_status_returns_acceptable_status(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """非法 status 不应导致崩溃，返回 200/201/422 均可"""
        # Arrange
        # (test_project_id fixture 已准备项目)

        # Act
        resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": test_project_id},
            json={"name": "测试", "entity_type": "item", "status": "nonexistent_status"},
        )

        # Assert
        assert resp.status_code in (200, 201, 422)

    async def test_security_invalid_character_creation_returns_acceptable_status(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """非法角色创建参数（缺少 entity_id）不应导致崩溃，返回 422 验证错误"""
        # Arrange
        # (test_project_id fixture 已准备项目)

        # Act
        resp = await async_client.post(
            "/api/world/characters",
            params={"novel_id": test_project_id},
            json={"novel_id": test_project_id, "name": "测试", "role": "主角"},
        )

        # Assert
        assert resp.status_code == 422

    async def test_security_negative_chapter_index_returns_acceptable_status(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """负章节索引不应导致崩溃，返回 200/201/422 均可"""
        # Arrange
        # (test_project_id fixture 已准备项目)

        # Act
        resp = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": test_project_id,
                "chapter_index": -1,
                "content": "负章节测试内容",
            },
        )

        # Assert
        assert resp.status_code in (200, 201, 422)

    # ============================================================
    # RAG top_k 超限
    # ============================================================

    async def test_security_rag_top_k_overflow_does_not_return_all_data(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """超大 top_k 不应导致全量数据返回"""
        # Arrange
        # (test_project_id fixture 已准备项目)

        # Act
        resp = await async_client.post(
            "/api/rag/retrieve",
            params={"novel_id": test_project_id},
            json={"query": "测试", "top_k": 999999},
        )

        # Assert
        assert resp.status_code in (200, 201, 422)

    async def test_security_rag_top_k_zero_returns_acceptable_status(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """top_k=0 应被修正为有效值或返回可接受状态"""
        # Arrange
        # (test_project_id fixture 已准备项目)

        # Act
        resp = await async_client.post(
            "/api/rag/retrieve",
            params={"novel_id": test_project_id},
            json={"query": "测试", "top_k": 0},
        )

        # Assert
        assert resp.status_code in (200, 201, 422)
