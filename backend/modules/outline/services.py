from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.crud import CrudService
from modules.outline.contracts import (
    OutlineArcContract,
    PlotThreadContract,
    SceneContract,
)
from modules.outline.foreshadowing_repository import ForeshadowingPlanRepository
from modules.outline.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
)
from modules.outline.repositories import (
    OutlineArcRepository,
    PlotThreadRepository,
    SceneRepository,
)
from modules.outline.reveal_repository import RevealPlanRepository
from modules.outline.schemas import (
    ForeshadowingPlanCreate,
    ForeshadowingPlanListResponse,
    ForeshadowingPlanResponse,
    ForeshadowingPlanUpdate,
    OutlineArcCreate,
    OutlineArcListResponse,
    OutlineArcResponse,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadListResponse,
    PlotThreadResponse,
    PlotThreadUpdate,
    RevealPlanCreate,
    RevealPlanListResponse,
    RevealPlanResponse,
    RevealPlanUpdate,
    SceneCreate,
    SceneListResponse,
    SceneResponse,
    SceneUpdate,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)


class PlotThreadService(
    CrudService[PlotThread, PlotThreadCreate, PlotThreadUpdate, PlotThreadResponse]
):
    repo = PlotThreadRepository()
    response = PlotThreadResponse
    list_response = PlotThreadListResponse
    label = "PlotThread"
    id_param = "thread_id"

    async def get_active(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> list[PlotThreadContract]:
        nid = parse_uuid(novel_id, "novel_id")
        threads = await self.repo.get_active(db, nid, chapter_index)
        return [
            PlotThreadContract(
                id=str(t.id),
                novel_id=str(t.novel_id),
                name=t.name,
                thread_type=t.thread_type,
                summary=t.summary,
                visible_goal=t.visible_goal,
                hidden_truth=t.hidden_truth,
                start_chapter=t.start_chapter,
                planned_payoff_chapter=t.planned_payoff_chapter,
                current_stage=t.current_stage,
                related_character_ids=t.related_character_ids or [],
                related_entity_ids=t.related_entity_ids or [],
                reader_known_state=t.reader_known_state,
                author_known_state=t.author_known_state,
                status=t.status,
            )
            for t in threads
        ]

    async def count_by_novel_and_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
    ) -> int:
        """统计与 [start_chapter, end_chapter] 范围重叠的剧情线数量。"""
        return await self.repo.count_by_novel_and_range(
            db, novel_id, start_chapter, end_chapter
        )


class OutlineArcService(
    CrudService[OutlineArc, OutlineArcCreate, OutlineArcUpdate, OutlineArcResponse]
):
    repo = OutlineArcRepository()
    response = OutlineArcResponse
    list_response = OutlineArcListResponse
    label = "OutlineArc"
    id_param = "arc_id"

    async def get_by_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> OutlineArcContract | None:
        nid = parse_uuid(novel_id, "novel_id")
        arc = await self.repo.get_by_chapter(db, nid, chapter_index)
        if arc is None:
            return None
        return OutlineArcContract(
            id=str(arc.id),
            novel_id=str(arc.novel_id),
            title=arc.title,
            arc_index=arc.arc_index,
            start_chapter=arc.start_chapter,
            end_chapter=arc.end_chapter,
            arc_goal=arc.arc_goal,
            core_conflict=arc.core_conflict,
            main_opposition=arc.main_opposition,
            entry_hook=arc.entry_hook,
            midpoint_turn=arc.midpoint_turn,
            climax=arc.climax,
            result=arc.result,
            next_hook=arc.next_hook,
            related_thread_ids=arc.related_thread_ids or [],
            related_character_ids=arc.related_character_ids or [],
            related_entity_ids=arc.related_entity_ids or [],
            status=arc.status,
        )

    async def count_by_novel_and_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
    ) -> int:
        """统计章节范围 [start, end] 内重叠的篇章数。"""
        return await self.repo.count_by_novel_and_range(
            db, novel_id, start_chapter, end_chapter
        )


class ForeshadowingPlanService(
    CrudService[
        ForeshadowingPlan,
        ForeshadowingPlanCreate,
        ForeshadowingPlanUpdate,
        ForeshadowingPlanResponse,
    ]
):
    repo = ForeshadowingPlanRepository()
    response = ForeshadowingPlanResponse
    list_response = ForeshadowingPlanListResponse
    label = "ForeshadowingPlan"
    id_param = "plan_id"

    async def get_foreshadowing_plan(
        self,
        db: AsyncSession,
        plan_id: str,
        novel_id: str,
    ) -> ForeshadowingPlanResponse:
        return await self.get(db, plan_id, novel_id=novel_id)

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: ForeshadowingPlanCreate,
    ) -> ForeshadowingPlanResponse:
        nid = parse_uuid(novel_id, "novel_id")
        plan = await self.repo.create(db, nid, data.model_dump())
        return self.response.model_validate(plan)

    async def update(
        self,
        db: AsyncSession,
        id: str,
        data: ForeshadowingPlanUpdate,
        *,
        novel_id: str,
    ) -> ForeshadowingPlanResponse:
        return await super().update(
            db,
            id,
            data.model_dump(exclude_unset=True),
            novel_id=novel_id,
        )


