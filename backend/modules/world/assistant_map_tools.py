"""Map-owned confirmed operations; no generated coordinates or new geography."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from core.container import get
from core.errors import ConflictError, ValidationError
from core.service_keys import (
    ASSISTANT_READ_MAP_AUTHOR_DECISION,
    ASSISTANT_REQUIRE_OPERATION_TARGETS,
)
from infrastructure.stable_hash import stable_hash
from modules.world.map_atlas_models import MapAtlasNode
from modules.world.map_atlas_schemas import MapAtlasNodeUpdate
from modules.world.map_atlas_service import MapAtlasService
from modules.world.map_auto_draft_service import list_map_auto_drafts
from modules.world.map_spatial_clue_schemas import (
    MapSpatialClueDecisionRequest,
)
from modules.world.map_spatial_clue_service import (
    list_spatial_clues,
    review_spatial_clue,
)
from modules.world.map_structure_schemas import (
    MapDocument,
    MapFeature,
    MapNodeCreate,
    MapRevisionReview,
    MapSaveRequest,
    MapSpace,
    SpatialAccessCondition,
    SpatialConstraint,
    SpatialJourney,
    SpatialQuantityRange,
    SpatialValidity,
)
from modules.world.map_structure_service import MapStructureService
from modules.world.project_vocabulary_service import resolve_vocabulary_type_revisions
from shared.observation import ObservationModality


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


class SpatialClueDecisionSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote: str = Field(min_length=1, max_length=2000)
    scene_index: int | None = Field(default=None, ge=0)
    action: Literal["adopt", "reject", "merge"]
    target_quote: str | None = Field(default=None, min_length=1, max_length=2000)
    target_scene_index: int | None = Field(default=None, ge=0)
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def merge_target(self):
        if (self.action == "merge") != (self.target_quote is not None):
            raise ValueError("合并线索需要且仅能指定目标引文")
        if self.target_quote is None and self.target_scene_index is not None:
            raise ValueError("只有合并操作可以指定目标场景")
        return self


class ReviewSpatialClues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[SpatialClueDecisionSelector] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_sources(self):
        keys = [(item.quote.strip(), item.scene_index) for item in self.decisions]
        if len(keys) != len(set(keys)):
            raise ValueError("同一批次不能重复处理同一条引文")
        return self


class ReviewAutoDraftGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_kind: Literal["hierarchy", "space"]
    scope_id: str = Field(min_length=1, max_length=96)
    action: Literal["adopt", "reject"]


class AssistantSpaceArrangement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=96)
    label: str = Field(min_length=1, max_length=200)
    type_ref: UUID | None = None
    type_revision_id: UUID | None = None


class AssistantConstraintArrangement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=96)
    subject: str = Field(min_length=1, max_length=96)
    relation: str = Field(min_length=1, max_length=96)
    target: str = Field(min_length=1, max_length=96)
    via: list[str] = Field(default_factory=list, max_length=30)
    path_kind: Literal["road", "river"] = "road"
    path_label: str | None = Field(default=None, min_length=1, max_length=200)
    path_type_ref: UUID | None = None
    path_type_revision_id: UUID | None = None
    type_ref: UUID | None = None
    type_revision_id: UUID | None = None
    modality: ObservationModality = "event_observed"
    effective: SpatialValidity | None = None


class AssistantJourneyArrangement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=96)
    origin: str = Field(min_length=1, max_length=96)
    destination: str = Field(min_length=1, max_length=96)
    transport_label: str = Field(min_length=1, max_length=200)
    transport_type_ref: UUID | None = None
    transport_type_revision_id: UUID | None = None
    traveler_type_ref: UUID | None = None
    traveler_type_revision_id: UUID | None = None
    connection_type_ref: UUID | None = None
    connection_type_revision_id: UUID | None = None
    duration: SpatialQuantityRange | None = None
    distance: SpatialQuantityRange | None = None
    access_conditions: list[SpatialAccessCondition] = Field(
        default_factory=list, max_length=30
    )
    modality: ObservationModality = "event_observed"
    effective: SpatialValidity | None = None


class MapStructureEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "add_space",
        "rename_space",
        "remove_space",
        "upsert_constraint",
        "remove_constraint",
        "upsert_journey",
        "remove_journey",
    ]
    target_id: str | None = Field(default=None, min_length=1, max_length=96)
    space: AssistantSpaceArrangement | None = None
    constraint: AssistantConstraintArrangement | None = None
    journey: AssistantJourneyArrangement | None = None

    @model_validator(mode="after")
    def payload_matches_kind(self):
        payloads = {
            "space": self.space,
            "constraint": self.constraint,
            "journey": self.journey,
        }
        expected = (
            "space"
            if self.kind in {"add_space", "rename_space", "remove_space"}
            else "constraint"
            if self.kind in {"upsert_constraint", "remove_constraint"}
            else "journey"
        )
        if any(value is not None for key, value in payloads.items() if key != expected):
            raise ValueError("编辑参数与操作类型不匹配")
        needs_payload = self.kind in {
            "add_space",
            "rename_space",
            "upsert_constraint",
            "upsert_journey",
        }
        if (payloads[expected] is not None) != needs_payload:
            raise ValueError("该地图编辑缺少对应的结构数据")
        if (
            self.kind
            in {
                "rename_space",
                "remove_space",
                "remove_constraint",
                "remove_journey",
            }
            and not self.target_id
        ):
            raise ValueError("该地图编辑需要指定现有项目")
        if self.kind == "rename_space" and self.space and self.space.id != self.target_id:
            raise ValueError("改名参数必须引用同一个空间")
        if self.kind in {"add_space", "upsert_constraint", "upsert_journey"} and (
            self.target_id
        ):
            raise ValueError("新增或更新数据请在结构对象中指定身份")
        return self


class EditMapStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: UUID
    base_revision_id: UUID | None
    edits: list[MapStructureEdit] = Field(min_length=1, max_length=20)


class UpdateMapNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: UUID
    update: MapAtlasNodeUpdate


async def _document(db, novel_id, node_id, context):
    require_operation_targets = get(ASSISTANT_REQUIRE_OPERATION_TARGETS)
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
    require_operation_targets = get(ASSISTANT_REQUIRE_OPERATION_TARGETS)
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
    level_type = None
    type_ref = getattr(args, "level_type_ref", None)
    revision_id = getattr(args, "level_type_revision_id", None)
    if type_ref is not None:
        types = await resolve_vocabulary_type_revisions(
            db, novel_id, {(type_ref, revision_id)}
        )
        pinned = types[(type_ref, revision_id)]
        if pinned["kind"] != "level":
            raise ValidationError("地图层级必须引用层级类型")
        level_type = {
            "type_ref": str(type_ref),
            "type_revision_id": str(revision_id),
            "name": pinned["name"],
            "description": pinned["description"],
            "status": pinned["status"],
        }
    return {
        "title": args.title,
        "after": {
            "title": args.title,
            "level": args.level,
            **({"level_type": level_type} if level_type else {}),
        },
        "effect": "创建空白地图节点，不生成地形、坐标或世界事实",
    }


async def _node_apply(db, novel_id, args, preview, *, context=None):
    row = await MapStructureService().create_node(db, novel_id, args)
    return {"type": "map_atlas_node", "id": str(row["id"]), "label": "已创建空白地图"}


async def _review_preview(db, novel_id, args, *, context=None):
    require_operation_targets = get(ASSISTANT_REQUIRE_OPERATION_TARGETS)
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


def _require_workbench_scope(context):
    if (
        context is not None
        and context.work.scope == "current"
        and (context.work.chapter_index or context.work.scene_id)
    ):
        raise ConflictError("请从地图工作台按完整空间范围审核")


async def _require_aggregate_scope(db, novel_id, context):
    require_targets = get(ASSISTANT_REQUIRE_OPERATION_TARGETS)
    await require_targets(db, novel_id, context, [], aggregate=True)


def _select_clue(clues, quote, scene_index):
    matches = [
        item
        for item in clues
        if item.quote == quote.strip()
        and (scene_index is None or item.scene_index == scene_index)
    ]
    if len(matches) != 1:
        raise ConflictError(
            "引文无法唯一定位到一条空间线索，请补充场景位置或到审核队列选择"
        )
    return matches[0]


async def _clue_review_preview(db, novel_id, args, *, context=None):
    _require_workbench_scope(context)
    await _require_aggregate_scope(db, novel_id, context)
    page = await list_spatial_clues(
        db,
        novel_id,
        statuses=["pending_review", "pending_verification", "adopted"],
        limit=200,
        offset=0,
    )
    if page.total_count > len(page.items):
        raise ConflictError("待审空间线索过多，请先在地图审核工作台缩小范围")
    decisions = []
    selected_ids = set()
    for selector in args.decisions:
        source = _select_clue(page.items, selector.quote, selector.scene_index)
        if selector.action == "adopt" and source.status != "pending_review":
            raise ConflictError("待核线索不能直接采用，请先完成来源核查")
        if source.id in selected_ids:
            raise ConflictError("同一批次不能重复处理同一条空间线索")
        selected_ids.add(source.id)
        target = None
        if selector.action == "merge":
            target = _select_clue(
                page.items, selector.target_quote, selector.target_scene_index
            )
            if target.id == source.id:
                raise ConflictError("不能把空间线索合并到自身")
        decisions.append(
            {
                "clue_id": str(source.id),
                "quote": source.quote,
                "scene_index": source.scene_index,
                "status": source.status,
                "fingerprint": source.fingerprint,
                "action": selector.action,
                "reason": selector.reason,
                "target_clue_id": str(target.id) if target else None,
                "target_quote": target.quote if target else None,
                "target_scene_index": target.scene_index if target else None,
                "target_fingerprint": target.fingerprint if target else None,
            }
        )
    return {
        "target_keys": [f"spatial-clue:{item['clue_id']}" for item in decisions],
        "affected_count": len(decisions),
        "decision_fingerprint": stable_hash(decisions),
        "decisions": decisions,
        "effect": "逐条核对引文并采用、拒绝或合并线索；不会直接修改正式地图",
    }


async def _clue_review_apply(db, novel_id, args, preview, *, context=None):
    if await _clue_review_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("空间线索或原文来源已变化，请重新准备审核")
    results = []
    for item in preview["decisions"]:
        result = await review_spatial_clue(
            db,
            novel_id,
            item["clue_id"],
            MapSpatialClueDecisionRequest(
                action=item["action"],
                expected_fingerprint=item["fingerprint"],
                confirmed=True,
                target_clue_id=item["target_clue_id"],
                target_fingerprint=item["target_fingerprint"],
                reason=item["reason"],
            ),
            decided_by=context.owner_id if context else "author",
        )
        results.append(
            {
                "quote": result.quote,
                "status": result.status,
                "merged_into": str(result.merged_into_id)
                if result.merged_into_id
                else None,
            }
        )
    return {"type": "map_spatial_clues", "results": results}


def _item_space_ids(key, item, documents):
    spaces_by_feature = {
        feature.id: feature.space_id
        for document in documents
        for feature in document.features
    }
    if key.startswith("space:"):
        return {key.removeprefix("space:")}
    if key.startswith("feature:"):
        return {item.space_id}
    if key.startswith(("constraint:", "journey:")):
        endpoints = (
            {item.subject, item.target, *item.via}
            if key.startswith("constraint:")
            else {item.origin, item.destination}
        )
        return {
            spaces_by_feature[name] for name in endpoints if name in spaces_by_feature
        }
    if key.startswith("image:"):
        feature_ids = {anchor.feature_id for anchor in item.anchors}
        if item.feature_id:
            feature_ids.add(item.feature_id)
        return {
            spaces_by_feature[name] for name in feature_ids if name in spaces_by_feature
        }
    if key.startswith("binding:"):
        return (
            {spaces_by_feature[item.feature_id]}
            if item.feature_id in spaces_by_feature
            else set()
        )
    return set()


async def _auto_draft_group_preview(db, novel_id, args, *, context=None):
    _require_workbench_scope(context)
    await _require_aggregate_scope(db, novel_id, context)
    page = await list_map_auto_drafts(db, novel_id, limit=200, offset=0)
    if page.truncated or page.batches_truncated:
        raise ConflictError("自动草图过多，请先在地图工作台缩小审核范围")
    nodes = list(
        (
            await db.scalars(
                select(MapAtlasNode).where(
                    MapAtlasNode.novel_id == UUID(novel_id),
                    MapAtlasNode.status == "adopted",
                )
            )
        ).all()
    )
    if args.scope_kind == "hierarchy":
        root = await MapStructureService().node(db, novel_id, args.scope_id)
        node_ids = {root.id}
        changed = True
        while changed:
            descendants = {item.id for item in nodes if item.parent_id in node_ids}
            changed = not descendants.issubset(node_ids)
            node_ids.update(descendants)
        scoped = [item for item in page.items if item.node_id in node_ids]
    else:
        scoped = [
            item
            for item in page.items
            if any(
                feature.space_id == args.scope_id for feature in item.document.features
            )
        ]
    candidates = [item for item in scoped if item.status == "candidate"]
    if not candidates:
        raise ConflictError("这个空间或层级没有待审自动草图")
    if any(item.stale or item.warnings for item in candidates):
        raise ConflictError("草图有失效来源或未完成分片，请到地图工作台核对")
    require_targets = get(ASSISTANT_REQUIRE_OPERATION_TARGETS)
    await require_targets(
        db,
        novel_id,
        context,
        [("map_atlas_node", item.node_id) for item in candidates],
        aggregate=True,
    )
    service = MapStructureService()
    manifest = [
        {
            "node_id": str(item.node_id),
            "revision_id": str(item.revision_id),
            "review_base_revision_id": str(item.review_base_revision_id)
            if item.review_base_revision_id
            else None,
            "batch_id": str(item.batch_id),
            "batch_fingerprint": item.fingerprint,
            "source_clue_ids": [str(value) for value in item.source_clue_ids],
        }
        for item in candidates
    ]
    decisions, affected = [], 0
    for item in candidates:
        node = await service.node(db, novel_id, str(item.node_id))
        if node.current_revision_id != item.review_base_revision_id:
            raise ConflictError("正式地图版本已变化，请重新比较草图")
        baseline = (
            MapDocument.model_validate(
                (
                    await service.revision(
                        db, novel_id, str(node.id), node.current_revision_id
                    )
                ).document
            )
            if node.current_revision_id
            else MapDocument()
        )
        candidate = MapDocument.model_validate(item.document)
        from modules.world.map_structure_review import changed_items, document_items

        old_items, new_items = document_items(baseline), document_items(candidate)
        all_keys = changed_items(baseline, candidate)
        selected_keys = (
            sorted(all_keys)
            if args.scope_kind == "hierarchy"
            else sorted(
                key
                for key in all_keys
                if args.scope_id
                in _item_space_ids(
                    key, new_items.get(key) or old_items.get(key), [baseline, candidate]
                )
            )
        )
        if not selected_keys:
            continue
        decision_preview = None
        if args.action == "adopt":
            decision_preview = await service.review_preview(
                db,
                novel_id,
                str(node.id),
                str(item.revision_id),
                MapRevisionReview(
                    base_revision_id=item.review_base_revision_id,
                    action="adopt",
                    change_keys=selected_keys,
                ),
            )
            count = len(
                set(decision_preview.applied_change_keys)
                | set(decision_preview.expanded_change_keys)
            )
        else:
            await service.preview_revision(
                db, novel_id, str(node.id), str(item.revision_id)
            )
            count = 1
        affected += count
        decisions.append(
            {
                "node_id": str(item.node_id),
                "revision_id": str(item.revision_id),
                "base_revision_id": str(item.review_base_revision_id)
                if item.review_base_revision_id
                else None,
                "action": args.action,
                "change_keys": selected_keys,
                "expanded_change_keys": decision_preview.expanded_change_keys
                if decision_preview
                else [],
                "affected_count": count,
                "title": item.node_title,
            }
        )
    if not decisions:
        raise ConflictError("所选空间或层级没有可审核的实际地图项目")
    if affected > 20:
        raise ConflictError("本次会涉及超过 20 个地图项目，请拆分到更小范围")
    return {
        "target_keys": [f"map:{item['node_id']}" for item in decisions],
        "affected_count": affected,
        "group_fingerprint": stable_hash(manifest),
        "revision_manifest": manifest,
        "decisions": decisions,
        "effect": "对完整版本基线做分批审核；地图正式版本仍按各节点 CAS 保存",
    }


async def _auto_draft_group_apply(db, novel_id, args, preview, *, context=None):
    if await _auto_draft_group_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("草图、线索或正式地图版本已变化，请重新准备审核")
    service = MapStructureService()
    results = []
    for item in preview["decisions"]:
        result = await service.review(
            db,
            novel_id,
            item["node_id"],
            item["revision_id"],
            MapRevisionReview(
                base_revision_id=item["base_revision_id"],
                action=item["action"],
                change_keys=item["change_keys"] if item["action"] == "adopt" else None,
            ),
        )
        results.append(
            {
                "node_title": item["title"],
                "status": result.status,
                "revision_id": result.id,
            }
        )
    return {"type": "map_auto_draft_group", "results": results}


async def _read_author_decision(db, novel_id, context):
    if context is None or not context.run_id:
        raise ConflictError("作者安排需要绑定到本次助手运行")
    frozen = (context.internal_meta or {}).get("prepared_preview") or {}
    frozen_decision = frozen.get("author_decision") or {}
    reader = get(ASSISTANT_READ_MAP_AUTHOR_DECISION)
    return await reader(
        db,
        novel_id,
        context.run_id,
        message_id=frozen_decision.get("message_id"),
    )


async def _structure_edit_preview(db, novel_id, args, *, context=None):
    service, node, document = await _document(db, novel_id, args.node_id, context)
    if node.current_revision_id != args.base_revision_id:
        raise ConflictError("地图版本已变化，请重新读取当前空间")
    document = document.model_copy(deep=True)
    arranged_journeys = [edit for edit in args.edits if edit.kind == "upsert_journey"]
    author_decision = (
        await _read_author_decision(db, novel_id, context) if arranged_journeys else None
    )
    before = document.model_dump(mode="json")
    for edit in args.edits:
        if edit.kind == "add_space":
            if any(space.id == edit.space.id for space in document.spaces):
                raise ConflictError("这个空间已经存在")
            document.spaces.append(MapSpace(**edit.space.model_dump()))
        elif edit.kind == "rename_space":
            space = next(
                (item for item in document.spaces if item.id == edit.target_id), None
            )
            if space is None:
                raise ConflictError("没有找到要改名的空间")
            space.label = edit.space.label if edit.space else space.label
        elif edit.kind == "remove_space":
            if edit.target_id == "main":
                raise ConflictError("主空间不能移除")
            if not any(space.id == edit.target_id for space in document.spaces):
                raise ConflictError("没有找到要移除的空间")
            if any(feature.space_id == edit.target_id for feature in document.features):
                raise ConflictError("该空间仍包含地点，请先移动或处理地点")
            document.spaces = [
                item for item in document.spaces if item.id != edit.target_id
            ]
        elif edit.kind == "upsert_constraint":
            constraint = SpatialConstraint(**edit.constraint.model_dump())
            document.constraints = [
                item for item in document.constraints if item.id != constraint.id
            ] + [constraint]
        elif edit.kind == "remove_constraint":
            if not any(item.id == edit.target_id for item in document.constraints):
                raise ConflictError("没有找到要移除的空间关系")
            document.constraints = [
                item for item in document.constraints if item.id != edit.target_id
            ]
        elif edit.kind == "upsert_journey":
            journey = SpatialJourney(
                **edit.journey.model_dump(),
                sources=[],
                author_decision=author_decision,
            )
            document.journeys = [
                item for item in document.journeys if item.id != journey.id
            ] + [journey]
        elif edit.kind == "remove_journey":
            if not any(item.id == edit.target_id for item in document.journeys):
                raise ConflictError("没有找到要移除的行程")
            document.journeys = [
                item for item in document.journeys if item.id != edit.target_id
            ]
    document = MapDocument.model_validate(document.model_dump(mode="json"))
    layout_preview = await service.preview_layout(
        db,
        novel_id,
        str(args.node_id),
        MapSaveRequest(base_revision_id=args.base_revision_id, document=document),
    )
    return {
        "target_key": f"map:{node.id}",
        "title": f"修改{node.title}的空间结构",
        "base_revision_id": str(node.current_revision_id)
        if node.current_revision_id
        else None,
        "before": before,
        "after": document.model_dump(mode="json"),
        "author_decision": author_decision.model_dump(mode="json")
        if author_decision
        else None,
        "problems": [item.model_dump(mode="json") for item in layout_preview.problems],
        "effect": "只保存作者安排的空间、关系或行程；不生成坐标，也不伪装成正文引文",
    }


async def _structure_edit_apply(db, novel_id, args, preview, *, context=None):
    if await _structure_edit_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("地图、正文安排来源或空间类型已变化，请重新查看方案")
    document = MapDocument.model_validate(preview["after"])
    result = await MapStructureService().save(
        db,
        novel_id,
        str(args.node_id),
        MapSaveRequest(base_revision_id=preview["base_revision_id"], document=document),
    )
    return {
        "type": "map_atlas_node",
        "id": str(args.node_id),
        "revision_id": result.id,
        "label": "已保存新的空间版本",
    }


async def _node_update_preview(db, novel_id, args, *, context=None):
    _require_workbench_scope(context)
    require_targets = get(ASSISTANT_REQUIRE_OPERATION_TARGETS)
    targets = [("map_atlas_node", args.node_id)]
    if args.update.parent_id is not None:
        targets.append(("map_atlas_node", args.update.parent_id))
    await require_targets(db, novel_id, context, targets, aggregate=True)
    before_node = await MapStructureService().node(db, novel_id, str(args.node_id))
    before = MapAtlasService._node_dict(before_node, [], [])
    savepoint = await db.begin_nested()
    try:
        after = await MapAtlasService().update_node(
            db, novel_id, str(args.node_id), args.update
        )
    finally:
        await savepoint.rollback()
    fields = (
        "title",
        "parent_id",
        "level",
        "level_type_ref",
        "level_type_revision_id",
        "sort_order",
    )
    return {
        "target_key": f"map-node:{args.node_id}",
        "title": f"修改地图层级：{before['title']}",
        "before": {key: before[key] for key in fields},
        "after": {key: after[key] for key in fields},
        "effect": "只移動或改名地圖節點，不改動空間版本和圖元坐標",
    }


async def _node_update_apply(db, novel_id, args, preview, *, context=None):
    if await _node_update_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("地圖層級已變化，請重新查看方案")
    result = await MapAtlasService().update_node(
        db, novel_id, str(args.node_id), args.update
    )
    return {
        "type": "map_atlas_node",
        "id": str(args.node_id),
        "label": f"已更新地图层级：{result['title']}",
    }


OPERATIONS_SPEC = {
    "map.add_known_location": {
        "label": "把已知地点加入地图（保留未知位置）",
        "schema": AddKnownLocation,
        "prepare": _location_preview,
        "apply": _save_document,
    },
    "map.edit_feature_label": {
        "label": "修改图元名称或备注",
        "schema": EditFeatureLabel,
        "prepare": _feature_preview,
        "apply": _save_document,
    },
    "map.create_node": {
        "label": "创建空白地图",
        "schema": MapNodeCreate,
        "prepare": _node_preview,
        "apply": _node_apply,
    },
    "map.review_revision": {
        "label": "处理已有地图版本",
        "schema": ReviewMapRevision,
        "prepare": _review_preview,
        "apply": _review_apply,
    },
    "map.review_spatial_clues": {
        "label": "审核空间线索",
        "schema": ReviewSpatialClues,
        "prepare": _clue_review_preview,
        "apply": _clue_review_apply,
    },
    "map.review_auto_draft_group": {
        "label": "按空间或层级审核自动草图",
        "schema": ReviewAutoDraftGroup,
        "prepare": _auto_draft_group_preview,
        "apply": _auto_draft_group_apply,
    },
    "map.edit_spatial_structure": {
        "label": "编辑空间、关系或行程",
        "schema": EditMapStructure,
        "prepare": _structure_edit_preview,
        "apply": _structure_edit_apply,
    },
    "map.update_node": {
        "label": "移动或改名地图节点",
        "schema": UpdateMapNode,
        "prepare": _node_update_preview,
        "apply": _node_update_apply,
    },
}
