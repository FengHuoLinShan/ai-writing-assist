from __future__ import annotations

import uuid
from unittest import mock

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.outline_state.generation.context_builder import PlotStructureContext
from modules.story.outline_state.generation.models import GeneratedThread
from modules.story.outline_state.generation.parser import PlotStructureParser
from modules.story.outline_state.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
)
from modules.story.outline_state.repositories import (
    OutlineArcRepository,
    PlotThreadRepository,
    SceneRepository,
)
from modules.story.outline_state.services import PlotStructureGenerator
from tests.utils import _make_bundle


def _mock_client(generate_structured: mock.AsyncMock) -> mock.MagicMock:
    client = mock.MagicMock(model_name="test-model")

    async def bound_generate(*args, **kwargs):
        return await generate_structured(client, *args, **kwargs)

    client.generate_structured = mock.AsyncMock(side_effect=bound_generate)
    return client


# Shared Pydantic response models used by LLM mocks in TestPlotStructureGenerator.
# These were previously defined inside each test method, causing duplication.


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


class _CaptureLLM:
    def __init__(self) -> None:
        self.request = None
        self.kwargs = None

    async def generate_structured(self, request, schema, **kwargs):
        self.request = request
        self.kwargs = kwargs
        return schema(
            plot_threads=[
                GeneratedThread(
                    name="主线：灰雾召唤",
                    thread_type="main",
                    summary="克莱恩接触灰雾空间",
                )
            ],
            scenes=[],
        )


class TestPlotStructureParserDeepImportMode:
    @pytest.mark.asyncio
    async def test_deep_import_without_scene_evidence_returns_review_empty(self) -> None:
        context = PlotStructureContext(
            markdown="## 已生成 Scene 摘要\n- S0 第1章《穿越苏醒》：克莱恩醒来\n"
        )
        llm = _CaptureLLM()

        result = await PlotStructureParser(
            context,
            include_scenes=False,
            fast_structured=True,
        ).parse(llm, "codex-5.3", 1, 7)

        assert result is not None
        assert result.threads == []
        assert result.arcs == []
        assert result.diagnostics == {
            "parameter_version": "phase3_structure_simple_v2",
            "input_mode": "no_scene_evidence",
            "prompt_level": "none",
            "provider_called": False,
            "needs_review": True,
        }
        assert llm.request is None


