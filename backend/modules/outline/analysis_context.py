"""Read-only chapter-range projection for manual outline analysis."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.contracts import OutlineAnalysisContextContract
from modules.outline.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    SceneChapterLink,
)
from modules.outline.repositories import SceneRepository
from shared.utils import parse_uuid

_ACTIVE_STRUCTURE_STATUSES = ("draft", "canonical")


class OutlineAnalysisContextService:
    """Build the exact structure package shown in AI reference confirmation."""

    def __init__(self, scene_repository: SceneRepository | None = None) -> None:
        self._scenes = scene_repository or SceneRepository()

    async def get_range(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        start_chapter: int,
        end_chapter: int,
    ) -> OutlineAnalysisContextContract:
        if start_chapter < 1 or end_chapter < start_chapter:
            raise ValueError("outline analysis chapter range is invalid")
        nid = parse_uuid(novel_id, "novel_id")

        scenes = await self._scenes.get_by_chapter_range(
            db,
            nid,
            start_chapter,
            end_chapter,
            statuses=_ACTIVE_STRUCTURE_STATUSES,
        )
        scene_chapters = await self._scene_chapters(db, nid, scenes)
        arcs = list(
            (
                await db.execute(
                    select(OutlineArc)
                    .where(
                        OutlineArc.novel_id == nid,
                        OutlineArc.status.in_(_ACTIVE_STRUCTURE_STATUSES),
                        or_(
                            OutlineArc.start_chapter.is_not(None),
                            OutlineArc.end_chapter.is_not(None),
                        ),
                        or_(
                            OutlineArc.start_chapter.is_(None),
                            OutlineArc.start_chapter <= end_chapter,
                        ),
                        or_(
                            OutlineArc.end_chapter.is_(None),
                            OutlineArc.end_chapter >= start_chapter,
                        ),
                    )
                    .order_by(OutlineArc.arc_index, OutlineArc.id)
                )
            )
            .scalars()
            .all()
        )
        foreshadowing = [
            item
            for item in (
                (
                    await db.execute(
                        select(ForeshadowingPlan)
                        .where(
                            ForeshadowingPlan.novel_id == nid,
                            ForeshadowingPlan.status.notin_(
                                ("deprecated", "abandoned")
                            ),
                        )
                        .order_by(
                            ForeshadowingPlan.planned_seed_chapter,
                            ForeshadowingPlan.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if _foreshadowing_overlaps(item, start_chapter, end_chapter)
        ]
        reveal_candidates = list(
            (
                await db.execute(
                    select(RevealPlan)
                    .where(
                        RevealPlan.novel_id == nid,
                        RevealPlan.status.notin_(("deprecated", "abandoned")),
                    )
                    .order_by(RevealPlan.created_at, RevealPlan.id)
                )
            )
            .scalars()
            .all()
        )

        scene_items = [
            _scene_payload(scene, scene_chapters.get(str(scene.id), []))
            for scene in scenes
        ]
        arc_items = [_arc_payload(item) for item in arcs]
        foreshadowing_items = [_foreshadowing_payload(item) for item in foreshadowing]
        directly_related_thread_ids = _uuid_values(
            _related_values(
                scene_items,
                arc_items,
                foreshadowing_items,
                keys=("related_thread_ids",),
            )
        )
        threads = list(
            (
                await db.execute(
                    select(PlotThread)
                    .where(
                        PlotThread.novel_id == nid,
                        PlotThread.status.in_(_ACTIVE_STRUCTURE_STATUSES),
                        or_(
                            *(
                                [PlotThread.id.in_(directly_related_thread_ids)]
                                if directly_related_thread_ids
                                else []
                            ),
                            (
                                or_(
                                    PlotThread.start_chapter.is_not(None),
                                    PlotThread.planned_payoff_chapter.is_not(None),
                                )
                                & (
                                    or_(
                                        PlotThread.start_chapter.is_(None),
                                        PlotThread.start_chapter <= end_chapter,
                                    )
                                    & or_(
                                        PlotThread.planned_payoff_chapter.is_(None),
                                        PlotThread.planned_payoff_chapter
                                        >= start_chapter,
                                    )
                                )
                            ),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        threads.sort(
            key=lambda item: (
                item.start_chapter is None,
                item.start_chapter or 0,
                item.name or "",
                str(item.id),
            )
        )
        thread_items = [_thread_payload(item) for item in threads]
        base_character_ids = _unique_ids(
            _related_values(
                scene_items,
                arc_items,
                thread_items,
                keys=(
                    "pov_character_id",
                    "related_character_ids",
                    "present_character_ids",
                    "character_ids",
                ),
            )
        )
        base_entity_ids = _unique_ids(
            _related_values(
                scene_items,
                arc_items,
                thread_items,
                foreshadowing_items,
                keys=("related_entity_ids",),
            )
        )
        involved_target_ids = {*base_character_ids, *base_entity_ids}
        reveals = [
            item
            for item in reveal_candidates
            if _reveal_overlaps(item, start_chapter, end_chapter)
            or str(item.target_id or "") in involved_target_ids
        ]
        reveal_items = [_reveal_payload(item) for item in reveals]
        related_character_ids = _unique_ids(
            [
                *base_character_ids,
                *(
                    str(item["target_id"])
                    for item in reveal_items
                    if item.get("target_type") == "character"
                ),
            ]
        )
        related_entity_ids = _unique_ids(
            [
                *base_entity_ids,
                *(
                    str(item["target_id"])
                    for item in reveal_items
                    if item.get("target_type") != "character"
                ),
            ]
        )
        return OutlineAnalysisContextContract(
            novel_id=str(nid),
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            scenes=scene_items,
            arcs=arc_items,
            plot_threads=thread_items,
            foreshadowing_plans=foreshadowing_items,
            reveal_plans=reveal_items,
            related_character_ids=related_character_ids,
            related_entity_ids=related_entity_ids,
        )

    @staticmethod
    async def _scene_chapters(
        db: AsyncSession,
        novel_id: uuid.UUID,
        scenes: list[Any],
    ) -> dict[str, list[int]]:
        scene_ids = [scene.id for scene in scenes]
        if not scene_ids:
            return {}
        rows = (
            await db.execute(
                select(SceneChapterLink.scene_id, SceneChapterLink.chapter_index)
                .where(
                    SceneChapterLink.novel_id == novel_id,
                    SceneChapterLink.scene_id.in_(scene_ids),
                )
                .order_by(
                    SceneChapterLink.chapter_index,
                    SceneChapterLink.scene_id,
                )
            )
        ).all()
        result: dict[str, list[int]] = {}
        for scene_id, chapter_index in rows:
            result.setdefault(str(scene_id), []).append(int(chapter_index))
        return result


def _scene_payload(scene: Any, linked_chapters: list[int]) -> dict[str, Any]:
    structure_meta = dict(scene.structure_meta or {})
    chapter_indices = linked_chapters or _chapter_indices(
        scene.scene_chunks or [],
        scene.chapter_ids or [],
    )
    return {
        "id": str(scene.id),
        "scene_index": scene.scene_index,
        "chapter_indices": chapter_indices,
        "title": scene.title,
        "goal": scene.goal,
        "core_conflict": scene.core_conflict,
        "emotional_beat": scene.emotional_beat,
        "must_happen": scene.must_happen,
        "must_not_happen": scene.must_not_happen,
        "narrative_tag": scene.narrative_tag,
        "pov_character_id": scene.pov_character_id,
        "related_character_ids": list(
            structure_meta.get("related_character_ids") or []
        ),
        "present_character_ids": list(
            structure_meta.get("present_character_ids") or []
        ),
        "character_ids": list(structure_meta.get("character_ids") or []),
        "related_entity_ids": list(structure_meta.get("related_entity_ids") or []),
        "related_thread_ids": list(structure_meta.get("related_thread_ids") or []),
        "status": scene.status,
    }


def _arc_payload(item: OutlineArc) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "title": item.title,
        "arc_index": item.arc_index,
        "start_chapter": item.start_chapter,
        "end_chapter": item.end_chapter,
        "arc_goal": item.arc_goal,
        "core_conflict": item.core_conflict,
        "main_opposition": item.main_opposition,
        "entry_hook": item.entry_hook,
        "midpoint_turn": item.midpoint_turn,
        "climax": item.climax,
        "result": item.result,
        "next_hook": item.next_hook,
        "related_thread_ids": list(item.related_thread_ids or []),
        "related_character_ids": list(item.related_character_ids or []),
        "related_entity_ids": list(item.related_entity_ids or []),
        "status": item.status,
    }


def _thread_payload(item: PlotThread) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "name": item.name,
        "thread_type": item.thread_type,
        "summary": item.summary,
        "visible_goal": item.visible_goal,
        "hidden_truth": item.hidden_truth,
        "start_chapter": item.start_chapter,
        "planned_payoff_chapter": item.planned_payoff_chapter,
        "current_stage": item.current_stage,
        "related_character_ids": list(item.related_character_ids or []),
        "related_entity_ids": list(item.related_entity_ids or []),
        "reader_known_state": item.reader_known_state,
        "author_known_state": item.author_known_state,
        "status": item.status,
    }


def _foreshadowing_payload(item: ForeshadowingPlan) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "name": item.name,
        "summary": item.summary,
        "surface_meaning": item.surface_meaning,
        "hidden_meaning": item.hidden_meaning,
        "planned_seed_chapter": item.planned_seed_chapter,
        "planned_reinforce_chapters": list(item.planned_reinforce_chapters or []),
        "planned_payoff_chapter": item.planned_payoff_chapter,
        "planned_payoff_scene": item.planned_payoff_scene,
        "related_entity_ids": list(item.related_entity_ids or []),
        "related_thread_ids": list(item.related_thread_ids or []),
        "status": item.status,
    }


def _reveal_payload(item: RevealPlan) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "target_type": item.target_type,
        "target_id": str(item.target_id or ""),
        "secret_summary": item.secret_summary,
        "reveal_stages": list(item.reveal_stages or []),
        "status": item.status,
    }


def _foreshadowing_overlaps(
    item: ForeshadowingPlan,
    start_chapter: int,
    end_chapter: int,
) -> bool:
    points = [
        item.planned_seed_chapter,
        item.planned_payoff_chapter,
        *(item.planned_reinforce_chapters or []),
    ]
    if any(_chapter_in_range(value, start_chapter, end_chapter) for value in points):
        return True
    seed = _as_int(item.planned_seed_chapter)
    payoff = _as_int(item.planned_payoff_chapter)
    return seed is not None and seed <= end_chapter and (
        payoff is None or payoff >= start_chapter
    )


def _reveal_overlaps(
    item: RevealPlan,
    start_chapter: int,
    end_chapter: int,
) -> bool:
    chapters = [
        chapter
        for chapter in (
            _as_int(stage.get("chapter_index"))
            for stage in item.reveal_stages or []
            if isinstance(stage, dict)
        )
        if chapter is not None
    ]
    return bool(
        chapters
        and min(chapters) <= end_chapter
        and max(chapters) >= start_chapter
    )


def _chapter_indices(chunks: list[Any], chapter_ids: list[Any]) -> list[int]:
    values: list[Any] = []
    for chunk in chunks:
        if isinstance(chunk, dict):
            values.append(chunk.get("chapter_index"))
    values.extend(chapter_ids)
    return sorted(
        {
            chapter
            for chapter in (_as_int(value) for value in values)
            if chapter is not None
        }
    )


def _chapter_in_range(value: Any, start_chapter: int, end_chapter: int) -> bool:
    chapter = _as_int(value)
    return chapter is not None and start_chapter <= chapter <= end_chapter


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _related_values(*groups: list[dict], keys: tuple[str, ...]) -> Iterable[Any]:
    for group in groups:
        for item in group:
            for key in keys:
                value = item.get(key)
                if isinstance(value, list | tuple | set):
                    yield from value
                elif value:
                    yield value


def _unique_ids(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item_id = str(value or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item_id)
    return result


def _uuid_values(values: Iterable[Any]) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for value in values:
        try:
            item_id = uuid.UUID(str(value))
        except (AttributeError, TypeError, ValueError):
            continue
        if item_id in seen:
            continue
        seen.add(item_id)
        result.append(item_id)
    return result
