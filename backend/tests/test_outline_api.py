from __future__ import annotations

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
        """删除存在的剧情线返回 204 且后续获取返回 404"""
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
        assert get_resp.status_code == 404

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
        """Mock LLM 后调用生成端点返回正确的 total_threads 和 total_arcs"""
        # Arrange
        from unittest import mock

        from pydantic import BaseModel

        class _GA(BaseModel):
            title: str
            arc_index: int | None = None
            start_chapter: int | None = None
            end_chapter: int | None = None
            arc_goal: str | None = None
            core_conflict: str | None = None
            main_opposition: str | None = None
            entry_hook: str | None = None
            midpoint_turn: str | None = None
            climax: str | None = None
            result: str | None = None
            next_hook: str | None = None

        class _GT(BaseModel):
            name: str
            thread_type: str
            summary: str | None = None
            visible_goal: str | None = None
            hidden_truth: str | None = None
            start_chapter: int | None = None
            planned_payoff_chapter: int | None = None
            current_stage: str | None = None
            related_character_names: list[str] = []
            related_entity_names: list[str] = []

        class _FP(BaseModel):
            name: str = ""
            summary: str | None = None
            planned_seed_chapter: int | None = None
            planned_payoff_chapter: int | None = None
            status: str = "draft"

        class _RP(BaseModel):
            target_name: str = ""
            target_type: str = "world_entity"
            secret_summary: str | None = None
            status: str = "draft"

        class _OP(BaseModel):
            thread_name: str = ""
            offscreen_description: str | None = None
            importance: str = "medium"

        class _RK(BaseModel):
            risk_type: str = "其他"
            description: str | None = None
            severity: str = "medium"

        class _QN(BaseModel):
            question: str = ""
            context: str | None = None
            suggested_options: list[str] = []

        class _GS(BaseModel):
            title: str
            goal: str | None = None
            core_conflict: str | None = None
            emotional_beat: str | None = None
            must_happen: str | None = None
            must_not_happen: str | None = None
            narrative_tag: str | None = None
            chapter_start: int | None = None
            chapter_end: int | None = None
            scene_chunks: list[dict] = []

        class _GO(BaseModel):
            plot_threads: list[_GT] = []
            outline_arcs: list[_GA] = []
            scenes: list[_GS] = []
            foreshadowing_plans: list[_FP] = []
            reveal_plans: list[_RP] = []
            offscreen_progress: list[_OP] = []
            risks: list[_RK] = []
            questions_for_user: list[_QN] = []

        with (
            mock.patch("modules.context.facade.compile_structure_context") as mock_ctx,
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured"
            ) as mock_llm,
        ):
            from modules.context.contracts import StructureContextBundle

            mock_ctx.return_value = StructureContextBundle(
                novel_id=test_project_id,
                task="test",
                scope="full",
            )
            mock_llm.return_value = _GO(
                plot_threads=[_GT(name="test", thread_type="main")],
                outline_arcs=[],
            )

            # Act
            resp = await async_client.post(
                "/api/outline/generate",
                params={
                    "novel_id": test_project_id,
                    "start_chapter": 1,
                    "end_chapter": 5,
                },
            )

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_threads"] == 1
        assert data["total_arcs"] == 0
        assert "extra_sections" in data
