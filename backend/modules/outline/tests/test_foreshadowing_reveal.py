"""ForeshadowingPlan / RevealPlan API 层测试"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.foreshadowing_repository import ForeshadowingPlanRepository
from modules.outline.reveal_repository import RevealPlanRepository

pytestmark = [pytest.mark.asyncio, pytest.mark.api]


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
