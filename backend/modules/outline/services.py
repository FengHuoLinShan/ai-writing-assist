from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud import CrudService
from modules.outline.contracts import (
    OutlineArcContract,
    PlotThreadContract,
    SceneContract,
    SceneSpanContract,
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
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)


class StructureAssetFilterMixin:
    async def update(
        self,
        db: AsyncSession,
        id: str,
        data,
        *,
        novel_id: str,
    ):
        rid = parse_uuid(id, getattr(self, "id_param", "id"))
        nid = parse_uuid(novel_id, "novel_id")
        existing = await self.repo.get(db, rid)
        self._assert_found_in_novel(existing, id, nid)
        payload = _update_payload(data)
        meta = dict(getattr(existing, "provenance_meta", None) or {})
        if _should_mark_user_edited_meta(meta, payload, "provenance_meta"):
            data = _with_update_payload(
                data,
                payload,
                {
                    "provenance_meta": _mark_user_edited_meta(meta),
                },
            )
        return await super().update(db, id, data, novel_id=novel_id)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        status: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
    ):
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        objs, total = await self.repo.get_by_novel(
            db,
            nid,
            skip=skip,
            limit=limit,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
        )
        return [self._to_response(o) for o in objs], total

    async def list_with_response(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        status: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
    ) -> BaseModel:
        items, total = await self.list(
            db,
            novel_id,
            skip=skip,
            limit=limit,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
        )
        if self.list_response is None:
            raise TypeError(
                f"{self.__class__.__name__}.list_response is not set",
            )
        return self.list_response(items=items, total=total)


def _update_payload(data) -> dict[str, Any]:
    if isinstance(data, BaseModel):
        return data.model_dump(exclude_unset=True)
    if isinstance(data, dict):
        return dict(data)
    return {}


def _with_update_payload(data, payload: dict[str, Any], extra: dict[str, Any]):
    update = {**payload, **extra}
    if isinstance(data, BaseModel):
        copied = data.model_copy(update=extra)
        copied.model_fields_set.update(extra.keys())
        return copied
    return update


def _should_mark_user_edited_meta(
    meta: dict[str, Any],
    payload: dict[str, Any],
    meta_field: str,
    *,
    require_source: bool = True,
) -> bool:
    eligible = (
        bool(payload)
        and meta_field not in payload
        and meta.get("auto_ingested") is True
        and meta.get("user_edited") is not True
    )
    if require_source:
        return eligible and meta.get("source") == "deep_import"
    return eligible


def _mark_user_edited_meta(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        **meta,
        "user_edited": True,
        "edited_at": datetime.now(UTC).isoformat(),
    }


def _is_cleanup_eligible_deep_import_meta(
    meta: dict[str, Any],
    workflow_id: str,
    *,
    require_source: bool = True,
) -> bool:
    eligible = (
        meta.get("workflow_id") == workflow_id
        and meta.get("auto_ingested") is True
        and meta.get("user_edited") is not True
    )
    if require_source:
        return eligible and meta.get("source") == "deep_import"
    return eligible


def scene_to_contract(scene: Any) -> SceneContract:
    """Convert Scene ORM/response objects to the stable cross-module contract."""
    return SceneContract(
        id=str(scene.id),
        novel_id=str(scene.novel_id),
        scene_index=scene.scene_index,
        title=scene.title,
        goal=scene.goal,
        core_conflict=scene.core_conflict,
        emotional_beat=scene.emotional_beat,
        must_happen=scene.must_happen,
        must_not_happen=scene.must_not_happen,
        narrative_tag=scene.narrative_tag,
        source=scene.source,
        scene_chunks=scene.scene_chunks or [],
        chapter_ids=scene.chapter_ids or [],
        pov_character_id=scene.pov_character_id,
        structure_meta=scene.structure_meta or {},
        status=scene.status,
    )


