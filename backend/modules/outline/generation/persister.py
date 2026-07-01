"""剧情结构生成器的持久化模块。

负责将 ParsedPlotStructure 通过 outline service 层写入各表，
并返回与现有 /api/outline/generate 端点兼容的响应字典。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.generation.models import (
    ForeshadowingPlan as GeneratedForeshadowingPlan,
)
from modules.outline.generation.models import (
    GeneratedArc,
    GeneratedScene,
    GeneratedThread,
)
from modules.outline.generation.models import (
    RevealPlan as GeneratedRevealPlan,
)
from modules.outline.generation.parser import ParsedPlotStructure
from modules.outline.schemas import (
    OutlineArcCreate,
    PlotThreadCreate,
    SceneCreate,
)

if TYPE_CHECKING:
    from modules.outline.services import (
        ForeshadowingPlanService,
        OutlineArcService,
        PlotThreadService,
        RevealPlanService,
        SceneService,
    )

logger = logging.getLogger(__name__)


def _sanitize_ge_1(value: int | None, default: int | None = None) -> int | None:
    """确保章节索引类字段满足 Pydantic ge=1 约束。

    LLM 可能输出 0 或负数；原实现通过 repository 直接绕过 Pydantic 校验，
    现统一走 service 层，因此在持久化前做最小清洗。
    """
    if value is None:
        return default
    return value if value >= 1 else default


def _truncate(
    value: str | None,
    max_length: int,
    default: str | None = None,
) -> str | None:
    """截断字符串至数据库/Schema 允许的最大长度。"""
    if value is None:
        return default
    return value[:max_length]


def _deep_import_provenance(workflow_id: str | None) -> dict[str, Any]:
    if not workflow_id:
        return {}
    return {
        "source": "deep_import",
        "workflow_id": workflow_id,
        "auto_ingested": True,
        "needs_review": False,
        "user_edited": False,
        "phase": "structure_analysis",
    }


@dataclass
class PersistResult:
    """持久化结果。"""

    total_threads: int = 0
    total_arcs: int = 0
    total_scenes: int = 0
    existing_threads_count: int = 0
    existing_arcs_count: int = 0
    threads: list[dict] = None  # type: ignore[assignment]
    arcs: list[dict] = None  # type: ignore[assignment]
    scenes: list[dict] = None  # type: ignore[assignment]
    extra_sections: dict = None  # type: ignore[assignment]
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.threads is None:
            self.threads = []
        if self.arcs is None:
            self.arcs = []
        if self.scenes is None:
            self.scenes = []
        if self.extra_sections is None:
            self.extra_sections = {}
        if self.warnings is None:
            self.warnings = []

    def to_dict(self) -> dict[str, Any]:
        """转换为 API 响应字典。"""
        return {
            "total_threads": self.total_threads,
            "total_arcs": self.total_arcs,
            "total_scenes": self.total_scenes,
            "existing_threads_count": self.existing_threads_count,
            "existing_arcs_count": self.existing_arcs_count,
            "threads": self.threads,
            "arcs": self.arcs,
            "scenes": self.scenes,
            "extra_sections": self.extra_sections,
            "warnings": self.warnings,
        }


class PlotStructurePersister:
    """将通过 LLM 解析的剧情结构持久化到 outline 各表。"""

    def __init__(
        self,
        thread_service: PlotThreadService,
        arc_service: OutlineArcService,
        scene_service: SceneService,
        foreshadowing_service: ForeshadowingPlanService,
        reveal_service: RevealPlanService,
    ) -> None:
        self._thread_service = thread_service
        self._arc_service = arc_service
        self._scene_service = scene_service
        self._foreshadowing_service = foreshadowing_service
        self._reveal_service = reveal_service

    async def persist(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
        parsed: ParsedPlotStructure,
        entity_name_to_id: dict[str, str],
        character_name_to_id: dict[str, str],
        workflow_id: str | None = None,
    ) -> PersistResult:
        """持久化解析结果。"""
        result = PersistResult()
        provenance_meta = _deep_import_provenance(workflow_id)

        existing_threads, existing_arcs = await self._check_duplicates(
            db, novel_id, start_chapter, end_chapter
        )
        result.existing_threads_count = existing_threads
        result.existing_arcs_count = existing_arcs
        if existing_threads > 0 or existing_arcs > 0:
            msg = (
                f"章节 {start_chapter}-{end_chapter} 已有 "
                f"{existing_threads} 条剧情线、{existing_arcs} 个篇章纲"
            )
            logger.warning("Duplicate generation warning: %s", msg)
            result.warnings.append(msg)

        created_threads = await self._persist_threads(
            db,
            novel_id,
            start_chapter,
            parsed.threads,
            character_name_to_id,
            entity_name_to_id,
            provenance_meta,
        )
        result.threads = created_threads
        result.total_threads = len(created_threads)

        thread_name_to_id = {t["name"]: t["id"] for t in created_threads}

        created_arcs = await self._persist_arcs(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            parsed.arcs,
            thread_name_to_id,
            character_name_to_id,
            entity_name_to_id,
            provenance_meta,
        )
        result.arcs = created_arcs
        result.total_arcs = len(created_arcs)

        plans_result = await self._persist_foreshadowing_and_reveals(
            db,
            novel_id,
            parsed.foreshadowing_plans,
            parsed.reveal_plans,
            entity_name_to_id,
            character_name_to_id,
            provenance_meta,
        )
        created_foreshadowing, created_reveals = plans_result

        created_scenes = await self._persist_scenes(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            parsed.scenes,
        )
        result.scenes = created_scenes
        result.total_scenes = len(created_scenes)

        result.extra_sections = {
            "foreshadowing_plans": created_foreshadowing,
            "reveal_plans": created_reveals,
            "offscreen_progress": [p.model_dump() for p in parsed.offscreen_progress],
            "risks": [r.model_dump() for r in parsed.risks],
            "questions_for_user": [q.model_dump() for q in parsed.questions_for_user],
        }

        return result

    async def _check_duplicates(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
    ) -> tuple[int, int]:
        """检查目标章节范围是否已有剧情线/篇章纲。"""
        existing_threads = await self._thread_service.count_by_novel_and_range(
            db, novel_id, start_chapter, end_chapter
        )
        existing_arcs = await self._arc_service.count_by_novel_and_range(
            db, novel_id, start_chapter, end_chapter
        )
        return existing_threads, existing_arcs

    async def _persist_threads(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        threads: list[GeneratedThread],
        character_name_to_id: dict[str, str],
        entity_name_to_id: dict[str, str],
        provenance_meta: dict[str, Any],
    ) -> list[dict]:
        """持久化剧情线。"""
        created: list[dict] = []
        for t in threads:
            if not t.name:
                continue

            thread_char_ids = [
                character_name_to_id[n]
                for n in t.related_character_names
                if n in character_name_to_id
            ]
            thread_entity_ids = [
                entity_name_to_id[n]
                for n in t.related_entity_names
                if n in entity_name_to_id
            ]

            thread_data = PlotThreadCreate(
                name=t.name,
                thread_type=t.thread_type,
                summary=t.summary,
                visible_goal=t.visible_goal,
                hidden_truth=t.hidden_truth,
                start_chapter=_sanitize_ge_1(t.start_chapter, default=start_chapter),
                planned_payoff_chapter=_sanitize_ge_1(t.planned_payoff_chapter),
                current_stage=t.current_stage,
                related_character_ids=thread_char_ids,
                related_entity_ids=thread_entity_ids,
                provenance_meta=dict(provenance_meta),
                status="draft",
            )
            try:
                thread_resp = await self._thread_service.create(
                    db, str(novel_id), thread_data
                )
                created.append(
                    {
                        "id": str(thread_resp.id),
                        "name": thread_resp.name,
                        "thread_type": thread_resp.thread_type,
                    }
                )
            except Exception as exc:
                logger.warning("Failed to create thread '%s': %s", t.name, exc)
        return created

    async def _persist_arcs(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
        arcs: list[GeneratedArc],
        thread_name_to_id: dict[str, str],
        character_name_to_id: dict[str, str],
        entity_name_to_id: dict[str, str],
        provenance_meta: dict[str, Any],
    ) -> list[dict]:
        """持久化篇章纲。"""
        created: list[dict] = []
        for a in arcs:
            if not a.title:
                continue

            arc_related_thread_ids = [
                thread_name_to_id[n]
                for n in a.related_thread_names
                if n in thread_name_to_id
            ]
            arc_related_char_ids = [
                character_name_to_id[n]
                for n in a.related_character_names
                if n in character_name_to_id
            ]
            arc_related_entity_ids = [
                entity_name_to_id[n]
                for n in a.related_entity_names
                if n in entity_name_to_id
            ]

            arc_data = OutlineArcCreate(
                title=a.title,
                arc_index=_sanitize_ge_1(a.arc_index),
                start_chapter=_sanitize_ge_1(a.start_chapter, default=start_chapter),
                end_chapter=_sanitize_ge_1(a.end_chapter, default=end_chapter),
                arc_goal=a.arc_goal,
                core_conflict=a.core_conflict,
                main_opposition=a.main_opposition,
                entry_hook=a.entry_hook,
                midpoint_turn=a.midpoint_turn,
                climax=a.climax,
                result=a.result,
                next_hook=a.next_hook,
                related_thread_ids=arc_related_thread_ids,
                related_character_ids=arc_related_char_ids,
                related_entity_ids=arc_related_entity_ids,
                provenance_meta=dict(provenance_meta),
                status="draft",
            )
            try:
                arc_resp = await self._arc_service.create(db, str(novel_id), arc_data)
                created.append(
                    {
                        "id": str(arc_resp.id),
                        "title": arc_resp.title,
                        "arc_index": arc_resp.arc_index,
                    }
                )
            except Exception as exc:
                logger.warning("Failed to create arc '%s': %s", a.title, exc)
        return created

    async def _persist_foreshadowing_and_reveals(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        foreshadowing_plans: list[GeneratedForeshadowingPlan],
        reveal_plans: list[GeneratedRevealPlan],
        entity_name_to_id: dict[str, str],
        character_name_to_id: dict[str, str],
        provenance_meta: dict[str, Any],
    ) -> tuple[list[dict], list[dict]]:
        """持久化伏笔计划和揭示计划。"""
        created_foreshadowing: list[dict] = []
        for fp in foreshadowing_plans:
            if not fp.name:
                continue
            try:
                from modules.outline.schemas import ForeshadowingPlanCreate

                plan = await self._foreshadowing_service.create(
                    db,
                    str(novel_id),
                    ForeshadowingPlanCreate(
                        name=fp.name,
                        summary=fp.summary,
                        surface_meaning=getattr(fp, "surface_meaning", None),
                        hidden_meaning=getattr(fp, "hidden_meaning", None),
                        planned_seed_chapter=fp.planned_seed_chapter,
                        planned_payoff_chapter=fp.planned_payoff_chapter,
                        provenance_meta=dict(provenance_meta),
                        status="draft",
                    ),
                )
                created_foreshadowing.append(
                    {
                        "id": str(plan.id),
                        "name": plan.name,
                    }
                )
            except Exception as exc:
                logger.warning("Failed to create foreshadowing '%s': %s", fp.name, exc)

        created_reveals: list[dict] = []
        for rp in reveal_plans:
            if not rp.target_name:
                continue
            target_id = entity_name_to_id.get(rp.target_name) or character_name_to_id.get(
                rp.target_name
            )
            try:
                from modules.outline.schemas import RevealPlanCreate

                plan = await self._reveal_service.create(
                    db,
                    str(novel_id),
                    RevealPlanCreate(
                        target_type=rp.target_type,
                        target_id=uuid.UUID(
                            target_id or "00000000-0000-0000-0000-000000000000"
                        ),
                        secret_summary=rp.secret_summary or "",
                        provenance_meta=dict(provenance_meta),
                        status="draft",
                    ),
                )
                created_reveals.append(
                    {
                        "id": str(plan.id),
                        "target_name": rp.target_name,
                    }
                )
            except Exception as exc:
                logger.warning(
                    "Failed to create reveal for '%s': %s",
                    rp.target_name,
                    exc,
                )

        return created_foreshadowing, created_reveals

    async def _persist_scenes(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
        scenes: list[GeneratedScene],
    ) -> list[dict]:
        """持久化 Scene 卡。"""
        existing_scene_contracts = await self._scene_service.get_ordered(
            db, str(novel_id)
        )
        next_scene_index = (
            max([s.scene_index for s in existing_scene_contracts], default=-1) + 1
        )

        created: list[dict] = []
        for s in scenes:
            if not s.title:
                continue

            cs = s.chapter_start if s.chapter_start is not None else start_chapter
            ce = s.chapter_end if s.chapter_end is not None else end_chapter
            chapter_ids = [str(i) for i in range(cs, ce + 1)]

            chunks = s.scene_chunks
            if not chunks:
                chunks = [
                    {"chapter_index": i, "start_pos": 0, "end_pos": 0}
                    for i in range(cs, ce + 1)
                ]

            scene_data = SceneCreate(
                scene_index=next_scene_index,
                title=s.title,
                goal=s.goal,
                core_conflict=s.core_conflict,
                emotional_beat=s.emotional_beat,
                must_happen=s.must_happen,
                must_not_happen=s.must_not_happen,
                narrative_tag=_truncate(s.narrative_tag, 32, "draft"),
                source="ai",
                scene_chunks=chunks,
                chapter_ids=chapter_ids,
                status="draft",
            )
            try:
                scene_resp = await self._scene_service.create(
                    db, str(novel_id), scene_data
                )
                created.append(
                    {
                        "id": str(scene_resp.id),
                        "title": scene_resp.title,
                        "scene_index": scene_resp.scene_index,
                    }
                )
                next_scene_index += 1
            except Exception as exc:
                logger.warning("Failed to create scene '%s': %s", s.title, exc)

        return created
