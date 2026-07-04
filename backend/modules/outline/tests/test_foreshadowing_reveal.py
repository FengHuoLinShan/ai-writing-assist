"""ForeshadowingPlan / RevealPlan API 层测试"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import mock

import pytest
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.foreshadowing_repository import ForeshadowingPlanRepository
from modules.outline.reveal_repository import RevealPlanRepository
from tests.utils import _make_bundle

pytestmark = [pytest.mark.asyncio, pytest.mark.api]


class _FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.flush_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1


async def test_foreshadowing_update_reuses_loaded_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = ForeshadowingPlanRepository()
    plan_id = uuid.uuid4()
    plan = type("Plan", (), {"id": plan_id, "name": "旧伏笔"})()
    get_calls = 0

    async def fake_get(_db, requested_id):
        nonlocal get_calls
        get_calls += 1
        assert requested_id == plan_id
        return plan

    monkeypatch.setattr(repo, "get", fake_get)
    db = _FakeSession()

    result = await repo.update(db, plan_id, {"name": "新伏笔"})  # type: ignore[arg-type]

    assert result is plan
    assert plan.name == "新伏笔"
    assert get_calls == 1
    assert db.added == [plan]
    assert db.flush_count == 1


async def test_reveal_update_reuses_loaded_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = RevealPlanRepository()
    plan_id = uuid.uuid4()
    plan = type("Plan", (), {"id": plan_id, "secret_summary": "旧秘密"})()
    get_calls = 0

    async def fake_get(_db, requested_id):
        nonlocal get_calls
        get_calls += 1
        assert requested_id == plan_id
        return plan

    monkeypatch.setattr(repo, "get", fake_get)
    db = _FakeSession()

    result = await repo.update(
        db,  # type: ignore[arg-type]
        plan_id,
        {"secret_summary": "新秘密"},
    )

    assert result is plan
    assert plan.secret_summary == "新秘密"
    assert get_calls == 1
    assert db.added == [plan]
    assert db.flush_count == 1


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

    @pytest.mark.parametrize(
        "endpoint,payload,method",
        [
            ("foreshadowing", {"name": "篡改"}, "patch"),
            ("foreshadowing", None, "delete"),
            ("reveals", {"secret_summary": "篡改"}, "patch"),
            ("reveals", None, "delete"),
        ],
        ids=[
            "foreshadowing_update",
            "foreshadowing_delete",
            "reveal_update",
            "reveal_delete",
        ],
    )
    async def test_api_cross_novel_returns_404(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        test_project_id: str,
        other_novel_id: str,
        test_entity_id: str,
        endpoint: str,
        payload: dict | None,
        method: str,
    ) -> None:
        if endpoint == "foreshadowing":
            repo = ForeshadowingPlanRepository()
            plan = await repo.create(
                db_session,
                uuid.UUID(hex=test_project_id),
                {"name": "只属于项目1的伏笔", "status": "draft"},
            )
        else:
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

        url = f"/api/outline/{endpoint}/{plan.id}"
        if method == "patch":
            resp = await async_client.patch(
                url,
                params={"novel_id": other_novel_id},
                json=payload,
            )
        else:
            resp = await async_client.delete(
                url,
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
        assert after_get.status_code == 200
        assert after_get.json()["status"] == "deprecated"


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


class TestPlotStructureGenerateDuplicateRange:
    """AI 生成重复区间告警测试"""

    async def test_first_generate_reports_zero_existing_counts(
        self,
        db_session: AsyncSession,
        test_project_id: str,
    ) -> None:
        bundle = _make_bundle(test_project_id)
        from modules.outline.generator import PlotStructureGenerator

        with (
            mock.patch(
                "modules.context.facade.compile_structure_context", return_value=bundle
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured"
            ) as mock_llm,
        ):
            mock_llm.return_value = _mock_llm_return_value()
            data = await PlotStructureGenerator().generate(
                db_session,
                novel_id=test_project_id,
                start_chapter=1,
                end_chapter=10,
            )

        assert data["total_threads"] == 2
        assert data["total_arcs"] == 2
        assert data["existing_threads_count"] == 0
        assert data["existing_arcs_count"] == 0

    async def test_deep_import_generate_creates_context_snapshot(
        self,
        db_session: AsyncSession,
        test_project_id: str,
    ) -> None:
        """深度导入结构分析应为真实 LLM 调用创建 context snapshot。"""
        bundle = _make_bundle(test_project_id)
        bundle.warnings = ["RAG 检索降级"]
        from sqlalchemy import select

        from modules.context.models import ContextSnapshot
        from modules.outline.generator import PlotStructureGenerator
        from shared.utils import parse_uuid

        with (
            mock.patch(
                "modules.context.facade.compile_structure_context", return_value=bundle
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured"
            ) as mock_llm,
        ):
            mock_llm.return_value = _mock_llm_return_value()
            data = await PlotStructureGenerator().generate(
                db_session,
                novel_id=test_project_id,
                start_chapter=1,
                end_chapter=10,
                context_mode="working",
                include_pending_objects=True,
                workflow_id="wf-structure",
                audit_context_snapshot=True,
            )

        stmt = select(ContextSnapshot).where(
            ContextSnapshot.novel_id == parse_uuid(test_project_id, "novel_id"),
            ContextSnapshot.workflow_id == "wf-structure",
        )
        snapshot = (await db_session.execute(stmt)).scalar_one()
        assert snapshot.phase == "structure_analysis"
        assert snapshot.operation == "plot_structure_generation"
        assert snapshot.context_mode == "working"
        assert snapshot.include_pending_objects is True
        assert snapshot.status == "succeeded"
        assert snapshot.context_summary["chapter_range"] == {"start": 1, "end": 10}
        assert snapshot.context_summary["warnings_count"] == 1
        assert snapshot.section_metadata["warnings"] == ["RAG 检索降级"]
        assert snapshot.result_refs
        assert any(ref["type"] == "plot_thread" for ref in snapshot.result_refs)
        assert data["audit_summary"]["structure_analysis"]["snapshot_count"] == 1

    async def test_deep_import_generate_marks_snapshot_failed_on_persist_error(
        self,
        db_session: AsyncSession,
        test_project_id: str,
    ) -> None:
        """结构分析解析成功但持久化失败时，snapshot 应标记 failed。"""
        bundle = _make_bundle(test_project_id)
        from sqlalchemy import select

        from modules.context.models import ContextSnapshot
        from modules.outline.generator import PlotStructureGenerator
        from shared.utils import parse_uuid

        with (
            mock.patch(
                "modules.context.facade.compile_structure_context", return_value=bundle
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured"
            ) as mock_llm,
            mock.patch(
                "modules.outline.generation.persister.PlotStructurePersister.persist",
                side_effect=RuntimeError("persist failed"),
            ),
        ):
            mock_llm.return_value = _mock_llm_return_value()
            with pytest.raises(RuntimeError, match="persist failed"):
                await PlotStructureGenerator().generate(
                    db_session,
                    novel_id=test_project_id,
                    start_chapter=1,
                    end_chapter=10,
                    context_mode="working",
                    include_pending_objects=True,
                    workflow_id="wf-structure-persist-failed",
                    audit_context_snapshot=True,
                )

        await db_session.rollback()

        stmt = select(ContextSnapshot).where(
            ContextSnapshot.novel_id == parse_uuid(test_project_id, "novel_id"),
            ContextSnapshot.workflow_id == "wf-structure-persist-failed",
        )
        snapshot = (await db_session.execute(stmt)).scalar_one()
        assert snapshot.phase == "structure_analysis"
        assert snapshot.status == "failed"
        assert snapshot.error_kind == "RuntimeError"
        assert "persist failed" in snapshot.error_message

    async def test_second_generate_reports_existing_counts_and_warning(
        self,
        db_session: AsyncSession,
        test_project_id: str,
    ) -> None:
        bundle = _make_bundle(test_project_id)
        from modules.outline.generator import PlotStructureGenerator

        with (
            mock.patch(
                "modules.context.facade.compile_structure_context", return_value=bundle
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured"
            ) as mock_llm,
        ):
            mock_llm.return_value = _mock_llm_return_value()
            generator = PlotStructureGenerator()
            first_data = await generator.generate(
                db_session,
                novel_id=test_project_id,
                start_chapter=1,
                end_chapter=10,
            )
            first_threads = first_data["total_threads"]
            first_arcs = first_data["total_arcs"]

            second_data = await generator.generate(
                db_session,
                novel_id=test_project_id,
                start_chapter=1,
                end_chapter=10,
            )

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
        assert after_get.status_code == 200
        assert after_get.json()["status"] == "deprecated"


async def test_plot_structure_persister_batches_foreshadowing_and_reveals() -> None:
    from modules.outline.generation.models import (
        ForeshadowingPlan as GeneratedForeshadowingPlan,
    )
    from modules.outline.generation.models import RevealPlan as GeneratedRevealPlan
    from modules.outline.generation.persister import PlotStructurePersister

    novel_id = uuid.uuid4()
    target_id = uuid.uuid4()
    foreshadowing_plans = [
        SimpleNamespace(id=uuid.uuid4(), name="古剑封印"),
        SimpleNamespace(id=uuid.uuid4(), name="暗线伏笔"),
    ]
    reveal_plans = [SimpleNamespace(id=uuid.uuid4())]
    foreshadowing_service = SimpleNamespace(
        create=mock.AsyncMock(side_effect=AssertionError("should use create_batch")),
        create_batch=mock.AsyncMock(return_value=foreshadowing_plans),
    )
    reveal_service = SimpleNamespace(
        create=mock.AsyncMock(side_effect=AssertionError("should use create_batch")),
        create_batch=mock.AsyncMock(return_value=reveal_plans),
    )
    persister = PlotStructurePersister(
        thread_service=SimpleNamespace(),
        arc_service=SimpleNamespace(),
        scene_service=SimpleNamespace(),
        foreshadowing_service=foreshadowing_service,
        reveal_service=reveal_service,
    )

    created_foreshadowing, created_reveals = (
        await persister._persist_foreshadowing_and_reveals(
            mock.AsyncMock(spec=AsyncSession),
            novel_id,
            [
                GeneratedForeshadowingPlan(name="古剑封印", summary="秘密线索"),
                GeneratedForeshadowingPlan(name="暗线伏笔", summary="第二线索"),
            ],
            [
                GeneratedRevealPlan(
                    target_name="霜华剑",
                    target_type="world_entity",
                    secret_summary="封印着魔神",
                )
            ],
            entity_name_to_id={"霜华剑": str(target_id)},
            character_name_to_id={},
            provenance_meta={"workflow_id": "wf-1"},
        )
    )

    assert [item["name"] for item in created_foreshadowing] == ["古剑封印", "暗线伏笔"]
    assert created_reveals == [
        {
            "id": str(reveal_plans[0].id),
            "target_name": "霜华剑",
        }
    ]
    foreshadowing_service.create.assert_not_awaited()
    reveal_service.create.assert_not_awaited()
    foreshadowing_service.create_batch.assert_awaited_once()
    reveal_service.create_batch.assert_awaited_once()
    assert len(foreshadowing_service.create_batch.await_args.args[2]) == 2
    reveal_payload = reveal_service.create_batch.await_args.args[2][0]
    assert reveal_payload.target_id == target_id


async def test_plot_structure_persister_batches_threads_and_arcs() -> None:
    from modules.outline.generation.models import GeneratedArc, GeneratedThread
    from modules.outline.generation.persister import PlotStructurePersister

    novel_id = uuid.uuid4()
    character_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    thread_service = SimpleNamespace(
        create=mock.AsyncMock(side_effect=AssertionError("should use create_batch")),
        create_batch=mock.AsyncMock(
            return_value=[
                SimpleNamespace(id=thread_id, name="主线", thread_type="main"),
                SimpleNamespace(id=uuid.uuid4(), name="暗线", thread_type="hidden"),
            ],
        ),
    )
    arc_service = SimpleNamespace(
        create=mock.AsyncMock(side_effect=AssertionError("should use create_batch")),
        create_batch=mock.AsyncMock(
            return_value=[
                SimpleNamespace(id=uuid.uuid4(), title="卷一", arc_index=1),
                SimpleNamespace(id=uuid.uuid4(), title="卷二", arc_index=2),
            ],
        ),
    )
    persister = PlotStructurePersister(
        thread_service=thread_service,
        arc_service=arc_service,
        scene_service=SimpleNamespace(),
        foreshadowing_service=SimpleNamespace(),
        reveal_service=SimpleNamespace(),
    )

    created_threads = await persister._persist_threads(
        mock.AsyncMock(spec=AsyncSession),
        novel_id,
        1,
        [
            GeneratedThread(
                name="主线",
                thread_type="main",
                related_character_names=["主角"],
                related_entity_names=["秘宝"],
            ),
            GeneratedThread(name="", thread_type="secondary"),
            GeneratedThread(name="暗线", thread_type="hidden"),
        ],
        character_name_to_id={"主角": str(character_id)},
        entity_name_to_id={"秘宝": str(entity_id)},
        provenance_meta={"workflow_id": "wf-1"},
    )

    created_arcs = await persister._persist_arcs(
        mock.AsyncMock(spec=AsyncSession),
        novel_id,
        1,
        10,
        [
            GeneratedArc(
                title="卷一",
                arc_index=1,
                related_thread_names=["主线"],
                related_character_names=["主角"],
                related_entity_names=["秘宝"],
            ),
            GeneratedArc(title="", arc_index=2),
            GeneratedArc(title="卷二", arc_index=2),
        ],
        thread_name_to_id={"主线": str(thread_id)},
        character_name_to_id={"主角": str(character_id)},
        entity_name_to_id={"秘宝": str(entity_id)},
        provenance_meta={"workflow_id": "wf-1"},
    )

    assert [item["name"] for item in created_threads] == ["主线", "暗线"]
    assert [item["title"] for item in created_arcs] == ["卷一", "卷二"]
    thread_service.create.assert_not_awaited()
    arc_service.create.assert_not_awaited()
    thread_service.create_batch.assert_awaited_once()
    arc_service.create_batch.assert_awaited_once()
    thread_payload = thread_service.create_batch.await_args.args[2][0]
    assert thread_payload.related_character_ids == [str(character_id)]
    assert thread_payload.related_entity_ids == [str(entity_id)]
    arc_payload = arc_service.create_batch.await_args.args[2][0]
    assert arc_payload.related_thread_ids == [str(thread_id)]
    assert arc_payload.related_character_ids == [str(character_id)]
    assert arc_payload.related_entity_ids == [str(entity_id)]


async def test_plot_structure_persister_falls_back_for_thread_arc_batches() -> None:
    from modules.outline.generation.models import GeneratedArc, GeneratedThread
    from modules.outline.generation.persister import PlotStructurePersister

    novel_id = uuid.uuid4()
    created_thread = SimpleNamespace(id=uuid.uuid4(), name="主线", thread_type="main")
    created_arc = SimpleNamespace(id=uuid.uuid4(), title="卷一", arc_index=1)
    thread_service = SimpleNamespace(
        create_batch=mock.AsyncMock(side_effect=RuntimeError("thread batch failed")),
        create=mock.AsyncMock(
            side_effect=[
                created_thread,
                RuntimeError("single thread failed"),
            ],
        ),
    )
    arc_service = SimpleNamespace(
        create_batch=mock.AsyncMock(side_effect=RuntimeError("arc batch failed")),
        create=mock.AsyncMock(
            side_effect=[
                created_arc,
                RuntimeError("single arc failed"),
            ],
        ),
    )
    persister = PlotStructurePersister(
        thread_service=thread_service,
        arc_service=arc_service,
        scene_service=SimpleNamespace(),
        foreshadowing_service=SimpleNamespace(),
        reveal_service=SimpleNamespace(),
    )

    created_threads = await persister._persist_threads(
        mock.AsyncMock(spec=AsyncSession),
        novel_id,
        1,
        [
            GeneratedThread(name="主线", thread_type="main"),
            GeneratedThread(name="失败线", thread_type="secondary"),
        ],
        character_name_to_id={},
        entity_name_to_id={},
        provenance_meta={},
    )
    created_arcs = await persister._persist_arcs(
        mock.AsyncMock(spec=AsyncSession),
        novel_id,
        1,
        10,
        [
            GeneratedArc(title="卷一", arc_index=1),
            GeneratedArc(title="失败卷", arc_index=2),
        ],
        thread_name_to_id={},
        character_name_to_id={},
        entity_name_to_id={},
        provenance_meta={},
    )

    assert created_threads == [
        {"id": str(created_thread.id), "name": "主线", "thread_type": "main"}
    ]
    assert created_arcs == [
        {"id": str(created_arc.id), "title": "卷一", "arc_index": 1}
    ]
    thread_service.create_batch.assert_awaited_once()
    arc_service.create_batch.assert_awaited_once()
    assert thread_service.create.await_count == 2
    assert arc_service.create.await_count == 2


async def test_plot_structure_persister_batches_scenes() -> None:
    from modules.outline.generation.models import GeneratedScene
    from modules.outline.generation.persister import PlotStructurePersister

    novel_id = uuid.uuid4()
    scene_service = SimpleNamespace(
        get_ordered=mock.AsyncMock(
            side_effect=AssertionError("should not load every scene for next index"),
        ),
        get_next_scene_index=mock.AsyncMock(return_value=5),
        create=mock.AsyncMock(side_effect=AssertionError("should use batch create")),
        batch_create_models_from_dicts=mock.AsyncMock(
            return_value=[
                SimpleNamespace(id=uuid.uuid4(), title="伏击", scene_index=5),
                SimpleNamespace(id=uuid.uuid4(), title="追索", scene_index=6),
            ],
        ),
    )
    persister = PlotStructurePersister(
        thread_service=SimpleNamespace(),
        arc_service=SimpleNamespace(),
        scene_service=scene_service,
        foreshadowing_service=SimpleNamespace(),
        reveal_service=SimpleNamespace(),
    )

    created = await persister._persist_scenes(
        mock.AsyncMock(spec=AsyncSession),
        novel_id,
        1,
        3,
        [
            GeneratedScene(title="伏击", chapter_start=1, chapter_end=1),
            GeneratedScene(title="", chapter_start=2, chapter_end=2),
            GeneratedScene(
                title="追索",
                chapter_start=2,
                chapter_end=3,
                scene_chunks=[{"chapter_index": 2, "start_pos": 0, "end_pos": 10}],
            ),
        ],
    )

    assert [item["title"] for item in created] == ["伏击", "追索"]
    scene_service.get_ordered.assert_not_awaited()
    scene_service.get_next_scene_index.assert_awaited_once()
    scene_service.create.assert_not_awaited()
    scene_service.batch_create_models_from_dicts.assert_awaited_once()
    payloads = scene_service.batch_create_models_from_dicts.await_args.args[2]
    assert [payload["scene_index"] for payload in payloads] == [5, 6]
    assert payloads[0]["chapter_ids"] == ["1"]
    assert payloads[0]["scene_chunks"] == [
        {"chapter_index": 1, "start_pos": 0, "end_pos": 0}
    ]
    assert payloads[1]["chapter_ids"] == ["2", "3"]


async def test_plot_structure_persister_falls_back_when_scene_batch_fails() -> None:
    from modules.outline.generation.models import GeneratedScene
    from modules.outline.generation.persister import PlotStructurePersister

    novel_id = uuid.uuid4()
    created_scene = SimpleNamespace(id=uuid.uuid4(), title="伏击", scene_index=0)
    scene_service = SimpleNamespace(
        get_ordered=mock.AsyncMock(
            side_effect=AssertionError("should not load every scene for next index"),
        ),
        get_next_scene_index=mock.AsyncMock(return_value=0),
        batch_create_models_from_dicts=mock.AsyncMock(
            side_effect=RuntimeError("batch failed"),
        ),
        create=mock.AsyncMock(
            side_effect=[
                created_scene,
                RuntimeError("single scene failed"),
            ],
        ),
    )
    persister = PlotStructurePersister(
        thread_service=SimpleNamespace(),
        arc_service=SimpleNamespace(),
        scene_service=scene_service,
        foreshadowing_service=SimpleNamespace(),
        reveal_service=SimpleNamespace(),
    )

    created = await persister._persist_scenes(
        mock.AsyncMock(spec=AsyncSession),
        novel_id,
        1,
        2,
        [
            GeneratedScene(title="伏击", chapter_start=1, chapter_end=1),
            GeneratedScene(title="失败 Scene", chapter_start=2, chapter_end=2),
        ],
    )

    assert created == [
        {
            "id": str(created_scene.id),
            "title": "伏击",
            "scene_index": 0,
        }
    ]
    scene_service.get_ordered.assert_not_awaited()
    scene_service.get_next_scene_index.assert_awaited_once()
    scene_service.batch_create_models_from_dicts.assert_awaited_once()
    assert scene_service.create.await_count == 2


async def test_foreshadowing_service_create_batch_delegates_to_repository_batch() -> None:
    from modules.outline.schemas import ForeshadowingPlanCreate
    from modules.outline.services import ForeshadowingPlanService

    novel_id = uuid.uuid4()
    persisted = [
        SimpleNamespace(
            id=uuid.uuid4(),
            novel_id=novel_id,
            name="古剑封印",
            summary=None,
            surface_meaning=None,
            hidden_meaning=None,
            planned_seed_chapter=1,
            planned_reinforce_chapters=[],
            planned_payoff_chapter=3,
            planned_payoff_scene=None,
            related_entity_ids=[],
            related_thread_ids=[],
            provenance_meta={},
            status="draft",
            created_at=None,
            updated_at=None,
        )
    ]
    svc = ForeshadowingPlanService()
    svc.repo = SimpleNamespace(
        create=mock.AsyncMock(side_effect=AssertionError("should use create_batch")),
        create_batch=mock.AsyncMock(return_value=persisted),
    )

    result = await svc.create_batch(
        mock.AsyncMock(spec=AsyncSession),
        str(novel_id),
        [
            ForeshadowingPlanCreate(
                name="古剑封印",
                planned_seed_chapter=1,
                planned_payoff_chapter=3,
            )
        ],
    )

    assert result[0].name == "古剑封印"
    svc.repo.create.assert_not_awaited()
    svc.repo.create_batch.assert_awaited_once()


async def test_reveal_service_create_batch_delegates_to_repository_batch() -> None:
    from modules.outline.schemas import RevealPlanCreate
    from modules.outline.services import RevealPlanService

    novel_id = uuid.uuid4()
    target_id = uuid.uuid4()
    persisted = [
        SimpleNamespace(
            id=uuid.uuid4(),
            novel_id=novel_id,
            target_type="world_entity",
            target_id=target_id,
            secret_summary="秘密",
            reveal_stages=[],
            provenance_meta={},
            status="draft",
            created_at=None,
            updated_at=None,
        )
    ]
    svc = RevealPlanService()
    svc.repo = SimpleNamespace(
        create=mock.AsyncMock(side_effect=AssertionError("should use create_batch")),
        create_batch=mock.AsyncMock(return_value=persisted),
    )

    result = await svc.create_batch(
        mock.AsyncMock(spec=AsyncSession),
        str(novel_id),
        [
            RevealPlanCreate(
                target_type="world_entity",
                target_id=target_id,
                secret_summary="秘密",
            )
        ],
    )

    assert result[0].target_id == str(target_id)
    svc.repo.create.assert_not_awaited()
    svc.repo.create_batch.assert_awaited_once()
