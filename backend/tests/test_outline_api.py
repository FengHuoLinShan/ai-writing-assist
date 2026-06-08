from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.api]


class TestOutlineThreadsAPI:
    """T3: API 层 — PlotThread"""

    async def test_create_thread(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        resp = await async_client.post(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
            json={"name": "主线", "thread_type": "main", "summary": "测试剧情线"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "主线"
        assert data["thread_type"] == "main"
        assert "id" in data

    async def test_list_threads(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        await async_client.post(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
            json={"name": "主线A", "thread_type": "main"},
        )
        resp = await async_client.get(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] >= 1

    async def test_get_thread_not_found(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        resp = await async_client.get(
            "/api/outline/threads/00000000-0000-0000-0000-000000000000",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 404

    async def test_update_thread(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        create_resp = await async_client.post(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
            json={"name": "原线", "thread_type": "main"},
        )
        thread_id = create_resp.json()["id"]

        resp = await async_client.patch(
            f"/api/outline/threads/{thread_id}",
            params={"novel_id": test_project_id},
            json={"name": "改线", "current_stage": "中期"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "改线"
        assert data["current_stage"] == "中期"

    async def test_delete_thread(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        create_resp = await async_client.post(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
            json={"name": "待删", "thread_type": "main"},
        )
        thread_id = create_resp.json()["id"]

        resp = await async_client.delete(
            f"/api/outline/threads/{thread_id}",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 204

        get_resp = await async_client.get(
            f"/api/outline/threads/{thread_id}",
            params={"novel_id": test_project_id},
        )
        assert get_resp.status_code == 404

    async def test_create_thread_missing_name(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        resp = await async_client.post(
            "/api/outline/threads",
            params={"novel_id": test_project_id},
            json={"thread_type": "main"},
        )
        assert resp.status_code == 422


class TestOutlineArcsAPI:
    """T3: API 层 — OutlineArc"""

    async def test_create_arc(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        resp = await async_client.post(
            "/api/outline/arcs",
            params={"novel_id": test_project_id},
            json={"title": "第一卷", "start_chapter": 1, "end_chapter": 10, "arc_goal": "建立世界观"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "第一卷"
        assert data["arc_goal"] == "建立世界观"

    async def test_list_arcs(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        await async_client.post(
            "/api/outline/arcs",
            params={"novel_id": test_project_id},
            json={"title": "卷一", "start_chapter": 1, "end_chapter": 5},
        )
        resp = await async_client.get(
            "/api/outline/arcs",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] >= 1

    async def test_get_arc_not_found(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        resp = await async_client.get(
            "/api/outline/arcs/00000000-0000-0000-0000-000000000000",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 404

    async def test_update_arc(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        create_resp = await async_client.post(
            "/api/outline/arcs",
            params={"novel_id": test_project_id},
            json={"title": "原标题", "start_chapter": 1, "end_chapter": 10},
        )
        arc_id = create_resp.json()["id"]

        resp = await async_client.patch(
            f"/api/outline/arcs/{arc_id}",
            params={"novel_id": test_project_id},
            json={"title": "新标题", "core_conflict": "新冲突"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "新标题"
        assert data["core_conflict"] == "新冲突"

    async def test_delete_arc(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        create_resp = await async_client.post(
            "/api/outline/arcs",
            params={"novel_id": test_project_id},
            json={"title": "待删", "start_chapter": 1, "end_chapter": 10},
        )
        arc_id = create_resp.json()["id"]

        resp = await async_client.delete(
            f"/api/outline/arcs/{arc_id}",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 204


class TestOutlineGenerateAPI:
    """T3: API 层 — AI 生成"""

    async def test_generate_returns_result(
        self, async_client: AsyncClient, test_project_id: str,
    ) -> None:
        """生成端点应返回 {total_threads, total_arcs}"""
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

        class _GO(BaseModel):
            plot_threads: list[_GT] = []
            outline_arcs: list[_GA] = []
            foreshadowing_plans: list[_FP] = []
            reveal_plans: list[_RP] = []
            offscreen_progress: list[_OP] = []
            risks: list[_RK] = []
            questions_for_user: list[_QN] = []

        with (
            mock.patch("modules.context.facade.compile_structure_context") as mock_ctx,
            mock.patch("infrastructure.llm.client.LLMClient.generate_structured") as mock_llm,
        ):
            from modules.context.contracts import StructureContextBundle
            mock_ctx.return_value = StructureContextBundle(
                novel_id=test_project_id, task="test", scope="full",
            )
            mock_llm.return_value = _GO(
                plot_threads=[_GT(name="test", thread_type="main")],
                outline_arcs=[],
            )

            resp = await async_client.post(
                "/api/outline/generate",
                params={
                    "novel_id": test_project_id,
                    "start_chapter": 1,
                    "end_chapter": 5,
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["total_threads"] == 1
        assert data["total_arcs"] == 0
        assert "extra_sections" in data