@pytest.mark.skip(reason="legacy monolithic structure generation retired by P20 v2")
class TestPlotStructureGenerator:
    """T6: AI 生成管线"""

    @pytest.mark.asyncio
    async def test_generate_persists_deep_import_structure_provenance(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        bundle = _make_bundle(sample_novel_id)
        target_id = uuid.uuid4()
        bundle.world_entities[0]["entity_id"] = str(target_id)
        expected_meta = {
            "source": "deep_import",
            "workflow_id": "wf-structure",
            "auto_ingested": True,
            "needs_review": False,
            "user_edited": False,
            "phase": "structure_analysis",
        }

        with (
            mock.patch(
                "modules.evidence.facade.compile_structure_context",
                return_value=bundle,
                autospec=True,
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured",
                autospec=True,
            ) as mock_llm,
        ):
            mock_llm.return_value = _GO(
                plot_threads=[
                    _GT(
                        name="主线：寻剑",
                        thread_type="main",
                        summary="主角寻找霜华剑",
                        start_chapter=1,
                    )
                ],
                outline_arcs=[
                    _GA(
                        title="第一卷：启程",
                        arc_index=1,
                        start_chapter=1,
                        end_chapter=3,
                        related_thread_names=["主线：寻剑"],
                    )
                ],
                foreshadowing_plans=[
                    _FP(
                        name="古剑封印",
                        summary="主角发现古剑秘密",
                        planned_seed_chapter=1,
                        planned_payoff_chapter=3,
                    )
                ],
                reveal_plans=[
                    _RP(
                        target_name="霜华剑",
                        target_type="world_entity",
                        secret_summary="古剑封印着魔神",
                    )
                ],
            )
            await PlotStructureGenerator(llm_client=_mock_client(mock_llm)).generate(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=3,
                workflow_id="wf-structure",
                context_mode="working",
                include_pending_objects=True,
                persist=True,
            )

        for model in (PlotThread, OutlineArc, ForeshadowingPlan, RevealPlan):
            item = (
                await db_session.execute(
                    select(model).where(model.novel_id == uuid.UUID(sample_novel_id))
                )
            ).scalar_one()
            assert item.provenance_meta == expected_meta

    @pytest.mark.asyncio
    async def test_generate_creates_threads_and_arcs(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        bundle = _make_bundle(sample_novel_id)

        with (
            mock.patch(
                "modules.evidence.facade.compile_structure_context",
                return_value=bundle,
                autospec=True,
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured",
                autospec=True,
            ) as mock_llm,
        ):
            mock_llm.return_value = _GO(
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
                        start_chapter=11,
                        end_chapter=20,
                        arc_goal="寻找霜华剑",
                    ),
                ],
            )

            generator = PlotStructureGenerator(llm_client=_mock_client(mock_llm))
            result = await generator.generate(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=10,
                persist=True,
            )

        assert result["total_threads"] == 2
        assert result["total_arcs"] == 2
        assert result["total_scenes"] == 0
        assert "scenes" in result
        assert "extra_sections" in result
        assert isinstance(result["extra_sections"], dict)

        threads, _ = await PlotThreadRepository().get_by_novel(
            db_session,
            uuid.UUID(hex=sample_novel_id),
        )
        assert len(threads) == 2
        thread_names = [t.name for t in threads]
        assert "主线：寻剑" in thread_names
        assert "暗线：魔神复苏" in thread_names

        arcs, _ = await OutlineArcRepository().get_by_novel(
            db_session,
            uuid.UUID(hex=sample_novel_id),
        )
        assert len(arcs) == 2
        arc_titles = [a.title for a in arcs]
        assert "第一卷：启程" in arc_titles
        assert "第二卷：寻剑" in arc_titles

    @pytest.mark.asyncio
    async def test_generate_empty_llm_output(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """LLM 返回空列表时不应崩溃"""
        bundle = _make_bundle(sample_novel_id)

        with (
            mock.patch(
                "modules.evidence.facade.compile_structure_context",
                return_value=bundle,
                autospec=True,
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured",
                autospec=True,
            ) as mock_llm,
        ):
            mock_llm.return_value = _GO(plot_threads=[], outline_arcs=[])

            generator = PlotStructureGenerator(llm_client=_mock_client(mock_llm))
            result = await generator.generate(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=10,
            )

        assert result["total_threads"] == 0
        assert result["total_arcs"] == 0
        assert result["total_scenes"] == 0
        assert "scenes" in result
        assert "extra_sections" in result

    @pytest.mark.asyncio
    async def test_generate_creates_scenes(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """LLM 返回 Scene 数据时应创建 Scene 卡。"""
        bundle = _make_bundle(sample_novel_id)

        with (
            mock.patch(
                "modules.evidence.facade.compile_structure_context",
                return_value=bundle,
                autospec=True,
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured",
                autospec=True,
            ) as mock_llm,
        ):
            mock_llm.return_value = _GO(
                scenes=[
                    _GS(
                        title="初入落星阁",
                        goal="主角进入落星阁",
                        core_conflict="主角与守阁人对峙",
                        emotional_beat="紧张",
                        must_happen="主角拿到令牌",
                        narrative_tag="exposition",
                        chapter_start=1,
                        chapter_end=1,
                        scene_chunks=[
                            {"chapter_index": 1, "start_pos": 0, "end_pos": 100}
                        ],
                    ),
                    _GS(
                        title="霜华剑异动",
                        goal="霜华剑出现异动",
                        chapter_start=2,
                        chapter_end=3,
                    ),
                ],
            )

            generator = PlotStructureGenerator(llm_client=_mock_client(mock_llm))
            result = await generator.generate(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=3,
                persist=True,
            )

        assert result["total_scenes"] == 2
        assert len(result["scenes"]) == 2
        assert result["scenes"][0]["title"] == "初入落星阁"
        assert result["scenes"][0]["scene_index"] == 0
        assert result["scenes"][1]["scene_index"] == 1

        scenes, _ = await SceneRepository().get_by_novel(
            db_session,
            uuid.UUID(hex=sample_novel_id),
        )
        assert len(scenes) == 2
        titles = [s.title for s in scenes]
        assert "初入落星阁" in titles
        assert "霜华剑异动" in titles

    @pytest.mark.asyncio
    async def test_generate_llm_failure_graceful(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """LLM 异常时应优雅降级"""
        bundle = _make_bundle(sample_novel_id)

        with (
            mock.patch(
                "modules.evidence.facade.compile_structure_context",
                return_value=bundle,
                autospec=True,
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured",
                side_effect=Exception("LLM down"),
                autospec=True,
            ) as mock_llm,
        ):
            generator = PlotStructureGenerator(llm_client=_mock_client(mock_llm))
            result = await generator.generate(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=10,
            )

        assert result["total_threads"] == 0
        assert result["total_arcs"] == 0
        assert "extra_sections" in result
