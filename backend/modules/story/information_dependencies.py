"""Explicit chapter/Scene mappings used by script baselines and change checks."""

import hashlib
import json
from collections import defaultdict

from sqlalchemy import select

from modules.story.outline_state.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
    SceneChapterLink,
)


def _overlaps(row, chapters):
    start = row.start_chapter
    end = row.planned_payoff_chapter if isinstance(row, PlotThread) else row.end_chapter
    return (
        type(start) is int
        and (type(end) is int or isinstance(row, PlotThread) and end is None)
        and any(
            start <= chapter and (end is None or chapter <= end) for chapter in chapters
        )
    )


def _plan_matches(plan, chapters, scene_index, threads):
    if isinstance(plan, ForeshadowingPlan):
        direct = [
            plan.planned_seed_chapter,
            plan.planned_payoff_chapter,
            *(plan.planned_reinforce_chapters or []),
        ]
        if (
            plan.planned_payoff_scene is not None
            and plan.planned_payoff_scene == scene_index
        ):
            return True
    else:
        direct = [
            stage.get("chapter_index")
            for stage in plan.reveal_stages or []
            if isinstance(stage, dict)
        ]
    return bool(
        chapters.intersection(value for value in direct if type(value) is int)
    ) or any(
        str(thread.id) in {str(value) for value in plan.related_thread_ids or []}
        and _overlaps(thread, chapters)
        for thread in threads
    )


async def affected_structure_scenes(db, novel_id, plan):
    threads = list(
        (
            await db.scalars(
                select(PlotThread).where(
                    PlotThread.novel_id == novel_id, PlotThread.status != "deprecated"
                )
            )
        ).all()
    )
    chapters = defaultdict(set)
    for sid, chapter in (
        await db.execute(
            select(SceneChapterLink.scene_id, SceneChapterLink.chapter_index).where(
                SceneChapterLink.novel_id == novel_id
            )
        )
    ).all():
        chapters[sid].add(chapter)
    return [
        sid
        for sid, index in (
            await db.execute(
                select(Scene.id, Scene.scene_index).where(
                    Scene.novel_id == novel_id, Scene.status != "deprecated"
                )
            )
        ).all()
        if (
            _overlaps(plan, chapters[sid])
            if isinstance(plan, PlotThread | OutlineArc)
            else _plan_matches(plan, chapters[sid], index, threads)
        )
    ]


async def script_information_basis(db, novel_id, scene_id):
    chapters = set(
        (
            await db.scalars(
                select(SceneChapterLink.chapter_index).where(
                    SceneChapterLink.novel_id == novel_id,
                    SceneChapterLink.scene_id == scene_id,
                )
            )
        ).all()
    )
    scene_index = await db.scalar(
        select(Scene.scene_index).where(Scene.novel_id == novel_id, Scene.id == scene_id)
    )
    threads = list(
        (
            await db.scalars(
                select(PlotThread).where(
                    PlotThread.novel_id == novel_id, PlotThread.status != "deprecated"
                )
            )
        ).all()
    )
    selected = [thread for thread in threads if _overlaps(thread, chapters)]
    # ponytail: O(project plans) metadata reads preserve exact JSON membership on
    # SQLite/PostgreSQL. Normalize these links if large-project latency warrants it.
    for model in (OutlineArc, ForeshadowingPlan, RevealPlan):
        for row in (
            await db.scalars(
                select(model).where(
                    model.novel_id == novel_id, model.status != "deprecated"
                )
            )
        ).all():
            if (
                _overlaps(row, chapters)
                if model is OutlineArc
                else _plan_matches(row, chapters, scene_index, threads)
            ):
                selected.append(row)
    return sorted(
        [
            {
                "type": row.__tablename__.removesuffix("s"),
                "id": str(row.id),
                "hash": hashlib.sha256(
                    json.dumps(
                        {
                            column.name: getattr(row, column.name)
                            for column in row.__table__.columns
                            if column.name
                            not in {"created_at", "updated_at", "provenance_meta"}
                        },
                        sort_keys=True,
                        ensure_ascii=False,
                        default=str,
                    ).encode()
                ).hexdigest(),
            }
            for row in selected
        ],
        key=lambda value: (value["type"], value["id"]),
    )


async def capture_change_scenes(db, row):
    from core.config import get_settings

    if row is None or not get_settings().assistant_enabled:
        return []
    return await affected_structure_scenes(db, row.novel_id, row)