def scene_span_to_contract(span: Any) -> SceneSpanContract:
    """Convert SceneSpan ORM objects to the stable cross-module contract."""
    return SceneSpanContract(
        id=str(span.id),
        novel_id=str(span.novel_id),
        scene_id=str(span.scene_id),
        chapter_index=span.chapter_index,
        content_mode=span.content_mode,
        source_draft_id=(
            str(span.source_draft_id) if span.source_draft_id is not None else None
        ),
        source_content_hash=span.source_content_hash,
        start_offset=span.start_offset,
        end_offset=span.end_offset,
        start_paragraph=span.start_paragraph,
        end_paragraph=span.end_paragraph,
        part_no=span.part_no,
        mapping_status=span.mapping_status,
        anchor_hash=span.anchor_hash,
        source=span.source,
        status=span.status,
    )


def foreshadowing_plan_to_dict(plan: ForeshadowingPlan) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "novel_id": str(plan.novel_id),
        "name": plan.name,
        "summary": plan.summary,
        "surface_meaning": plan.surface_meaning,
        "hidden_meaning": plan.hidden_meaning,
        "status": plan.status,
        "planned_seed_chapter": plan.planned_seed_chapter,
        "planned_payoff_chapter": plan.planned_payoff_chapter,
        "planned_payoff_scene": plan.planned_payoff_scene,
        "planned_reinforce_chapters": plan.planned_reinforce_chapters or [],
        "related_entity_ids": plan.related_entity_ids or [],
        "related_thread_ids": plan.related_thread_ids or [],
    }


