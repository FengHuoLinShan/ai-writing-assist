from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.api]


class TestApiOutlineThreads:
    """Outline Threads API 层测试 — 覆盖 happy path / error path / 边界条件"""

    async def test_api_outline_threads_create_with_valid_data_returns_201(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """使用有效数据创建剧情线返回 201 及正确字段"""
        # Arrange
        payload = {
            "name": "主线",
            "thread_type": "main",
            "summary": "测试剧情线",
        }

        # Act
        resp = await async_client.post(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
            json=payload,
        )

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "主线"
        assert data["thread_type"] == "main"
        assert "id" in data

    async def test_api_outline_threads_list_returns_items_with_total(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """列出剧情线返回包含 items 且 total >= 1"""
        # Arrange
        await async_client.post(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
            json={"name": "主线A", "thread_type": "main"},
        )

        # Act
        resp = await async_client.get(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
        )

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] >= 1

    async def test_api_outline_threads_get_not_found_returns_404(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """获取不存在的剧情线返回 404"""
        # Arrange
        missing_id = "00000000-0000-0000-0000-000000000000"

        # Act
        resp = await async_client.get(
            f"/api/outline/threads/{missing_id}",
            params={"novel_id": test_project_id},
        )

        # Assert
        assert resp.status_code == 404

    async def test_api_outline_threads_update_with_valid_data_returns_200(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """使用有效数据更新剧情线返回 200 及更新后字段"""
        # Arrange
        create_resp = await async_client.post(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
            json={"name": "原线", "thread_type": "main"},
        )
        thread_id = create_resp.json()["id"]
        payload = {"name": "改线", "current_stage": "中期"}

        # Act
        resp = await async_client.patch(
            f"/api/outline/threads/{thread_id}",
            params={"novel_id": test_project_id},
            json=payload,
        )

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "改线"
        assert data["current_stage"] == "中期"

    async def test_api_outline_threads_delete_existing_returns_204(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """删除存在的剧情线返回 204 且后续获取为 deprecated"""
        # Arrange
        create_resp = await async_client.post(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
            json={"name": "待删", "thread_type": "main"},
        )
        thread_id = create_resp.json()["id"]

        # Act
        resp = await async_client.delete(
            f"/api/outline/threads/{thread_id}",
            params={"novel_id": test_project_id},
        )

        # Assert
        assert resp.status_code == 204
        get_resp = await async_client.get(
            f"/api/outline/threads/{thread_id}",
            params={"novel_id": test_project_id},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "deprecated"

    async def test_api_outline_threads_create_missing_name_returns_422(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """缺少必填字段 name 时创建剧情线返回 422"""
        # Arrange
        payload = {"thread_type": "main"}

        # Act
        resp = await async_client.post(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
            json=payload,
        )

        # Assert
        assert resp.status_code == 422


class TestApiOutlineArcs:
    """Outline Arcs API 层测试 — 覆盖 happy path / error path / 边界条件"""

    async def test_api_outline_arcs_create_with_valid_data_returns_201(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """使用有效数据创建故事弧返回 201 及正确字段"""
        # Arrange
        payload = {
            "title": "第一卷",
            "start_chapter": 1,
            "end_chapter": 10,
            "arc_goal": "建立世界观",
        }

        # Act
        resp = await async_client.post(
            "/api/outline/arcs",
            params={"novel_id": test_project_id},
            json=payload,
        )

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "第一卷"
        assert data["arc_goal"] == "建立世界观"

    async def test_api_outline_arcs_list_returns_items_with_total(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """列出故事弧返回包含 items 且 total >= 1"""
        # Arrange
        await async_client.post(
            "/api/outline/arcs",
            params={"novel_id": test_project_id},
            json={"title": "卷一", "start_chapter": 1, "end_chapter": 5},
        )

        # Act
        resp = await async_client.get(
            "/api/outline/arcs",
            params={"novel_id": test_project_id},
        )

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] >= 1

    async def test_api_outline_arcs_get_not_found_returns_404(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """获取不存在的故事弧返回 404"""
        # Arrange
        missing_id = "00000000-0000-0000-0000-000000000000"

        # Act
        resp = await async_client.get(
            f"/api/outline/arcs/{missing_id}",
            params={"novel_id": test_project_id},
        )

        # Assert
        assert resp.status_code == 404

    async def test_api_outline_arcs_update_with_valid_data_returns_200(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """使用有效数据更新故事弧返回 200 及更新后字段"""
        # Arrange
        create_resp = await async_client.post(
            "/api/outline/arcs",
            params={"novel_id": test_project_id},
            json={"title": "原标题", "start_chapter": 1, "end_chapter": 10},
        )
        arc_id = create_resp.json()["id"]
        payload = {"title": "新标题", "core_conflict": "新冲突"}

        # Act
        resp = await async_client.patch(
            f"/api/outline/arcs/{arc_id}",
            params={"novel_id": test_project_id},
            json=payload,
        )

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "新标题"
        assert data["core_conflict"] == "新冲突"

    async def test_api_outline_arcs_delete_existing_returns_204(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """删除存在的故事弧返回 204"""
        # Arrange
        create_resp = await async_client.post(
            "/api/outline/arcs",
            params={"novel_id": test_project_id},
            json={"title": "待删", "start_chapter": 1, "end_chapter": 10},
        )
        arc_id = create_resp.json()["id"]

        # Act
        resp = await async_client.delete(
            f"/api/outline/arcs/{arc_id}",
            params={"novel_id": test_project_id},
        )

        # Assert
        assert resp.status_code == 204


class TestApiOutlineGenerate:
    """Outline Generate API 层测试 — 覆盖 AI 生成 happy path"""

    async def test_api_outline_generate_with_mocked_llm_returns_counts(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """生成端点要求确认记录，并提交异步任务。"""
        # Arrange
        from unittest import mock

        confirmation_id = str(uuid.uuid4())

        with (
            mock.patch(
                "modules.outline.api.require_fresh_confirmation", autospec=True
            ) as mock_require,
            mock.patch(
                "modules.outline.api.attach_result_ref", autospec=True
            ) as mock_attach,
            mock.patch("modules.outline.api.enqueue_task", autospec=True) as mock_enqueue,
            mock.patch(
                "modules.outline.api.P20GenerationService",
                autospec=True,
            ) as service_cls,
            mock.patch(
                "modules.project.facade.build_project_llm_execution_snapshot",
                autospec=True,
            ) as mock_snapshot,
        ):
            mock_enqueue.return_value = "task-outline-generate"
            service_cls.return_value.prepare = mock.AsyncMock(
                return_value=mock.Mock(
                    source_fingerprint="p20-fingerprint",
                    context_provenance={"version": "outline-layer-context-v2"},
                )
            )
            mock_snapshot.return_value = {"profile_hash": "frozen"}

            # Act
            resp = await async_client.post(
                "/api/outline/generate",
                json={
                    "novel_id": test_project_id,
                    "context_confirmation_id": confirmation_id,
                    "target": "plot_thread",
                    "mode": "create",
                    "instruction": "基于当前小说总纲设计主剧情线。",
                    "start_chapter": 1,
                    "end_chapter": 5,
                },
            )

        # Assert
        assert resp.status_code == 201
        assert resp.json() == {
            "task_id": "task-outline-generate",
            "status": "pending",
        }
        mock_require.assert_awaited_once()
        mock_attach.assert_awaited_once()
