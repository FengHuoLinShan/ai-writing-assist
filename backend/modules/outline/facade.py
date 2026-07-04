"""
Outline Facade — 对外入口

其他模块只能从 facade 导入 outline 功能。
Facade 不写复杂业务逻辑，只做薄层转发。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
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
    from modules.outline.services import SceneService

    try:
        scene = await SceneService().get(db, scene_id, novel_id=novel_id)
    except NotFoundError:
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
    from modules.outline.services import SceneService

    scenes = await SceneService().get_ordered_models(
        db,
        novel_id,
        status_filter=status_filter,
        exclude_narrative_tags=exclude_narrative_tags,
    )
    return [_scene_to_dict(scene) for scene in scenes]


async def get_scenes_by_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> list[dict[str, Any]]:
    """获取指定章节相关 Scene（按 scene_index 排序）。"""
    from modules.outline.services import SceneService

    scenes = await SceneService().get_by_chapter_models(
        db,
        novel_id,
        chapter_index,
    )
    return [_scene_to_dict(scene) for scene in scenes]


async def get_scenes_by_provenance_key(
    db: AsyncSession,
    novel_id: str,
    provenance_key: str,
) -> list[dict[str, Any]]:
    """按 deep import provenance_key 获取 Scene，包含 deprecated。"""
    from modules.outline.services import SceneService

    scenes = await SceneService().get_by_provenance_key_models(
        db,
        novel_id,
        provenance_key,
    )
    return [_scene_to_dict(scene) for scene in scenes]


async def get_scenes_by_provenance_keys(
    db: AsyncSession,
    novel_id: str,
    provenance_keys: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """按 deep import provenance_key 批量获取 Scene，包含 deprecated。"""
    from modules.outline.services import SceneService

    unique_keys = list(dict.fromkeys(key for key in provenance_keys if key))
    scenes = await SceneService().get_by_provenance_keys_models(
        db,
        novel_id,
        unique_keys,
    )
    grouped = {key: [] for key in unique_keys}
    for scene in scenes:
        key = (scene.structure_meta or {}).get("provenance_key")
        if key in grouped:
            grouped[key].append(_scene_to_dict(scene))
    return grouped


async def count_scenes_by_novel(
    db: AsyncSession,
    novel_id: str,
    *,
    status_filter: list[str] | None = None,
) -> int:
    """统计 novel 的 Scene 数量。"""
    from modules.outline.services import SceneService

    return await SceneService().count_by_novel(
        db,
        novel_id,
        status_filter=status_filter,
    )


async def create_scene(
    db: AsyncSession,
    novel_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """创建单个 Scene，返回 dict。"""
    from modules.outline.services import SceneService

    scene = await SceneService().create_model_from_dict(db, novel_id, data)
    return _scene_to_dict(scene)


async def batch_create_scenes(
    db: AsyncSession,
    novel_id: str,
    scenes_data: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """批量创建 Scene，返回 dict 列表。"""
    from modules.outline.services import SceneService

    scenes = await SceneService().batch_create_models_from_dicts(
        db,
        novel_id,
        scenes_data,
    )
    return [_scene_to_dict(scene) for scene in scenes]


async def update_scene(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    """更新 Scene 字段（仅允许 status 等少量字段），返回 dict 或 None。"""
    from modules.outline.services import SceneService

    updated = await SceneService().update_model_from_dict(
        db,
        novel_id,
        scene_id,
        data,
    )
    if updated is None:
        return None
    return _scene_to_dict(updated)


async def get_next_scene_index(db: AsyncSession, novel_id: str) -> int:
    """获取该 novel 的下一个 scene_index（当前最大 + 1）。"""
    from modules.outline.services import SceneService

    return await SceneService().get_next_scene_index(db, novel_id)


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
    from modules.outline.services import SceneService

    return await SceneService().deprecate_deep_import_scenes_by_workflow(
        db,
        novel_id,
        workflow_id,
    )


async def deprecate_deep_import_structure_assets_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Soft-deprecate outline structure assets from one deep import workflow."""
    from modules.outline.services import OutlineStructureCleanupService

    return await (
        OutlineStructureCleanupService().deprecate_deep_import_structure_assets_by_workflow(
            db,
            novel_id,
            workflow_id,
        )
    )


async def reindex_scenes_for_deep_import_repair(
    db: AsyncSession,
    novel_id: str,
) -> int:
    """Reorder Scenes by chapter membership for deterministic deep-import display."""
    from modules.outline.deep_import_repair_service import (
        OutlineDeepImportRepairService,
    )

    return await OutlineDeepImportRepairService().reindex_scenes(db, novel_id)


async def get_deep_import_structure_counts(
    db: AsyncSession,
    novel_id: str,
) -> dict[str, int]:
    """Count outline-owned structure assets for deep-import display repair."""
    from modules.outline.deep_import_repair_service import (
        OutlineDeepImportRepairService,
    )

    return await OutlineDeepImportRepairService().structure_counts(db, novel_id)


async def get_deep_import_structure_payload(
    db: AsyncSession,
    novel_id: str,
) -> dict[str, Any]:
    """Return the structure-analysis payload shape consumed by import fallback logic."""
    from modules.outline.deep_import_repair_service import (
        OutlineDeepImportRepairService,
    )

    return await OutlineDeepImportRepairService().structure_payload(db, novel_id)


async def ensure_deep_import_structure_outputs(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    result: dict[str, Any],
    *,
    workflow_id: str | None,
    service_resolver: Any | None = None,
    small_sample_target_count: int | None = None,
) -> dict[str, Any]:
    from modules.outline.deep_import_repair_service import (
        SMALL_SAMPLE_STRUCTURE_TARGET_COUNT,
        OutlineDeepImportRepairService,
    )

    list_entities_func = None
    if service_resolver is not None:
        try:
            list_entities_func = service_resolver("world.list_entities")
        except KeyError:
            list_entities_func = None

    return await OutlineDeepImportRepairService(
        service_resolver=service_resolver,
        list_entities=list_entities_func,
    ).ensure_minimum_structure_outputs(
        db,
        novel_id,
        start_chapter,
        end_chapter,
        result,
        workflow_id=workflow_id,
        small_sample_target_count=(
            small_sample_target_count or SMALL_SAMPLE_STRUCTURE_TARGET_COUNT
        ),
    )


def get_deep_import_structure_category_targets(
    chapter_count: int,
    *,
    small_sample_target_count: int,
) -> dict[str, int]:
    from modules.outline.deep_import_repair_service import (
        minimum_structure_category_targets,
    )

    return minimum_structure_category_targets(
        chapter_count,
        small_sample_target_count=small_sample_target_count,
    )


def get_deep_import_structure_category_counts(
    result: dict[str, Any],
) -> dict[str, int]:
    from modules.outline.deep_import_repair_service import structure_category_counts

    return structure_category_counts(result)


def get_deep_import_structure_output_count(result: dict[str, Any]) -> int:
    from modules.outline.deep_import_repair_service import structure_output_count

    return structure_output_count(result)


def get_deep_import_fallback_thread_type(index: int) -> str:
    from modules.outline.deep_import_repair_service import fallback_thread_type

    return fallback_thread_type(index)


async def ensure_deep_import_structure_minimums(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    workflow_id: str | None,
) -> dict[str, int]:
    """Ensure outline structure minimums for repaired deep-import runs."""
    from modules.outline.deep_import_repair_service import (
        OutlineDeepImportRepairService,
    )

    return await OutlineDeepImportRepairService().ensure_structure_minimum_counts(
        db,
        novel_id,
        start_chapter,
        end_chapter,
        workflow_id=workflow_id,
    )


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
