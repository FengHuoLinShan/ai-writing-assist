"""Map-owned confirmed operations; no generated coordinates or new geography."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ConflictError
from modules.assistant.contracts import AssistantOperation
from modules.world.map_structure_schemas import (
    MapDocument,
    MapFeature,
    MapNodeCreate,
    MapRevisionReview,
    MapSaveRequest,
)
from modules.world.map_structure_service import MapStructureService


class ReviewMapRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: UUID
    revision_id: UUID
    base_revision_id: UUID | None
    action: Literal["adopt", "reject", "restore"] = "adopt"


class AddKnownLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: UUID
    entity_id: UUID


class EditFeatureLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: UUID
    feature_id: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


async def _document(db, novel_id, node_id, context):
    from modules.assistant.facade import require_operation_targets

    await require_operation_targets(
        db, novel_id, context, [("map_atlas_node", node_id)], aggregate=True
    )
    if context.work.scope == "current" and (
        context.work.chapter_index or context.work.scene_id
    ):
        raise ConflictError("请从地图工作台核对整个空间版本后再修改")
    service = MapStructureService()
    node = await service.node(db, novel_id, str(node_id))
    current = (
        await service.revision(db, novel_id, str(node_id), node.current_revision_id)
        if node.current_revision_id
        else None
    )
    return (
        service,
        node,
        MapDocument.model_validate(current.document) if current else MapDocument(),
    )


async def _location_preview(db, novel_id, args, *, context=None):
    from modules.world.services.core.entity_service import WorldEntityService

    _, node, document = await _document(db, novel_id, args.node_id, context)
    entity = await WorldEntityService().get(db, str(args.entity_id), novel_id=novel_id)
    if entity.status != "canonical" or entity.entity_type != "location":
        raise ConflictError("只能把本作品已采用的地点加入地图")
    if any(feature.entity_id == args.entity_id for feature in document.features):
        raise ConflictError("这个地点已经在当前地图中，可定位查看")
    document.features.append(
        MapFeature(
            id=f"loc:{args.entity_id}",
            kind="location",
            label=entity.name,
            entity_id=args.entity_id,
            points=[],
        )
    )
    return {
        "target_key": f"map:{node.id}",
        "title": f"把{entity.name}加入{node.title}",
        "base_revision_id": str(node.current_revision_id)
        if node.current_revision_id
        else None,
        "entity_updated_at": str(entity.updated_at),
        "document": document.model_dump(mode="json"),
        "after": {"name": entity.name, "note": "位置尚未确定，保留空白"},
        "effect": "只加入已知地点，不推测坐标、地形或路线；保存为可恢复的新空间版本",
    }


async def _feature_preview(db, novel_id, args, *, context=None):
    _, node, document = await _document(db, novel_id, args.node_id, context)
    feature = next(
        (item for item in document.features if item.id == args.feature_id), None
    )
    if feature is None or (args.label is None and args.note is None):
        raise ConflictError("请指定现有图元及实际要修改的名称或备注")
    before = {"name": feature.label, "note": feature.note}
    if args.label is not None:
        feature.label = args.label
    if args.note is not None:
        feature.note = args.note
    return {
        "target_key": f"map:{node.id}",
        "title": f"修改{node.title}的图元说明",
        "base_revision_id": str(node.current_revision_id)
        if node.current_revision_id
        else None,
        "document": document.model_dump(mode="json"),
        "before": before,
        "after": {"name": feature.label, "note": feature.note},
        "effect": "只改名称和备注，保留坐标、来源、校准及已锁定位置；可从版本历史恢复",
    }


async def _save_document(db, novel_id, args, preview, *, context=None):
    prepare = (
        _location_preview if isinstance(args, AddKnownLocation) else _feature_preview
    )
    if await prepare(db, novel_id, args, context=context) != preview:
        raise ConflictError("地图或关联地点已变化，请重新查看方案")
    result = await MapStructureService().save(
        db,
        novel_id,
        str(args.node_id),
        MapSaveRequest(
            base_revision_id=preview["base_revision_id"],
            document=MapDocument.model_validate(preview["document"]),
        ),
    )
    return {
        "type": "map_atlas_node",
        "id": str(args.node_id),
        "revision_id": str(result.id),
        "label": "已保存新的空间版本",
    }


async def _node_preview(db, novel_id, args, *, context=None):
    from modules.assistant.facade import require_operation_targets

    await require_operation_targets(
        db,
        novel_id,
        context,
        [
            (kind, key)
            for kind, key in [
                ("map_atlas_node", args.parent_id),
                ("core_entity", args.location_entity_id),
            ]
            if key
        ],
    )
    service = MapStructureService()
    if args.parent_id:
        await service.node(db, novel_id, str(args.parent_id))
    if args.location_entity_id:
        from modules.world.services.core.entity_service import WorldEntityService

        await WorldEntityService().get(
            db, str(args.location_entity_id), novel_id=novel_id
        )
    return {
        "title": args.title,
        "after": {"title": args.title, "level": args.level},
        "effect": "创建空白地图节点，不生成地形、坐标或世界事实",
    }


async def _node_apply(db, novel_id, args, preview, *, context=None):
    row = await MapStructureService().create_node(db, novel_id, args)
    return {"type": "map_atlas_node", "id": str(row["id"]), "label": "已创建空白地图"}


async def _review_preview(db, novel_id, args, *, context=None):
    from modules.assistant.facade import require_operation_targets

    await require_operation_targets(
        db, novel_id, context, [("map_atlas_node", args.node_id)], aggregate=True
    )
    service = MapStructureService()
    node = await service.node(db, novel_id, str(args.node_id))
    if node.current_revision_id != args.base_revision_id:
        raise ConflictError("地图版本已变化", code="assistant_source_stale")
    result = (
        (
            await service.review_preview(
                db,
                novel_id,
                str(args.node_id),
                str(args.revision_id),
                MapRevisionReview(
                    base_revision_id=args.base_revision_id, action=args.action
                ),
            )
        )
        if args.action == "adopt"
        else (
            await service.preview_revision(
                db, novel_id, str(args.node_id), str(args.revision_id)
            )
        )
    )
    return {
        "target_key": f"map:{node.id}",
        "title": node.title,
        "base_revision_id": str(node.current_revision_id)
        if node.current_revision_id
        else None,
        "changes": result.model_dump(mode="json")
        if hasattr(result, "model_dump")
        else result,
        "effect": "按地图原有版本与来源门禁处理此版本，不改写世界事实",
    }


async def _review_apply(db, novel_id, args, preview, *, context=None):
    if await _review_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("地图版本已变化", code="assistant_source_stale")
    result = await MapStructureService().review(
        db,
        novel_id,
        str(args.node_id),
        str(args.revision_id),
        MapRevisionReview(base_revision_id=args.base_revision_id, action=args.action),
    )
    return {
        "type": "map_atlas_node",
        "id": str(args.node_id),
        "label": "已处理地图版本",
        "result": result.model_dump(mode="json")
        if hasattr(result, "model_dump")
        else result,
    }


OPERATIONS = {
    "map.add_known_location": AssistantOperation(
        "把已知地点加入地图（保留未知位置）",
        AddKnownLocation,
        _location_preview,
        _save_document,
    ),
    "map.edit_feature_label": AssistantOperation(
        "修改图元名称或备注", EditFeatureLabel, _feature_preview, _save_document
    ),
    "map.create_node": AssistantOperation(
        "创建空白地图", MapNodeCreate, _node_preview, _node_apply
    ),
    "map.review_revision": AssistantOperation(
        "处理已有地图版本", ReviewMapRevision, _review_preview, _review_apply
    ),
}
