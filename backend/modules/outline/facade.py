"""
Outline Facade — 对外入口

其他模块只能从 facade 导入 outline 功能。
Facade 不写复杂业务逻辑，只做薄层转发。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.contracts import SceneContract

# ============================================================
# Scene
# ============================================================


async def get_scene(db: AsyncSession, scene_id: str) -> dict[str, Any] | None:
    """按 ID 获取 Scene，返回 dict 或 None。"""
    from modules.outline.repositories import SceneRepository
    from shared.utils import parse_uuid

    sid = parse_uuid(scene_id, "scene_id")
    scene = await SceneRepository().get(db, sid)
    if scene is None:
        return None
    return _scene_to_dict(scene)


async def get_scene_contract(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
) -> SceneContract | None:
    """按 novel + ID 获取 SceneContract，供其他模块跨 seam 使用。"""
    from fastapi import HTTPException

    from modules.outline.services import SceneService

    try:
        scene = await SceneService().get(db, scene_id, novel_id=novel_id)
    except HTTPException:
        return None
    return _scene_to_contract(scene)


async def get_scenes_by_novel(
    db: AsyncSession,
    novel_id: str,
    *,
    status_filter: list[str] | None = None,
    exclude_narrative_tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """获取 novel 的所有 Scene（按 scene_index 排序），支持过滤。"""
    from modules.outline.repositories import SceneRepository
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    repo = SceneRepository()
    scenes = await repo.get_by_novel_ordered(db, nid)
    result = []
    for s in scenes:
        if status_filter and s.status not in status_filter:
            continue
        if exclude_narrative_tags and s.narrative_tag in exclude_narrative_tags:
            continue
        result.append(_scene_to_dict(s))
    return result


async def get_scenes_by_provenance_key(
    db: AsyncSession,
    novel_id: str,
    provenance_key: str,
) -> list[dict[str, Any]]:
    """按 deep import provenance_key 获取 Scene，包含 deprecated。"""
    from modules.outline.repositories import SceneRepository
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    scenes = await SceneRepository().get_by_provenance_key(
        db,
        nid,
        provenance_key,
    )
    return [_scene_to_dict(scene) for scene in scenes]


async def count_scenes_by_novel(
    db: AsyncSession,
    novel_id: str,
    *,
    status_filter: list[str] | None = None,
) -> int:
    """统计 novel 的 Scene 数量。"""
    from sqlalchemy import func, select

    from modules.outline.models import Scene
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    conditions = [Scene.novel_id == nid]
    if status_filter:
        conditions.append(Scene.status.in_(status_filter))
    stmt = select(func.count(Scene.id)).where(*conditions)
    result = await db.execute(stmt)
    return result.scalar() or 0


async def create_scene(
    db: AsyncSession,
    novel_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """创建单个 Scene，返回 dict。"""
    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    scene_data = SceneCreate(**data)
    scene = await SceneRepository().create(db, nid, scene_data)
    return _scene_to_dict(scene)


async def batch_create_scenes(
    db: AsyncSession,
    novel_id: str,
    scenes_data: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """批量创建 Scene，返回 dict 列表。"""
    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    repo = SceneRepository()
    results = []
    for data in scenes_data:
        scene_data = SceneCreate(**data)
        scene = await repo.create(db, nid, scene_data)
        results.append(_scene_to_dict(scene))
    return results


async def update_scene(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """更新 Scene 字段（仅允许 status 等少量字段），返回 dict 或 None。"""
    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneUpdate
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    sid = parse_uuid(scene_id, "scene_id")
    repo = SceneRepository()
    scene = await repo.get(db, sid)
    if scene is None or scene.novel_id != nid:
        return None
    update_data = SceneUpdate(**data)
    updated = await repo.update(db, sid, update_data)
    if updated is None:
        return None
    return _scene_to_dict(updated)


async def get_next_scene_index(db: AsyncSession, novel_id: str) -> int:
    """获取该 novel 的下一个 scene_index（当前最大 + 1）。"""
    from sqlalchemy import func, select

    from modules.outline.models import Scene
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    stmt = select(func.coalesce(func.max(Scene.scene_index), -1)).where(
        Scene.novel_id == nid,
    )
    result = await db.execute(stmt)
    return (result.scalar() or -1) + 1


async def split_scene_chunk_to_new_chapter(
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
) -> list[dict[str, Any]]:
    from modules.outline.services import SceneService

    scenes = await SceneService().split_scene_chunk_to_new_chapter(
        db,
        novel_id=novel_id,
        source_scene_id=source_scene_id,
        source_chapter_id=source_chapter_id,
        source_chapter_index=source_chapter_index,
        new_chapter_id=new_chapter_id,
        new_chapter_index=new_chapter_index,
        split_pos=split_pos,
        new_chapter_length=new_chapter_length,
    )
    return [_scene_to_dict(scene) for scene in scenes]


async def suggest_structure_dedup(
    db: AsyncSession,
    novel_id: str,
    *,
    asset_types: list[str] | None = None,
    limit: int = 1000,
    max_suggestions: int = 80,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Generate outline-owned duplicate suggestions without writing assets."""
    from modules.outline.structure_dedup import OutlineStructureDedupService

    return await OutlineStructureDedupService().suggest(
        db,
        novel_id=novel_id,
        asset_types=asset_types,
        limit=limit,
        max_suggestions=max_suggestions,
        progress_callback=progress_callback,
    )