class RevealPlanService(
    CrudService[RevealPlan, RevealPlanCreate, RevealPlanUpdate, RevealPlanResponse]
):
    repo = RevealPlanRepository()
    response = RevealPlanResponse
    list_response = RevealPlanListResponse
    label = "RevealPlan"
    id_param = "plan_id"

    async def get_reveal_plan(
        self,
        db: AsyncSession,
        plan_id: str,
        novel_id: str,
    ) -> RevealPlanResponse:
        return await self.get(db, plan_id, novel_id=novel_id)

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: RevealPlanCreate,
    ) -> RevealPlanResponse:
        nid = parse_uuid(novel_id, "novel_id")
        payload = data.model_dump()
        plan = await self.repo.create(db, nid, payload)
        return self.response.model_validate(plan)

    async def update(
        self,
        db: AsyncSession,
        id: str,
        data: RevealPlanUpdate,
        *,
        novel_id: str,
    ) -> RevealPlanResponse:
        return await super().update(
            db,
            id,
            data.model_dump(exclude_unset=True),
            novel_id=novel_id,
        )


class SceneService(CrudService[Scene, SceneCreate, SceneUpdate, SceneResponse]):
    repo = SceneRepository()
    response = SceneResponse
    list_response = SceneListResponse
    label = "Scene"
    id_param = "scene_id"

    async def get_ordered(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[SceneContract]:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self.repo.get_by_novel_ordered(db, nid)
        return [
            SceneContract(
                id=str(s.id),
                novel_id=str(s.novel_id),
                scene_index=s.scene_index,
                title=s.title,
                goal=s.goal,
                core_conflict=s.core_conflict,
                emotional_beat=s.emotional_beat,
                must_happen=s.must_happen,
                must_not_happen=s.must_not_happen,
                narrative_tag=s.narrative_tag,
                source=s.source,
                scene_chunks=s.scene_chunks or [],
                chapter_ids=s.chapter_ids or [],
                pov_character_id=s.pov_character_id,
                structure_meta=s.structure_meta or {},
                status=s.status,
            )
            for s in scenes
        ]

    async def get_by_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> list[SceneContract]:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self.repo.get_by_chapter(db, nid, chapter_index)
        return [
            SceneContract(
                id=str(s.id),
                novel_id=str(s.novel_id),
                scene_index=s.scene_index,
                title=s.title,
                goal=s.goal,
                core_conflict=s.core_conflict,
                emotional_beat=s.emotional_beat,
                must_happen=s.must_happen,
                must_not_happen=s.must_not_happen,
                narrative_tag=s.narrative_tag,
                source=s.source,
                scene_chunks=s.scene_chunks or [],
                chapter_ids=s.chapter_ids or [],
                pov_character_id=s.pov_character_id,
                structure_meta=s.structure_meta or {},
                status=s.status,
            )
            for s in scenes
        ]

    async def reorder(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_ids: list[str],
    ) -> dict:
        """批量重排 Scene 顺序"""
        nid = parse_uuid(novel_id, "novel_id")
        ids = [parse_uuid(sid, "scene_id") for sid in scene_ids]
        updated = await self.repo.reorder(db, nid, ids)
        return {"updated": updated, "total": len(scene_ids)}

    async def split_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
        target_scene_id: str | None = None,
    ) -> list[SceneContract]:
        """断章：将章节从当前 Scene 移到目标 Scene（或新建 Scene）。

        从 chapter_index 开始的所有章节从源 Scene 移除，归入目标 Scene。
        如果 target_scene_id 为 None，则新建一个 Scene。
        """

        nid = parse_uuid(novel_id, "novel_id")
        tid = parse_uuid(target_scene_id, "scene_id") if target_scene_id else None

        # 找到包含此章节的源 Scene
        source_scene = await self.repo.get_by_chapter_index(db, nid, chapter_index)
        if source_scene is None:
            raise ValueError(f"Chapter {chapter_index} is not assigned to any Scene")

        src_ids = source_scene.chapter_ids or []
        # 找到断点位置
        split_point = None
        for i, cid in enumerate(src_ids):
            try:
                if int(cid) >= chapter_index:
                    split_point = i
                    break
            except (ValueError, TypeError):
                continue

        if split_point is None:
            raise ValueError(f"Chapter {chapter_index} not found in source Scene")

        # 从断点分割
        keep_ids = src_ids[:split_point]
        move_ids = src_ids[split_point:]

        # 更新源 Scene
        source_scene.chapter_ids = keep_ids
        db.add(source_scene)

        # 目标 Scene
        if tid:
            target = await self.repo.get(db, tid)
            if target is None or str(target.novel_id) != str(nid):
                raise ValueError(f"Target Scene {target_scene_id} not found")
            target_ids = list(target.chapter_ids or [])
            target_ids.extend(move_ids)
            target_ids = sorted(
                set(target_ids), key=lambda x: int(x) if str(x).isdigit() else 0
            )
            target.chapter_ids = target_ids
            db.add(target)
        else:
            # 新建 Scene
            new_scene = Scene(
                novel_id=nid,
                scene_index=source_scene.scene_index + 1,
                title=f"Scene (断章自 Ch.{chapter_index})",
                chapter_ids=move_ids,
                source="manual",
            )
            db.add(new_scene)

        await db.flush()

        # 返回更新后的 scenes
        scenes = await self.repo.get_by_novel_ordered(db, nid)
        return [
            SceneContract(
                id=str(s.id),
                novel_id=str(s.novel_id),
                scene_index=s.scene_index,
                title=s.title,
                goal=s.goal,
                core_conflict=s.core_conflict,
                emotional_beat=s.emotional_beat,
                must_happen=s.must_happen,
                must_not_happen=s.must_not_happen,
                narrative_tag=s.narrative_tag,
                source=s.source,
                scene_chunks=s.scene_chunks or [],
                chapter_ids=s.chapter_ids or [],
                pov_character_id=s.pov_character_id,
                structure_meta=s.structure_meta or {},
                status=s.status,
            )
            for s in scenes
        ]

    async def split_scene_chunk_to_new_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        source_scene_id: str,
        source_chapter_id: str,
        source_chapter_index: int,
        new_chapter_id: str,
        new_chapter_index: int,
        split_pos: int,
        new_chapter_length: int,
    ) -> list[Scene]:
        """将 source_scene 中指定 chapter 的 chunk 从 split_pos 处切分，

        后半部分归属到新 chapter 对应的新 Scene。
        """
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(source_scene_id, "scene_id")
        source = await self.repo.get(db, sid)
        if source is None or str(source.novel_id) != str(nid):
            raise ValueError(f"Source Scene {source_scene_id} not found")

        chunks = source.scene_chunks or []
        target_chunk = None
        for chunk in chunks:
            if (
                chunk.get("chapter_id") == source_chapter_id
                or chunk.get("chapter_index") == source_chapter_index
            ):
                target_chunk = chunk
                break

        if target_chunk is None:
            raise ValueError(
                f"Chapter {source_chapter_id} not found in source Scene chunks"
            )

        start_pos = target_chunk.get("start_pos", 0)
        end_pos = target_chunk.get("end_pos", 0)
        if not (start_pos < split_pos < end_pos):
            raise ValueError(
                f"split_pos {split_pos} must be inside chunk range "
                f"({start_pos}, {end_pos})"
            )

        target_chunk["end_pos"] = split_pos
        source.scene_chunks = chunks
        db.add(source)

        new_scene = Scene(
            novel_id=nid,
            scene_index=source.scene_index + 1,
            chapter_ids=[new_chapter_id],
            scene_chunks=[
                {
                    "chapter_id": new_chapter_id,
                    "chapter_index": new_chapter_index,
                    "start_pos": 0,
                    "end_pos": new_chapter_length,
                }
            ],
            source="manual",
            narrative_tag="draft",
            status="draft",
        )
        db.add(new_scene)

        # Shift later scene_index values（排除刚新建的 Scene）
        later = await self.repo.get_by_novel_ordered(db, nid)
        excluded_ids = {source.id, new_scene.id}
        for s in later:
            if s.id not in excluded_ids and s.scene_index > source.scene_index:
                s.scene_index = s.scene_index + 1
                db.add(s)

        await db.flush()

        scenes = await self.repo.get_by_novel_ordered(db, nid)
        return list(scenes)


__all__ = [
    "PlotThreadService",
    "OutlineArcService",
    "ForeshadowingPlanService",
    "RevealPlanService",
    "SceneService",
]


def __getattr__(name: str) -> type:
    """懒加载兼容：PlotStructureGenerator 实际位于 modules.outline.generator。"""
    if name == "PlotStructureGenerator":
        from modules.outline.generator import PlotStructureGenerator as _Generator

        return _Generator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