class PlotThreadService(
    StructureAssetFilterMixin,
    CrudService[PlotThread, PlotThreadCreate, PlotThreadUpdate, PlotThreadResponse],
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

    async def create_batch(
        self,
        db: AsyncSession,
        novel_id: str,
        items: list[PlotThreadCreate],
    ) -> list[PlotThreadResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        threads = await self.repo.create_many(db, nid, items)
        return [self._to_response(thread) for thread in threads]


class OutlineArcService(
    StructureAssetFilterMixin,
    CrudService[OutlineArc, OutlineArcCreate, OutlineArcUpdate, OutlineArcResponse],
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

    async def create_batch(
        self,
        db: AsyncSession,
        novel_id: str,
        items: list[OutlineArcCreate],
    ) -> list[OutlineArcResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        arcs = await self.repo.create_many(db, nid, items)
        return [self._to_response(arc) for arc in arcs]


class ForeshadowingPlanService(
    StructureAssetFilterMixin,
    CrudService[
        ForeshadowingPlan,
        ForeshadowingPlanCreate,
        ForeshadowingPlanUpdate,
        ForeshadowingPlanResponse,
    ],
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

    async def create_batch(
        self,
        db: AsyncSession,
        novel_id: str,
        items: list[ForeshadowingPlanCreate],
    ) -> list[ForeshadowingPlanResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        plans = await self.repo.create_batch(
            db,
            nid,
            [item.model_dump() for item in items],
        )
        return [self.response.model_validate(plan) for plan in plans]

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

    async def get_active_dicts(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status: str = "seeded",
    ) -> list[dict[str, Any]]:
        nid = parse_uuid(novel_id, "novel_id")
        plans = await self.repo.get_active_by_status(db, nid, status=status)
        return [foreshadowing_plan_to_dict(plan) for plan in plans]


class RevealPlanService(
    StructureAssetFilterMixin,
    CrudService[RevealPlan, RevealPlanCreate, RevealPlanUpdate, RevealPlanResponse],
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

    async def create_batch(
        self,
        db: AsyncSession,
        novel_id: str,
        items: list[RevealPlanCreate],
    ) -> list[RevealPlanResponse]:
        nid = parse_uuid(novel_id, "novel_id")
        plans = await self.repo.create_batch(
            db,
            nid,
            [item.model_dump() for item in items],
        )
        return [self.response.model_validate(plan) for plan in plans]

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

    async def update(
        self,
        db: AsyncSession,
        id: str,
        data: SceneUpdate,
        *,
        novel_id: str,
    ) -> SceneResponse:
        rid = parse_uuid(id, self.id_param)
        nid = parse_uuid(novel_id, "novel_id")
        existing = await self.repo.get(db, rid)
        self._assert_found_in_novel(existing, id, nid)
        assert existing is not None
        payload = _update_payload(data)
        meta = dict(existing.structure_meta or {})
        if _should_mark_user_edited_meta(
            meta,
            payload,
            "structure_meta",
            require_source=False,
        ):
            data = _with_update_payload(
                data,
                payload,
                {
                    "structure_meta": _mark_user_edited_meta(meta),
                },
            )
        return await super().update(db, id, data, novel_id=novel_id)

    async def get_ordered(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[SceneContract]:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self.repo.get_by_novel_ordered(db, nid)
        return [scene_to_contract(scene) for scene in scenes]

    async def get_by_chapter_models(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> list[Scene]:
        nid = parse_uuid(novel_id, "novel_id")
        return await self.repo.get_by_chapter(db, nid, chapter_index)

    async def get_by_chapter_range_models(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> list[Scene]:
        nid = parse_uuid(novel_id, "novel_id")
        start = min(start_chapter, end_chapter)
        end = max(start_chapter, end_chapter)
        return await self.repo.get_by_chapter_range(db, nid, start, end)

    async def get_ordered_models(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status_filter: list[str] | None = None,
        exclude_narrative_tags: list[str] | None = None,
    ) -> list[Scene]:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self.repo.get_by_novel_ordered(db, nid)
        return [
            scene
            for scene in scenes
            if (not status_filter or scene.status in status_filter)
            and (
                not exclude_narrative_tags
                or scene.narrative_tag not in exclude_narrative_tags
            )
        ]

    async def get_by_provenance_key_models(
        self,
        db: AsyncSession,
        novel_id: str,
        provenance_key: str,
    ) -> list[Scene]:
        nid = parse_uuid(novel_id, "novel_id")
        return await self.repo.get_by_provenance_key(db, nid, provenance_key)

    async def get_by_provenance_keys_models(
        self,
        db: AsyncSession,
        novel_id: str,
        provenance_keys: list[str],
    ) -> list[Scene]:
        nid = parse_uuid(novel_id, "novel_id")
        return await self.repo.get_by_provenance_keys(db, nid, provenance_keys)

    async def count_by_novel(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status_filter: list[str] | None = None,
    ) -> int:
        nid = parse_uuid(novel_id, "novel_id")
        conditions = [Scene.novel_id == nid]
        if status_filter:
            conditions.append(Scene.status.in_(status_filter))
        stmt = select(func.count(Scene.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def create_model_from_dict(
        self,
        db: AsyncSession,
        novel_id: str,
        data: dict[str, Any],
    ) -> Scene:
        nid = parse_uuid(novel_id, "novel_id")
        return await self.repo.create(db, nid, SceneCreate(**data))

    async def batch_create_models_from_dicts(
        self,
        db: AsyncSession,
        novel_id: str,
        scenes_data: list[dict[str, Any]],
    ) -> list[Scene]:
        nid = parse_uuid(novel_id, "novel_id")
        return await self.repo.create_many(
            db,
            nid,
            [SceneCreate(**data) for data in scenes_data],
        )

    async def update_model_from_dict(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
        data: dict[str, Any],
    ) -> Scene | None:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(scene_id, "scene_id")
        scene = await self.repo.get(db, sid)
        if scene is None or scene.novel_id != nid:
            return None
        return await self.repo.update(db, sid, SceneUpdate(**data))

    async def get_next_scene_index(self, db: AsyncSession, novel_id: str) -> int:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(func.coalesce(func.max(Scene.scene_index), -1)).where(
            Scene.novel_id == nid,
        )
        result = await db.execute(stmt)
        current_max = result.scalar()
        return (current_max if current_max is not None else -1) + 1

    async def deprecate_deep_import_scenes_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(Scene).where(
            Scene.novel_id == nid,
            Scene.status.in_(["candidate", "proposal", "draft", "canonical"]),
            Scene.source == "deep_import",
            Scene.structure_meta["workflow_id"].as_string() == workflow_id,
            Scene.structure_meta["auto_ingested"].as_boolean().is_(True),
            Scene.structure_meta["user_edited"].as_boolean().is_not(True),
        )
        result = await db.execute(stmt)
        scenes = result.scalars().all()

        deprecated = 0
        repo = self.repo
        for scene in scenes:
            meta = scene.structure_meta or {}
            if not _is_cleanup_eligible_deep_import_meta(
                meta,
                workflow_id,
                require_source=False,
            ):
                continue
            updated_meta = {
                **meta,
                "cleanup_status": "deprecated",
                "cleanup_reason": "abandoned_deep_import_recovery",
            }
            scene.status = "deprecated"
            scene.structure_meta = updated_meta
            db.add(scene)
            deprecated += 1

        if deprecated:
            await db.flush()
            for scene in scenes:
                if scene.status == "deprecated":
                    await repo.sync_scene_spans(db, scene)
        return deprecated

    async def get_by_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> list[SceneContract]:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self.repo.get_by_chapter(db, nid, chapter_index)
        return [scene_to_contract(scene) for scene in scenes]

    async def get_scene_spans_by_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
        *,
        status_filter: list[str] | None = None,
        content_mode: str = "canonical",
    ) -> list[SceneSpanContract]:
        nid = parse_uuid(novel_id, "novel_id")
        statuses = tuple(status_filter or ["draft", "canonical"])
        spans = await self.repo.get_scene_spans_by_chapter(
            db,
            nid,
            chapter_index,
            statuses=statuses,
            content_mode=content_mode,
        )
        return [scene_span_to_contract(span) for span in spans]

    async def get_scene_spans_for_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
        *,
        status_filter: list[str] | None = None,
        content_mode: str = "canonical",
    ) -> list[SceneSpanContract]:
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(scene_id, "scene_id")
        statuses = tuple(status_filter) if status_filter is not None else None
        spans = await self.repo.get_scene_spans_for_scene(
            db,
            nid,
            sid,
            statuses=statuses,
            content_mode=content_mode,
        )
        return [scene_span_to_contract(span) for span in spans]

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
        await self.repo.sync_scene_indexes(db, source_scene)
        if tid:
            await self.repo.sync_scene_indexes(db, target)
        else:
            await self.repo.sync_scene_indexes(db, new_scene)

        # 返回更新后的 scenes
        scenes = await self.repo.get_by_novel_ordered(db, nid)
        return [scene_to_contract(scene) for scene in scenes]

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
        await db.flush()

        await self.repo.shift_scene_indices_after(
            db,
            nid,
            source.scene_index,
            exclude_ids={source.id, new_scene.id},
        )
        await self.repo.sync_scene_indexes(db, source)
        await self.repo.sync_scene_indexes(db, new_scene)

        scenes = await self.repo.get_by_novel_ordered(db, nid)
        return list(scenes)


class OutlineStructureCleanupService:
    """Owns cleanup rules for auto-ingested outline structure assets."""

    async def deprecate_deep_import_structure_assets_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        nid = parse_uuid(novel_id, "novel_id")
        deprecated = 0
        for model in (PlotThread, OutlineArc, ForeshadowingPlan, RevealPlan):
            stmt = select(model).where(
                model.novel_id == nid,
                model.status.in_(["candidate", "proposal", "draft", "canonical"]),
                model.provenance_meta["source"].as_string() == "deep_import",
                model.provenance_meta["workflow_id"].as_string() == workflow_id,
                model.provenance_meta["auto_ingested"].as_boolean().is_(True),
                model.provenance_meta["user_edited"].as_boolean().is_not(True),
            )
            result = await db.execute(stmt)
            assets = result.scalars().all()
            for asset in assets:
                meta = asset.provenance_meta or {}
                if not _is_cleanup_eligible_deep_import_meta(meta, workflow_id):
                    continue
                updated_meta = {
                    **meta,
                    "cleanup_status": "deprecated",
                    "cleanup_reason": "abandoned_deep_import_recovery",
                }
                asset.status = "deprecated"
                asset.provenance_meta = updated_meta
                db.add(asset)
                deprecated += 1

        if deprecated:
            await db.flush()
        return deprecated


__all__ = [
    "PlotThreadService",
    "OutlineArcService",
    "ForeshadowingPlanService",
    "RevealPlanService",
    "SceneService",
    "OutlineStructureCleanupService",
    "scene_to_contract",
]


def __getattr__(name: str) -> type:
    """懒加载兼容：PlotStructureGenerator 实际位于 modules.outline.generator。"""
    if name == "PlotStructureGenerator":
        from modules.outline.generator import PlotStructureGenerator as _Generator

        return _Generator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
