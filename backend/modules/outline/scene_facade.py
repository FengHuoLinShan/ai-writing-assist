"""Outline Scene Facade — Scene seam for cross-module callers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.outline.contracts import (
    NeighborSceneBriefContract,
    SceneContextWindowContract,
    SceneContract,
    SceneSpanContract,
    SceneSpanCoverageContract,
)


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


async def get_scene_spans_by_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    *,
    status_filter: list[str] | None = None,
    content_mode: str = "canonical",
) -> list[SceneSpanContract]:
    """获取指定章节的 SceneSpan 派生读模型。"""
    from modules.outline.services import SceneService

    return await SceneService().get_scene_spans_by_chapter(
        db,
        novel_id,
        chapter_index,
        status_filter=status_filter,
        content_mode=content_mode,
    )


async def get_scene_spans_for_scene(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
    *,
    status_filter: list[str] | None = None,
    content_mode: str = "canonical",
) -> list[SceneSpanContract]:
    """获取指定 Scene 的 SceneSpan 派生读模型。"""
    from modules.outline.services import SceneService

    return await SceneService().get_scene_spans_for_scene(
        db,
        novel_id,
        scene_id,
        status_filter=status_filter,
        content_mode=content_mode,
    )


async def get_scene_span_coverage(
    db: AsyncSession,
    novel_id: str,
    *,
    content_mode: str = "canonical",
) -> SceneSpanCoverageContract:
    """Return Scene/SceneSpan location coverage for cross-module health checks."""
    from modules.outline.scene_coverage import SceneSpanCoverageService

    return await SceneSpanCoverageService().get_coverage(
        db,
        novel_id,
        content_mode=content_mode,
    )


async def get_scene_context_window(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
    *,
    previous_limit: int = 2,
    status_filter: list[str] | None = None,
    content_mode: str = "canonical",
) -> SceneContextWindowContract | None:
    """Return the current Scene and prior-only briefs for context compilation."""
    scene = await get_scene_contract(db, novel_id, scene_id)
    if scene is None:
        return None
    allowed_statuses = status_filter or ["canonical", "draft"]
    scenes = await get_scenes_by_novel(
        db,
        novel_id,
        status_filter=allowed_statuses,
    )
    previous = [
        item for item in scenes if int(item.get("scene_index") or 0) < scene.scene_index
    ]
    previous = previous[-max(0, min(previous_limit, 4)) :]
    briefs = [
        NeighborSceneBriefContract(
            scene_id=str(item["id"]),
            novel_id=str(item["novel_id"]),
            scene_index=int(item["scene_index"]),
            title=item.get("title"),
            goal=item.get("goal"),
            core_conflict=item.get("core_conflict"),
            emotional_beat=item.get("emotional_beat"),
            chapter_indices=[
                int(value)
                for value in item.get("chapter_ids") or []
                if str(value).isdigit()
            ],
            scene_chunks=list(item.get("scene_chunks") or []),
        )
        for item in previous
    ]
    spans = await get_scene_spans_for_scene(
        db,
        novel_id,
        scene_id,
        status_filter=allowed_statuses,
        content_mode=content_mode,
    )
    return SceneContextWindowContract(
        novel_id=novel_id,
        scene=scene,
        scene_spans=spans,
        previous_briefs=briefs,
    )


async def bind_scene_spans_to_source(
    db: AsyncSession,
    *,
    novel_id: str,
    chapter_index: int,
    content_mode: str,
    source_draft_id: str,
    source_content_hash: str,
    content: str,
) -> list[SceneSpanContract]:
    from modules.outline.scene_source_service import SceneSourceService

    return await SceneSourceService().bind_chapter_spans(
        db,
        novel_id=novel_id,
        chapter_index=chapter_index,
        content_mode=content_mode,
        source_draft_id=source_draft_id,
        source_content_hash=source_content_hash,
        content=content,
    )


async def get_scene_summary_checkpoint(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str,
    content_mode: str,
    through_chapter: int,
    through_offset: int | None = None,
):
    from modules.outline.scene_source_service import SceneSourceService

    return await SceneSourceService().get_checkpoint(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        content_mode=content_mode,
        through_chapter=through_chapter,
        through_offset=through_offset,
    )


async def rebuild_scene_summary_checkpoint(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str,
    content_mode: str,
    through_chapter: int,
    through_offset: int | None = None,
):
    from modules.outline.scene_source_service import SceneSourceService

    return await SceneSourceService().rebuild_checkpoint(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        content_mode=content_mode,
        through_chapter=through_chapter,
        through_offset=through_offset,
    )


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
    from modules.outline.services import scene_to_contract

    return scene_to_contract(scene)


__all__ = [
    "bind_scene_spans_to_source",
    "batch_create_scenes",
    "count_scenes_by_novel",
    "create_scene",
    "get_next_scene_index",
    "get_scene",
    "get_scene_contract",
    "get_scene_context_window",
    "get_scene_summary_checkpoint",
    "get_scene_spans_by_chapter",
    "get_scene_spans_for_scene",
    "get_scene_span_coverage",
    "get_scenes_by_chapter",
    "get_scenes_by_novel",
    "get_scenes_by_provenance_key",
    "get_scenes_by_provenance_keys",
    "rebuild_scene_summary_checkpoint",
    "split_scene_chunk_to_new_chapter",
    "update_scene",
]
