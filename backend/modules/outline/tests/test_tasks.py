from __future__ import annotations

import uuid
from unittest import mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import StructureContextBundle
from modules.outline.repositories import OutlineArcRepository, PlotThreadRepository
from modules.outline.services import PlotStructureGenerator


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
            {"name": "落星阁", "entity_type": "location", "summary": "故事起点"},
        ],
        characters=[
            {"name": "白砚", "role": "protagonist", "desire": "寻找真相"},
            {"name": "苏荇", "role": "mentor", "desire": "守护秘密"},
        ],
    )


class TestPlotStructureGenerator:
    """T6: AI 生成管线"""

    @pytest.mark.asyncio
    async def test_generate_creates_threads_and_arcs(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        bundle = _make_bundle(sample_novel_id)
        _mock_compile = mock.AsyncMock(return_value=bundle)

        with (
            mock.patch(
                "modules.context.facade.compile_structure_context", return_value=bundle
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured"
            ) as mock_llm,
            mock.patch(
                "modules.outline.services._container_get", return_value=_mock_compile
            ),
        ):
            from pydantic import BaseModel

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

            class _GO(BaseModel):
                plot_threads: list[_GT] = []
                outline_arcs: list[_GA] = []
                foreshadowing_plans: list[_FP] = []
                reveal_plans: list[_RP] = []
                offscreen_progress: list[_OP] = []
                risks: list[_RK] = []
                questions_for_user: list[_QN] = []

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

            generator = PlotStructureGenerator()
            result = await generator.generate(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=10,
            )

        assert result["total_threads"] == 2
        assert result["total_arcs"] == 2
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
        _mock_compile = mock.AsyncMock(return_value=bundle)

        with (
            mock.patch(
                "modules.context.facade.compile_structure_context", return_value=bundle
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured"
            ) as mock_llm,
            mock.patch(
                "modules.outline.services._container_get", return_value=_mock_compile
            ),
        ):
            from pydantic import BaseModel

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

            class _GO(BaseModel):
                plot_threads: list[_GT] = []
                outline_arcs: list[_GA] = []
                foreshadowing_plans: list[_FP] = []
                reveal_plans: list[_RP] = []
                offscreen_progress: list[_OP] = []
                risks: list[_RK] = []
                questions_for_user: list[_QN] = []

            mock_llm.return_value = _GO(plot_threads=[], outline_arcs=[])

            generator = PlotStructureGenerator()
            result = await generator.generate(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=10,
            )

        assert result["total_threads"] == 0
        assert result["total_arcs"] == 0
        assert "extra_sections" in result

    @pytest.mark.asyncio
    async def test_generate_llm_failure_graceful(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        """LLM 异常时应优雅降级"""
        bundle = _make_bundle(sample_novel_id)
        _mock_compile = mock.AsyncMock(return_value=bundle)

        with (
            mock.patch(
                "modules.context.facade.compile_structure_context", return_value=bundle
            ),
            mock.patch(
                "infrastructure.llm.client.LLMClient.generate_structured",
                side_effect=Exception("LLM down"),
            ),
            mock.patch(
                "modules.outline.services._container_get", return_value=_mock_compile
            ),
        ):
            generator = PlotStructureGenerator()
            result = await generator.generate(
                db_session,
                sample_novel_id,
                start_chapter=1,
                end_chapter=10,
            )

        assert result["total_threads"] == 0
        assert result["total_arcs"] == 0
        assert "extra_sections" in result
