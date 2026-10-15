"""Story owns open questions, conditional reactions and information windows."""

import json

from modules.world.contracts import MapSpatialBriefRequest

INSTRUCTIONS = {
    ("story.open_question.v1"): (
        "先找可回读的异常、未完成承诺或因果疑问，再给竞争解释。问题有依据不表示任何解释为真；普通遗物或情感细节不"
        "必变成秘密，也不要求回收。"
    ),
    ("story.character_response.v1"): (
        "只依据所提供的人物资料和已观察刺激提出动机不同的反应。资料缺失保持未知；性格不决定唯一行动，意图不等于成"
        "功事件。"
    ),
    "story.scene_transition.v1": (
        "考虑当前结果到下一场的最小过渡、直接切场或继"
        "续留白，不重排场景。没有下一场安排时给条件式"
        "选择。"
    ),
    ("story.information_window.v1"): (
        "结合已登记计划与当前可回读变化讨论轻量回应、发展或继续潜伏。不编造回收章号，不将唯一已知渠道当成唯一可能"
        "渠道。"
    ),
    "story.spatial_planning.v1": (
        "以已采用、已揭示的地图和行程为参考，提示检查旅程分段、地点集中与可能的空间转场。"
        "地图未覆盖不代表地点或道路不存在；没有尺度时不推算距离与耗时。"
    ),
}


def _spatial_planning_fact(scene, brief) -> dict | None:
    items = list(getattr(brief, "items", None) or [])
    if not items:
        return None
    revisions = []
    journey_count = 0
    location_count = 0
    for item in items[:5]:
        try:
            content = json.loads(str(getattr(item, "content", "")))
        except (TypeError, ValueError):
            continue
        if not isinstance(content, dict) or not content.get("当前地点"):
            continue
        revisions.append(
            {
                "node_id": str(getattr(item, "node_id", "")),
                "revision_id": str(getattr(item, "revision_id", "")),
                "revision_hash": str(getattr(item, "revision_hash", "")),
                "source_hashes": list(getattr(item, "source_hashes", []) or [])[:32],
                "current_locations": content.get("当前地点", [])[:10],
                "connections": content.get("邻接与通路", [])[:20],
                "journeys": content.get("行程与通行条件", [])[:20],
            }
        )
        location_count += len(content.get("当前地点", []) or [])
        journey_count += len(content.get("行程与通行条件", []) or [])
    if not revisions:
        return None
    angle = "旅程分段" if journey_count else "地点分布与转场"
    return {
        "capability_id": "story.spatial_planning.v1",
        "subject": str(scene.id),
        "title": "核对本场的地理视角",
        "summary": (
            f"可结合当前已标注的 {location_count} 处地点与 {journey_count} 条行程，"
            f"检查{angle}是否服务剧情节奏。"
        ),
        "source": {"scene_id": str(scene.id), "map_revisions": revisions},
        "scope_label": "本场显式地点相关的已采用地图与行程",
        "unknowns": [
            "地图未覆盖不代表地点或路线不存在。",
            "地图没有真实比例，不据此推算距离或耗时。",
            "当前没有势力边界资料，因此不判断接壤冲突机会。",
        ],
        "target": {"page": "scene", "scene_id": str(scene.id)},
    }


async def inspect(db, novel_id, focus, excluded):
    from uuid import UUID

    from sqlalchemy import select

    from modules.story.facade import get_scene_story_assets
    from modules.story.outline_state.models import Scene

    if not focus.scene_id or excluded:
        return []
    scene = await db.scalar(
        select(Scene).where(Scene.novel_id == UUID(novel_id), Scene.id == focus.scene_id)
    )
    if scene is None:
        return []
    assets = await get_scene_story_assets(db, novel_id=novel_id, scene_id=str(scene.id))
    value = assets.model_dump(mode="json") if hasattr(assets, "model_dump") else assets
    # 纯数据事实（AO-5）：assistant 消费侧以 ForecastDomainFact.model_validate
    # 物化并校验，字段语义与原模型构造一致。
    facts = [
        {
            "capability_id": "story.structure_impact.v1",
            "subject": str(scene.id),
            "title": "场景调整后，先核对原文连接",
            "summary": (
                "这些章节与场景片段是当前明确的结构连接；调整信息顺序前可逐处核对。"
            ),
            "source": {
                "scene_id": str(scene.id),
                "chapter_ids": scene.chapter_ids or [],
                "scene_chunks": scene.scene_chunks or [],
                "updated_at": str(scene.updated_at),
            },
            "scope_label": "当前场景的显式章节映射",
            "unknowns": [
                "未以相邻场景或文字相似推断因果，尚未复核调整后的读者信息顺序。"
            ],
            "target": {"page": "scene", "scene_id": str(scene.id)},
        },
        {
            "capability_id": "writing.recall_pack.v1",
            "subject": str(scene.id),
            "title": "本场已有剧本与人物卡",
            "summary": "已采用的场景资料可作为接续前的检查清单，仍需按本次写作范围确认。",
            "source": {"scene_id": str(scene.id), "assets": value},
            "scope_label": "当前场景采用的故事资料",
            "target": {"page": "scene", "scene_id": str(scene.id)},
        },
    ]
    if (
        focus.page in {"outline", "scene"}
        and "story.spatial_planning" in _enabled_map_spatial_capabilities()
    ):
        spatial_fact = await _read_spatial_planning_fact(db, novel_id, scene)
        if spatial_fact is not None:
            facts.append(spatial_fact)
    return facts


def _enabled_map_spatial_capabilities() -> set[str]:
    from core.config import get_settings

    return set(get_settings().map_spatial_enabled_capabilities)


async def _read_spatial_planning_fact(db, novel_id, scene):
    from core.container import get
    from core.service_keys import WORLD_READ_MAP_SPATIAL_BRIEF

    brief = await get(WORLD_READ_MAP_SPATIAL_BRIEF)(
        db,
        MapSpatialBriefRequest(
            novel_id=str(novel_id),
            scene_id=str(scene.id),
            reveal_mode="author_safe",
            limit=5,
        ),
    )
    return _spatial_planning_fact(scene, brief)