async def apply_structure_dedup(
    db: AsyncSession,
    novel_id: str,
    *,
    confirmed: bool,
    suggestions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply user-confirmed outline duplicate suggestions."""
    from modules.outline.structure_dedup import OutlineStructureDedupService

    return await OutlineStructureDedupService().apply(
        db,
        novel_id=novel_id,
        confirmed=confirmed,
        suggestions=suggestions,
    )


async def deprecate_deep_import_scenes_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Soft-deprecate auto-ingested Scenes created by one deep import workflow."""
    from sqlalchemy import select, update

    from modules.outline.models import Scene
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    stmt = select(Scene).where(
        Scene.novel_id == nid,
        Scene.status.in_(["candidate", "proposal", "draft", "canonical"]),
    )
    result = await db.execute(stmt)
    scenes = result.scalars().all()

    deprecated = 0
    for scene in scenes:
        meta = scene.structure_meta or {}
        if scene.source != "deep_import" or not _is_cleanup_eligible_deep_import_meta(
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
        await db.execute(
            update(Scene)
            .where(Scene.id == scene.id, Scene.novel_id == nid)
            .values(status="deprecated", structure_meta=updated_meta)
        )
        deprecated += 1

    if deprecated:
        await db.flush()
    return deprecated


async def deprecate_deep_import_structure_assets_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Soft-deprecate outline structure assets from one deep import workflow."""
    from sqlalchemy import select, update

    from modules.outline.models import (
        ForeshadowingPlan,
        OutlineArc,
        PlotThread,
        RevealPlan,
    )
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    deprecated = 0
    for model in (PlotThread, OutlineArc, ForeshadowingPlan, RevealPlan):
        stmt = select(model).where(
            model.novel_id == nid,
            model.status.in_(["candidate", "proposal", "draft", "canonical"]),
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
            await db.execute(
                update(model)
                .where(model.id == asset.id, model.novel_id == nid)
                .values(status="deprecated", provenance_meta=updated_meta)
            )
            deprecated += 1

    if deprecated:
        await db.flush()
    return deprecated


# ============================================================
# ForeshadowingPlan
# ============================================================


async def get_active_foreshadowing(
    db: AsyncSession,
    novel_id: str,
    *,
    status: str = "seeded",
) -> list[dict[str, Any]]:
    """获取活跃伏笔计划列表，返回 dict 列表。"""
    from sqlalchemy import select

    from modules.outline.models import ForeshadowingPlan
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    stmt = select(ForeshadowingPlan).where(
        ForeshadowingPlan.novel_id == nid,
        ForeshadowingPlan.status == status,
    )
    result = await db.execute(stmt)
    plans = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "novel_id": str(p.novel_id),
            "name": p.name,
            "summary": p.summary,
            "surface_meaning": p.surface_meaning,
            "hidden_meaning": p.hidden_meaning,
            "status": p.status,
            "planned_seed_chapter": p.planned_seed_chapter,
            "planned_payoff_chapter": p.planned_payoff_chapter,
            "planned_payoff_scene": p.planned_payoff_scene,
            "planned_reinforce_chapters": p.planned_reinforce_chapters or [],
            "related_entity_ids": p.related_entity_ids or [],
            "related_thread_ids": p.related_thread_ids or [],
        }
        for p in plans
    ]


# ============================================================
# Helpers
# ============================================================


def _scene_to_dict(scene) -> dict[str, Any]:
    """将 Scene ORM 对象转为普通 dict（不暴露 ORM 对象给外部模块）。"""
    return {
        "id": str(scene.id),
        "novel_id": str(scene.novel_id),
        "scene_index": scene.scene_index,
        "title": scene.title,
        "goal": scene.goal,
        "core_conflict": scene.core_conflict,
        "emotional_beat": scene.emotional_beat,
        "must_happen": scene.must_happen,
        "must_not_happen": scene.must_not_happen,
        "narrative_tag": scene.narrative_tag,
        "source": scene.source,
        "scene_chunks": scene.scene_chunks or [],
        "chapter_ids": scene.chapter_ids or [],
        "pov_character_id": scene.pov_character_id,
        "structure_meta": scene.structure_meta or {},
        "status": scene.status,
    }


def _scene_to_contract(scene) -> SceneContract:
    """将 Scene ORM/response 对象转为稳定跨模块 contract。"""
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
