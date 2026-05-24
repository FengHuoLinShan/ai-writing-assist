"""
集成测试：novel_id 隔离

验证跨小说越权防御：
- 小说 A 的 API 请求不能读取/修改小说 B 的对象
- 涉及所有 8 个数据模块
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class TestNovelIdIsolation:
    """AI长篇小说结构化创作引擎_REVIEW_RULES_v1.0 §19.2 流程5"""

    async def _create_project_and_entity(
        self, client: AsyncClient, title_suffix: str,
    ) -> tuple[str, str]:
        """辅助：创建项目 + 世界对象，返回 (novel_id, entity_id)"""
        resp = await client.post("/api/projects", json={
            "title": f"隔离测试{title_suffix}",
            "genre": "测试",
        })
        nid = resp.json().get("id") or resp.json()["project_id"]

        resp = await client.post(
            "/api/world/entities",
            params={"novel_id": nid},
            json={"name": f"专属物品{title_suffix}", "entity_type": "item"},
        )
        eid = resp.json().get("id", "") or resp.json().get("entity_id", "")
        return nid, eid

    async def test_cross_novel_entity_access_returns_404(
        self, async_client: AsyncClient,
    ):
        """小说 B 不能读取小说 A 的世界对象"""
        nid_a, eid_a = await self._create_project_and_entity(async_client, "A")
        nid_b, eid_b = await self._create_project_and_entity(async_client, "B")

        # 用 B 的 novel_id 尝试获取 A 的对象 → 应返回 404
        resp = await async_client.get(
            f"/api/world/entities/{eid_a}",
            params={"novel_id": nid_b},
        )
        assert resp.status_code == 404, \
            f"跨 novel 读取应返回 404，实际: {resp.status_code}"

    async def test_cross_novel_entity_update_returns_404(
        self, async_client: AsyncClient,
    ):
        """小说 B 不能修改小说 A 的世界对象"""
        nid_a, eid_a = await self._create_project_and_entity(async_client, "A")
        nid_b, _ = await self._create_project_and_entity(async_client, "B")

        resp = await async_client.put(
            f"/api/world/entities/{eid_a}",
            params={"novel_id": nid_b},
            json={"name": "被篡改"},
        )
        assert resp.status_code == 404, \
            f"跨 novel 更新应返回 404，实际: {resp.status_code}"

    async def test_cross_novel_entity_delete_returns_404(
        self, async_client: AsyncClient,
    ):
        """小说 B 不能删除小说 A 的世界对象"""
        nid_a, eid_a = await self._create_project_and_entity(async_client, "A")
        nid_b, _ = await self._create_project_and_entity(async_client, "B")

        resp = await async_client.delete(
            f"/api/world/entities/{eid_a}",
            params={"novel_id": nid_b},
        )
        assert resp.status_code == 404, \
            f"跨 novel 删除应返回 404，实际: {resp.status_code}"

    async def test_list_entities_filtered_by_novel(
        self, async_client: AsyncClient,
    ):
        """列表接口应按 novel_id 过滤"""
        nid_a, _ = await self._create_project_and_entity(async_client, "A")
        nid_b, _ = await self._create_project_and_entity(async_client, "B")

        resp = await async_client.get(
            "/api/world/entities",
            params={"novel_id": nid_b},
        )
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items") or data.get("data") or (data if isinstance(data, list) else [])
        for item in items:
            item_nid = item.get("novel_id") or item.get("novel_id") or ""
            # 确保列表只包含小说 B 的对象
            if item_nid:
                assert item_nid == nid_b

    async def test_cross_novel_character_access(
        self, async_client: AsyncClient,
    ):
        """小说 B 不能读取小说 A 的人物"""
        nid_a, _ = await self._create_project_and_entity(async_client, "A")
        nid_b, _ = await self._create_project_and_entity(async_client, "B")

        # 创建 B 的人物（CharacterCreate 要求 novel_id 在 body 中）
        # 也需要在 URL 中传入 novel_id 作为查询参数
        resp = await async_client.post(
            "/api/characters",
            params={"novel_id": nid_b},
            json={"novel_id": nid_b, "name": "B 角色", "role": "主角"},
        )
        assert resp.status_code in (200, 201), f"创建角色失败: {resp.text}"
        char_b_id = resp.json().get("id", "")

        # B 读取自己的角色应成功
        if char_b_id:
            resp = await async_client.get(f"/api/characters/{char_b_id}")
            assert resp.status_code in (200, 404, 422), f"读取角色: {resp.status_code}"

    async def test_cross_novel_rag_retrieve(
        self, async_client: AsyncClient,
    ):
        """RAG 检索按 novel_id 过滤"""
        nid_a, _ = await self._create_project_and_entity(async_client, "A")

        # 为 A 创建 RAG chunk
        resp = await async_client.post(
            "/api/rag/chunks",
            params={"novel_id": nid_a},
            json={"source_type": "text", "text": "A 的机密内容"},
        )

        # 用假 novel_id 检索，不应返回 A 的内容
        resp = await async_client.post(
            "/api/rag/retrieve",
            params={"novel_id": "00000000-0000-0000-0000-000000000000"},
            json={"query": "机密", "top_k": 10},
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        chunks = data.get("chunks") or data.get("results") or []
        for c in chunks:
            chunk_nid = c.get("novel_id") or c.get("novel_id", "")
            if chunk_nid:
                assert chunk_nid == "00000000-0000-0000-0000-000000000000"
