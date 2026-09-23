"""Read-only map consumer of Story presence; no independent location state."""

from sqlalchemy import select

from core.errors import NotFoundError
from infrastructure.llm.collaboration import content_hash
from modules.story.facade import project_scene_presence
from modules.story.outline_state.facade import get_scene_contract
from modules.world.map_structure_schemas import MapPresenceItem, MapSceneContext
from modules.world.map_structure_service import MapStructureService
from modules.world.models import CoreEntity
from shared.utils import parse_uuid


async def get_scene_context(db, novel_id, node_id, scene_id):
    map_view = await MapStructureService().get_map(db, novel_id, node_id)
    scene = await get_scene_contract(db, novel_id, str(scene_id))
    if scene is None or scene.status not in {"draft", "canonical"}:
        raise NotFoundError("场景不在当前作品的可用范围内")
    report = await project_scene_presence(
        db, novel_id, through_scene_index=scene.scene_index
    )
    characters = list(
        (
            await db.scalars(
                select(CoreEntity)
                .where(
                    CoreEntity.novel_id == parse_uuid(novel_id, "novel_id"),
                    CoreEntity.entity_type == "character",
                    CoreEntity.status.in_(["draft", "canonical"]),
                )
                .order_by(CoreEntity.name, CoreEntity.id)
                .limit(201)
            )
        ).all()
    )
    names = {str(value.id): value.name for value in characters[:200]}
    revision = map_view.revision
    stale_features = {
        feature
        for problem in (revision.problems if revision else [])
        if problem.code == "source_stale"
        for feature in problem.feature_ids
    }
    features, identity_features = {}, {}
    for feature in revision.document.features if revision else []:
        if feature.kind in {"location", "landmark", "area"}:
            features.setdefault(feature.label, []).append(feature)
            if feature.entity_id:
                identity_features.setdefault(str(feature.entity_id), []).append(feature)

    def item(node):
        matches = (
            identity_features.get(node.location_id, [])
            if node.location_id
            else features.get(node.location, [])
        )
        feature = matches[0] if len(matches) == 1 else None
        if feature and feature.entity_id and not node.location_id:
            feature = None
        return MapPresenceItem(
            character_id=node.character_id,
            character_name=names[node.character_id],
            presence_kind=node.presence_kind,
            location=node.location,
            location_id=node.location_id,
            feature_id=feature.id
            if feature and feature.points and feature.id not in stale_features
            else None,
            scene_index=node.scene_index,
            source_receipt=node.source_receipt,
        )

    nodes = sorted(
        (value for value in report.nodes if value.character_id in names),
        key=lambda value: (value.scene_index, value.character_id),
    )
    latest = {value.character_id: value for value in nodes}
    presence = [
        item(latest[identity])
        if identity in latest
        else MapPresenceItem(
            character_id=identity, character_name=name, presence_kind="unknown"
        )
        for identity, name in names.items()
    ]
    routes = [
        value.model_dump() for value in report.segments if value.character_id in names
    ]
    receipts = [value.source_receipt for value in nodes]
    omissions = [
        "只展示已有场景事件中的位置；没有位置记录的角色保持未知。",
        "同名地点有歧义、地图来源已变化或尚未定位时，只列文字，不放置位置点。",
    ]
    if len(nodes) > 200 or len(routes) > 200 or len(characters) > 200:
        omissions.append(
            "仅展示最近 200 个历史节点、200 段关系及前 200 名人物，未覆盖全部记录。"
        )
    scene_ref = {
        "id": scene.id,
        "scene_index": scene.scene_index,
        "title": scene.title or f"场景 {scene.scene_index + 1}",
        "chapter_ids": scene.chapter_ids,
    }
    return MapSceneContext(
        scene_ref=scene_ref,
        map_revision=revision.id if revision else None,
        presence_items=presence,
        history=[item(value) for value in nodes[-200:]],
        routes=routes[-200:],
        source_receipts=[value.source_receipt for value in nodes[-200:]],
        coverage={
            "characters": len(names),
            "located": sum(bool(value.feature_id) for value in presence),
            "history_nodes": len(nodes),
            "complete": len(characters) <= 200
            and len(nodes) <= 200
            and len(routes) <= 200,
            "semantic_exhaustive": False,
        },
        omissions=omissions,
        unsupported_dimensions=[
            "item_custody",
            "world_valid_time",
            "character_view",
            "reader_view",
        ],
        freshness="partial" if stale_features else "current",
        generation_stamp=content_hash(
            {
                "scene": scene_ref,
                "map": revision.model_dump(mode="json") if revision else None,
                "events": receipts,
                "characters": names,
            }
        ),
        request_context_id=content_hash(
            {
                "novel_id": novel_id,
                "node_id": node_id,
                "scene_id": scene.id,
                "view": "author",
            }
        ),
    )
