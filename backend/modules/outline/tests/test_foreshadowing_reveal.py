"""ForeshadowingPlan / RevealPlan API 层测试"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import StructureContextBundle
from modules.outline.foreshadowing_repository import ForeshadowingPlanRepository
from modules.outline.reveal_repository import RevealPlanRepository

pytestmark = [pytest.mark.asyncio, pytest.mark.api]


def _make_bundle(novel_id: str) -> StructureContextBundle:
    return StructureContextBundle(
        novel_id=novel_id,
        task="测试生成",
        scope="full",
        project={
            "id": novel_id,
            "title": "测试小说",
            "genre": "仙侠",
            "tone": "正剧",
        },
        world_entities=[
            {"name": "霜华剑", "entity_type": "item", "summary": "上古神剑"},
        ],
        characters=[
            {"name": "白砚", "role": "protagonist", "desire": "寻找真相"},
        ],
    )


def _mock_llm_return_value() -> BaseModel:
    """构造 PlotStructureGenerator 需要的 LLM 输出模型。"""

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
        related_character_names: list[str] = []
        related_entity_names: list[str] = []
        related_thread_names: list[str] = []

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

    return _GO(
        plot_threads=[
            _GT(
                name="主线：寻剑",
                thread_type="main",
                summary="主角寻找霜华剑",
                start_chapter=1,
                planned_payoff_chapter=30,
                current_stage="初期",
            ),
            _GT(
                name="暗线：魔神复苏",
                thread_type="hidden",
                summary="霜华剑封印松动",
                start_chapter=5,
                planned_payoff_chapter=40,
            ),
        ],
        outline_arcs=[
            _GA(
                title="第一卷：启程",
                arc_index=1,
                start_chapter=1,
                end_chapter=10,
                arc_goal="建立世界观",
                core_conflict="主角与家族的冲突",
            ),
            _GA(
                title="第二卷：寻剑",
                arc_index=2,
                start_chapter=6,
                end_chapter=10,
                arc_goal="寻找霜华剑",
            ),
        ],
    )


class TestApiForeshadowingPlans:
    """伏笔计划 API 测试"""

    async def test_api_foreshadowing_create_returns_201(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        resp = await async_client.post(
            "/api/outline/foreshadowing",
            params={"novel_id": test_project_id},
            json={
                "name": "古剑封印",
                "summary": "主角发现古剑秘密",
                "planned_seed_chapter": 1,
                "planned_reinforce_chapters": [3, 5],
                "planned_payoff_chapter": 10,
                "status": "draft",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "古剑封印"
        assert data["novel_id"] == test_project_id

    async def test_api_foreshadowing_list_returns_items(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
    ) -> None:
        repo = ForeshadowingPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {
                "name": "古剑封印",
                "summary": "主角发现古剑秘密",
                "planned_seed_chapter": 1,
                "planned_reinforce_chapters": [3, 5],
                "planned_payoff_chapter": 10,
                "status": "draft",
            },
        )
        await db_session.flush()
        plan_id = str(plan.id)

        list_resp = await async_client.get(
            "/api/outline/foreshadowing",
            params={"novel_id": test_project_id},
        )
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == plan_id

    async def test_api_foreshadowing_update_returns_200(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
    ) -> None:
        repo = ForeshadowingPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {"name": "古剑封印", "status": "draft"},
        )
        await db_session.flush()
        plan_id = str(plan.id)

        patch_resp = await async_client.patch(
            f"/api/outline/foreshadowing/{plan_id}",
            params={"novel_id": test_project_id},
            json={"name": "古剑封印（改）", "planned_payoff_chapter": 12},
        )
        assert patch_resp.status_code == 200
        patched = patch_resp.json()
        assert patched["name"] == "古剑封印（改）"
        assert patched["planned_payoff_chapter"] == 12

    async def test_api_foreshadowing_update_invalid_reinforce_chapter_returns_422(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
    ) -> None:
        repo = ForeshadowingPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {"name": "伏笔", "status": "draft"},
        )
        await db_session.flush()

        resp = await async_client.patch(
            f"/api/outline/foreshadowing/{plan.id}",
            params={"novel_id": test_project_id},
            json={"planned_reinforce_chapters": [0, 3]},
        )
        assert resp.status_code == 422

    async def test_api_foreshadowing_update_cross_novel_returns_404(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        other_novel_id: str,
    ) -> None:
        repo = ForeshadowingPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {"name": "只属于项目1的伏笔", "status": "draft"},
        )
        await db_session.flush()

        resp = await async_client.patch(
            f"/api/outline/foreshadowing/{plan.id}",
            params={"novel_id": other_novel_id},
            json={"name": "篡改"},
        )
        assert resp.status_code == 404

    async def test_api_foreshadowing_delete_returns_204(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
    ) -> None:
        repo = ForeshadowingPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {"name": "待删除伏笔", "status": "draft"},
        )
        await db_session.flush()

        resp = await async_client.delete(
            f"/api/outline/foreshadowing/{plan.id}",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 204

    async def test_api_foreshadowing_delete_cross_novel_returns_404(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        other_novel_id: str,
    ) -> None:
        repo = ForeshadowingPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {"name": "只属于项目1的伏笔", "status": "draft"},
        )
        await db_session.flush()

        resp = await async_client.delete(
            f"/api/outline/foreshadowing/{plan.id}",
            params={"novel_id": other_novel_id},
        )
        assert resp.status_code == 404

    async def test_get_foreshadowing_plan(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
    ) -> None:
        repo = ForeshadowingPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {
                "name": "古剑封印",
                "summary": "主角发现古剑秘密",
                "planned_seed_chapter": 1,
                "planned_payoff_chapter": 10,
                "status": "draft",
            },
        )
        await db_session.flush()
        plan_id = str(plan.id)

        resp = await async_client.get(
            f"/api/outline/foreshadowing/{plan_id}",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == plan_id
        assert data["name"] == "古剑封印"
        assert data["novel_id"] == test_project_id

    async def test_get_foreshadowing_plan_wrong_novel(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        other_novel_id: str,
    ) -> None:
        repo = ForeshadowingPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {"name": "古剑封印", "status": "draft"},
        )
        await db_session.flush()

        resp = await async_client.get(
            f"/api/outline/foreshadowing/{plan.id}",
            params={"novel_id": other_novel_id},
        )
        assert resp.status_code == 404

    async def test_delete_foreshadowing_wrong_novel(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        other_novel_id: str,
    ) -> None:
        repo = ForeshadowingPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {"name": "待删除伏笔", "status": "draft"},
        )
        await db_session.flush()
        plan_id = str(plan.id)

        delete_resp = await async_client.delete(
            f"/api/outline/foreshadowing/{plan_id}",
            params={"novel_id": other_novel_id},
        )
        assert delete_resp.status_code == 404

        get_resp = await async_client.get(
            f"/api/outline/foreshadowing/{plan_id}",
            params={"novel_id": test_project_id},
        )
        assert get_resp.status_code == 200

        ok_delete = await async_client.delete(
            f"/api/outline/foreshadowing/{plan_id}",
            params={"novel_id": test_project_id},
        )
        assert ok_delete.status_code == 204

        after_get = await async_client.get(
            f"/api/outline/foreshadowing/{plan_id}",
            params={"novel_id": test_project_id},
        )
        assert after_get.status_code == 404


class TestApiRevealPlans:
    """揭示计划 API 测试"""

    async def test_api_reveal_create_returns_201(
        self,
        async_client: AsyncClient,
        test_project_id: str,
        test_entity_id: str,
    ) -> None:
        resp = await async_client.post(
            "/api/outline/reveals",
            params={"novel_id": test_project_id},
            json={
                "target_type": "world_entity",
                "target_id": test_entity_id,
                "secret_summary": "古剑封印着魔神",
                "reveal_stages": [
                    {"stage_index": 0, "chapter_index": 1, "reveal_content": "得到古剑"},
                ],
                "status": "draft",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["target_type"] == "world_entity"
        assert data["target_id"] == test_entity_id

    async def test_api_reveal_list_returns_items(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        test_entity_id: str,
    ) -> None:
        repo = RevealPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {
                "target_type": "world_entity",
                "target_id": uuid.UUID(hex=test_entity_id),
                "secret_summary": "古剑封印着魔神",
                "reveal_stages": [
                    {"stage_index": 0, "chapter_index": 1, "reveal_content": "得到古剑"},
                    {"stage_index": 1, "chapter_index": 5, "reveal_content": "古剑异动"},
                ],
                "status": "draft",
            },
        )
        await db_session.flush()
        plan_id = str(plan.id)

        list_resp = await async_client.get(
            "/api/outline/reveals",
            params={"novel_id": test_project_id},
        )
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == plan_id

    async def test_api_reveal_update_returns_200(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        test_entity_id: str,
    ) -> None:
        repo = RevealPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {
                "target_type": "world_entity",
                "target_id": uuid.UUID(hex=test_entity_id),
                "secret_summary": "古剑封印着魔神",
                "status": "draft",
            },
        )
        await db_session.flush()
        plan_id = str(plan.id)

        patch_resp = await async_client.patch(
            f"/api/outline/reveals/{plan_id}",
            params={"novel_id": test_project_id},
            json={
                "secret_summary": "古剑封印着上古魔神",
                "reveal_stages": [
                    {"stage_index": 0, "chapter_index": 2, "reveal_content": "得到古剑"},
                ],
            },
        )
        assert patch_resp.status_code == 200
        patched = patch_resp.json()
        assert patched["secret_summary"] == "古剑封印着上古魔神"
        assert patched["reveal_stages"][0]["chapter_index"] == 2

    async def test_api_reveal_update_invalid_stage_chapter_returns_422(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        test_entity_id: str,
    ) -> None:
        repo = RevealPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {
                "target_type": "world_entity",
                "target_id": uuid.UUID(hex=test_entity_id),
                "secret_summary": "秘密",
                "status": "draft",
            },
        )
        await db_session.flush()

        resp = await async_client.patch(
            f"/api/outline/reveals/{plan.id}",
            params={"novel_id": test_project_id},
            json={
                "reveal_stages": [
                    {"stage_index": 0, "chapter_index": 0, "reveal_content": "错误"},
                ],
            },
        )
        assert resp.status_code == 422

    async def test_api_reveal_update_cross_novel_returns_404(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        other_novel_id: str,
        test_entity_id: str,
    ) -> None:
        repo = RevealPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {
                "target_type": "world_entity",
                "target_id": uuid.UUID(hex=test_entity_id),
                "secret_summary": "只属于项目1的秘密",
                "status": "draft",
            },
        )
        await db_session.flush()

        resp = await async_client.patch(
            f"/api/outline/reveals/{plan.id}",
            params={"novel_id": other_novel_id},
            json={"secret_summary": "篡改"},
        )
        assert resp.status_code == 404

    async def test_api_reveal_delete_returns_204(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        test_entity_id: str,
    ) -> None:
        repo = RevealPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {
                "target_type": "world_entity",
                "target_id": uuid.UUID(hex=test_entity_id),
                "secret_summary": "待删除秘密",
                "status": "draft",
            },
        )
        await db_session.flush()

        resp = await async_client.delete(
            f"/api/outline/reveals/{plan.id}",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 204

    async def test_api_reveal_delete_cross_novel_returns_404(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        other_novel_id: str,
        test_entity_id: str,
    ) -> None:
        repo = RevealPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {
                "target_type": "world_entity",
                "target_id": uuid.UUID(hex=test_entity_id),
                "secret_summary": "只属于项目1的秘密",
                "status": "draft",
            },
        )
        await db_session.flush()

        resp = await async_client.delete(
            f"/api/outline/reveals/{plan.id}",
            params={"novel_id": other_novel_id},
        )
        assert resp.status_code == 404


class TestPlotStructureGenerateDuplicateRange:
    """AI 生成重复区间告警测试"""

    async def test_first_generate_reports_zero_existing_counts(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        bundle = _make_bundle(test_project_id)

        with (
            mock.patch(
                "modules.context.facade.compile_structure_context", return_value=bundle
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured"
            ) as mock_llm,
        ):
            mock_llm.return_value = _mock_llm_return_value()
            resp = await async_client.post(
                "/api/outline/generate",
                params={
                    "novel_id": test_project_id,
                    "start_chapter": 1,
                    "end_chapter": 10,
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["total_threads"] == 2
        assert data["total_arcs"] == 2
        assert data["existing_threads_count"] == 0
        assert data["existing_arcs_count"] == 0

    async def test_second_generate_reports_existing_counts_and_warning(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        bundle = _make_bundle(test_project_id)

        with (
            mock.patch(
                "modules.context.facade.compile_structure_context", return_value=bundle
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured"
            ) as mock_llm,
        ):
            mock_llm.return_value = _mock_llm_return_value()
            first = await async_client.post(
                "/api/outline/generate",
                params={
                    "novel_id": test_project_id,
                    "start_chapter": 1,
                    "end_chapter": 10,
                },
            )
            assert first.status_code == 201
            first_data = first.json()
            first_threads = first_data["total_threads"]
            first_arcs = first_data["total_arcs"]

            second = await async_client.post(
                "/api/outline/generate",
                params={
                    "novel_id": test_project_id,
                    "start_chapter": 1,
                    "end_chapter": 10,
                },
            )

        assert second.status_code == 201
        second_data = second.json()
        assert second_data["existing_threads_count"] == first_threads
        assert second_data["existing_arcs_count"] == first_arcs
        assert any("已有" in w for w in second_data.get("warnings", []))

    async def test_get_reveal_plan(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        test_entity_id: str,
    ) -> None:
        repo = RevealPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {
                "target_type": "world_entity",
                "target_id": uuid.UUID(hex=test_entity_id),
                "secret_summary": "古剑封印着魔神",
                "status": "draft",
            },
        )
        await db_session.flush()
        plan_id = str(plan.id)

        resp = await async_client.get(
            f"/api/outline/reveals/{plan_id}",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == plan_id
        assert data["target_type"] == "world_entity"
        assert data["target_id"] == test_entity_id
        assert data["novel_id"] == test_project_id

    async def test_get_reveal_plan_wrong_novel(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        other_novel_id: str,
        test_entity_id: str,
    ) -> None:
        repo = RevealPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {
                "target_type": "world_entity",
                "target_id": uuid.UUID(hex=test_entity_id),
                "secret_summary": "古剑封印着魔神",
                "status": "draft",
            },
        )
        await db_session.flush()

        resp = await async_client.get(
            f"/api/outline/reveals/{plan.id}",
            params={"novel_id": other_novel_id},
        )
        assert resp.status_code == 404

    async def test_delete_reveal_wrong_novel(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        other_novel_id: str,
        test_entity_id: str,
    ) -> None:
        repo = RevealPlanRepository()
        plan = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            {
                "target_type": "world_entity",
                "target_id": uuid.UUID(hex=test_entity_id),
                "secret_summary": "待删除秘密",
                "status": "draft",
            },
        )
        await db_session.flush()
        plan_id = str(plan.id)

        delete_resp = await async_client.delete(
            f"/api/outline/reveals/{plan_id}",
            params={"novel_id": other_novel_id},
        )
        assert delete_resp.status_code == 404

        get_resp = await async_client.get(
            f"/api/outline/reveals/{plan_id}",
            params={"novel_id": test_project_id},
        )
        assert get_resp.status_code == 200

        ok_delete = await async_client.delete(
            f"/api/outline/reveals/{plan_id}",
            params={"novel_id": test_project_id},
        )
        assert ok_delete.status_code == 204

        after_get = await async_client.get(
            f"/api/outline/reveals/{plan_id}",
            params={"novel_id": test_project_id},
        )
        assert after_get.status_code == 404
