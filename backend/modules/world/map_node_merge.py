"""Author-confirmed, reversible merges for simple saved map nodes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)
from pydantic import (
    ValidationError as SchemaValidationError,
)
from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from infrastructure.stable_hash import stable_hash
from infrastructure.tasks.facade import list_task_lifecycle_contracts
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)
from modules.world.map_atlas_models import (
    MapAtlasAnnotation,
    MapAtlasNode,
    MapAtlasPage,
    MapAtlasRevision,
    MapAtlasRun,
)
from modules.world.map_structure_review import changed_items
from modules.world.map_structure_schemas import (
    STRUCTURE_LEVELS,
    MapDocument,
    MapSpace,
)
from modules.world.map_structure_service import MapStructureService
from shared.constants import TASK_MAX_HEARTBEAT_GAP
from shared.utils import parse_uuid


class MapNodeMergePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: UUID
    target_node_id: UUID


class MapNodeMergePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: UUID
    target_node_id: UUID
    source_title: str
    target_title: str
    source_hierarchy: dict[str, Any]
    target_hierarchy: dict[str, Any]
    source_revision_id: UUID | None
    target_revision_id: UUID | None
    source_document: MapDocument | None = None
    target_document: MapDocument | None = None
    merged_document: MapDocument | None = None
    fingerprint: str
    can_execute: bool
    blockers: list[str] = Field(default_factory=list, max_length=50)
    affected_count: int
    requires_source_disposition_confirmation: bool = True


class MapNodeMergeApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: UUID
    target_node_id: UUID
    preview_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed_source_disposition: bool


class MapNodeMergeUndoPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: UUID
    target_node_id: UUID
    merged_revision_id: UUID | None
    restored_revision_id: UUID | None
    fingerprint: str
    can_undo: bool
    blockers: list[str] = Field(default_factory=list, max_length=50)
    affected_count: int


class MapNodeMergeUndoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: UUID
    target_node_id: UUID
    preview_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: bool


def _node_state(node: MapAtlasNode, revision: MapAtlasRevision | None) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "novel_id": str(node.novel_id),
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "current_revision_id": (
            str(node.current_revision_id) if node.current_revision_id else None
        ),
        "level": node.level,
        "level_type_ref": str(node.level_type_ref) if node.level_type_ref else None,
        "level_type_revision_id": (
            str(node.level_type_revision_id) if node.level_type_revision_id else None
        ),
        "status": node.status,
        "location_entity_id": (
            str(node.location_entity_id) if node.location_entity_id else None
        ),
        "semantic_key": node.semantic_key,
        "title": node.title,
        "summary": node.summary,
        "sort_order": node.sort_order,
        "structure_task_id": (
            str(node.structure_task_id) if node.structure_task_id else None
        ),
        "merged_into_node_id": (
            str(node.merged_into_node_id) if node.merged_into_node_id else None
        ),
        "merge_metadata": node.merge_metadata,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        "revision": (
            {
                "id": str(revision.id),
                "status": revision.status,
                "base_revision_id": (
                    str(revision.base_revision_id) if revision.base_revision_id else None
                ),
                "geometry_hash": revision.geometry_hash,
                "document": revision.document,
            }
            if revision
            else None
        ),
    }


def _bounded_id(source_id: UUID, kind: str, original_id: str, occupied: set[str]) -> str:
    digest = stable_hash([str(source_id), kind, original_id])[:16]
    base = f"m{source_id.hex[:10]}_{kind}_{digest}"
    candidate = base
    suffix = 1
    while candidate in occupied:
        candidate = f"{base}_{suffix}"
        suffix += 1
    occupied.add(candidate)
    return candidate


def _combine_documents(
    source_id: UUID, source: MapDocument, target: MapDocument
) -> MapDocument:
    feature_ids = {item.id for item in target.features}
    constraint_ids = {item.id for item in target.constraints}
    journey_ids = {item.id for item in target.journeys}
    feature_map = {
        item.id: _bounded_id(source_id, "f", item.id, feature_ids)
        for item in source.features
    }
    constraint_map = {
        item.id: _bounded_id(source_id, "c", item.id, constraint_ids)
        for item in source.constraints
    }
    journey_map = {
        item.id: _bounded_id(source_id, "j", item.id, journey_ids)
        for item in source.journeys
    }

    target_payload = target.model_dump(mode="json")
    target_payload["schema_version"] = 2
    if target.schema_version == 1:
        target_payload["spaces"] = [
            MapSpace(id="main", label="主空间").model_dump(mode="json")
        ]
    else:
        target_payload["spaces"] = [
            item.model_dump(mode="json") for item in target.spaces
        ]

    source_spaces = (
        source.spaces
        if source.schema_version == 2
        else [MapSpace(id="main", label="主空间")]
    )
    occupied_spaces = {item["id"] for item in target_payload["spaces"]}
    space_map = {
        item.id: _bounded_id(source_id, "s", item.id, occupied_spaces)
        for item in source_spaces
    }
    target_payload["spaces"].extend(
        [
            item.model_copy(update={"id": space_map[item.id]}).model_dump(mode="json")
            for item in source_spaces
        ]
    )

    for feature in source.features:
        copied = feature.model_copy(
            update={
                "id": feature_map[feature.id],
                "space_id": space_map[feature.space_id],
                "depends_on": [feature_map[item] for item in feature.depends_on],
            }
        )
        target_payload["features"].append(copied.model_dump(mode="json"))
    target_payload["constraints"].extend(
        [
            item.model_copy(
                update={
                    "id": constraint_map[item.id],
                    "subject": feature_map[item.subject],
                    "target": feature_map[item.target],
                    "via": [feature_map[key] for key in item.via],
                }
            ).model_dump(mode="json")
            for item in source.constraints
        ]
    )
    target_payload["journeys"].extend(
        [
            item.model_copy(
                update={
                    "id": journey_map[item.id],
                    "origin": feature_map[item.origin],
                    "destination": feature_map[item.destination],
                }
            ).model_dump(mode="json")
            for item in source.journeys
        ]
    )
    return MapDocument.model_validate(target_payload)


class MapNodeMergeService:
    async def _pair(
        self,
        db: AsyncSession,
        novel_id: str,
        source_node_id: str | UUID,
        target_node_id: str | UUID,
        *,
        lock: bool = False,
    ) -> tuple[MapAtlasNode, MapAtlasNode]:
        nid = parse_uuid(novel_id, "novel_id")
        source_id = parse_uuid(str(source_node_id), "source_node_id")
        target_id = parse_uuid(str(target_node_id), "target_node_id")
        if source_id == target_id:
            raise ValidationError("不能将地图节点合并到自身")
        statement = (
            select(MapAtlasNode)
            .where(
                MapAtlasNode.novel_id == nid,
                MapAtlasNode.id.in_({source_id, target_id}),
            )
            .order_by(MapAtlasNode.id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        nodes = (await db.scalars(statement)).all()
        by_id = {node.id: node for node in nodes}
        source, target = by_id.get(source_id), by_id.get(target_id)
        if source is None or target is None:
            raise NotFoundError("地图节点不存在或不属于当前作品")
        return source, target

    async def _head(
        self, db: AsyncSession, node: MapAtlasNode
    ) -> MapAtlasRevision | None:
        if node.current_revision_id is None:
            return None
        return await db.scalar(
            select(MapAtlasRevision)
            .where(
                MapAtlasRevision.novel_id == node.novel_id,
                MapAtlasRevision.node_id == node.id,
                MapAtlasRevision.id == node.current_revision_id,
            )
            .execution_options(populate_existing=True)
        )

    async def _resource_state(
        self,
        db: AsyncSession,
        novel_id: str,
        source: MapAtlasNode,
        target: MapAtlasNode,
    ) -> tuple[dict[str, Any], list[str]]:
        nid = source.novel_id
        ids = {source.id, target.id}
        blockers: list[str] = []
        children = list(
            (
                await db.scalars(
                    select(MapAtlasNode.id)
                    .where(
                        MapAtlasNode.novel_id == nid,
                        MapAtlasNode.parent_id == source.id,
                    )
                    .order_by(MapAtlasNode.id)
                )
            ).all()
        )
        if children:
            blockers.append("来源节点仍有子节点，需先整理层级")

        revisions = list(
            (
                await db.execute(
                    select(
                        MapAtlasRevision.id,
                        MapAtlasRevision.node_id,
                        MapAtlasRevision.status,
                        MapAtlasRevision.geometry_hash,
                    )
                    .where(
                        MapAtlasRevision.novel_id == nid,
                        MapAtlasRevision.node_id.in_(ids),
                    )
                    .order_by(MapAtlasRevision.node_id, MapAtlasRevision.created_at)
                )
            ).all()
        )
        candidate_revisions = [row for row in revisions if row.status == "candidate"]
        if candidate_revisions:
            blockers.append("来源或目标仍有待审核草图")

        pages = list(
            (
                await db.execute(
                    select(
                        MapAtlasPage.id,
                        MapAtlasPage.node_id,
                        MapAtlasPage.generation_status,
                        MapAtlasPage.review_status,
                    )
                    .where(MapAtlasPage.novel_id == nid, MapAtlasPage.node_id.in_(ids))
                    .order_by(MapAtlasPage.node_id, MapAtlasPage.id)
                )
            ).all()
        )
        if pages:
            blockers.append("来源或目标已有图片页，当前合并不会移动图片")

        annotations = list(
            (
                await db.execute(
                    select(
                        MapAtlasAnnotation.id,
                        MapAtlasAnnotation.page_id,
                        MapAtlasAnnotation.target_node_id,
                    )
                    .where(
                        MapAtlasAnnotation.novel_id == nid,
                        MapAtlasAnnotation.target_node_id == source.id,
                    )
                    .order_by(MapAtlasAnnotation.id)
                )
            ).all()
        )
        if annotations:
            blockers.append("其他地图标注仍跳转到来源节点，需先改正跳转")

        heads = (
            await db.execute(
                select(MapAtlasNode.id, MapAtlasRevision.document)
                .join(
                    MapAtlasRevision,
                    and_(
                        MapAtlasRevision.id == MapAtlasNode.current_revision_id,
                        MapAtlasRevision.node_id == MapAtlasNode.id,
                        MapAtlasRevision.novel_id == MapAtlasNode.novel_id,
                    ),
                )
                .where(MapAtlasNode.novel_id == nid)
                .order_by(MapAtlasNode.id)
            )
        ).all()
        document_links = []
        for node_id, document in heads:
            for feature in (document or {}).get("features", []):
                if str(feature.get("target_node_id")) == str(source.id):
                    document_links.append(
                        {"node_id": str(node_id), "feature_id": feature.get("id")}
                    )
        if document_links:
            blockers.append("其他地图仍有子图跳转到来源节点，需先改正跳转")

        from modules.world.map_auto_draft_models import MapAutoDraftBatchRecord

        batches = list(
            (
                await db.scalars(
                    select(MapAutoDraftBatchRecord)
                    .where(
                        MapAutoDraftBatchRecord.novel_id == nid,
                        MapAutoDraftBatchRecord.status.in_(["running", "completed"]),
                    )
                    .order_by(MapAutoDraftBatchRecord.id)
                )
            ).all()
        )
        auto_state = []
        for batch in batches:
            plan = batch.plan_json or {}
            shard_ids = {str(item.get("node_id")) for item in plan.get("shards", [])}
            result_refs = [
                item
                for item in batch.result_refs or []
                if str(item.get("node_id")) in {str(value) for value in ids}
                and item.get("status") == "candidate"
            ]
            pending_trays = [
                item
                for item in batch.tray_items or []
                if str(item.get("node_id")) in {str(value) for value in ids}
                and not item.get("placed_feature_id")
            ]
            relevant = (
                (batch.status == "running" and bool(shard_ids & {str(i) for i in ids}))
                or result_refs
                or pending_trays
            )
            if relevant:
                auto_state.append(
                    {
                        "id": str(batch.id),
                        "status": batch.status,
                        "shards": sorted(shard_ids & {str(i) for i in ids}),
                        "candidate_refs": result_refs,
                        "pending_trays": pending_trays,
                    }
                )
        if any(item["status"] == "running" for item in auto_state):
            blockers.append("来源或目标仍有进行中的自动草图")
        if any(item["candidate_refs"] for item in auto_state):
            blockers.append("来源或目标仍有自动草图候选")
        if any(item["pending_trays"] for item in auto_state):
            blockers.append("来源或目标仍有未放置的托盘地点")

        task_ids = [
            str(node.structure_task_id)
            for node in (source, target)
            if node.structure_task_id is not None
        ]
        tasks = (
            await list_task_lifecycle_contracts(
                db,
                task_ids=task_ids,
                novel_id=novel_id,
                max_heartbeat_gap=TASK_MAX_HEARTBEAT_GAP,
            )
            if task_ids
            else {}
        )
        active_tasks = sorted(
            task_id
            for task_id, task in tasks.items()
            if task.status in {"pending", "running"}
        )
        if active_tasks:
            blockers.append("来源或目标仍在整理空间资料")

        active_runs = list(
            (
                await db.execute(
                    select(MapAtlasRun.id, MapAtlasRun.status)
                    .where(
                        MapAtlasRun.novel_id == nid,
                        MapAtlasRun.status.in_(
                            {"planning", "prompt_review", "generating"}
                        ),
                    )
                    .order_by(MapAtlasRun.id)
                )
            ).all()
        )
        if active_runs:
            blockers.append("项目仍有进行中的地图册任务")

        state = {
            "children": [str(item) for item in children],
            "revisions": [
                {
                    "id": str(row.id),
                    "node_id": str(row.node_id),
                    "status": row.status,
                    "geometry_hash": row.geometry_hash,
                }
                for row in revisions
            ],
            "pages": [
                {
                    "id": str(row.id),
                    "node_id": str(row.node_id),
                    "generation_status": row.generation_status,
                    "review_status": row.review_status,
                }
                for row in pages
            ],
            "incoming_annotations": [
                {
                    "id": str(row.id),
                    "page_id": str(row.page_id),
                    "target_node_id": str(row.target_node_id),
                }
                for row in annotations
            ],
            "incoming_feature_links": document_links,
            "auto_drafts": auto_state,
            "active_tasks": active_tasks,
            "active_atlas_runs": [
                {"id": str(row.id), "status": row.status} for row in active_runs
            ],
        }
        return state, blockers

    async def preview(
        self,
        db: AsyncSession,
        novel_id: str,
        source_node_id: str | UUID,
        target_node_id: str | UUID,
        *,
        lock: bool = False,
    ) -> MapNodeMergePreview:
        await require_active_project(db, novel_id)
        source, target = await self._pair(
            db, novel_id, source_node_id, target_node_id, lock=lock
        )
        source_revision, target_revision = (
            await self._head(db, source),
            await self._head(db, target),
        )
        blockers: list[str] = []
        if source.merged_into_node_id is not None:
            blockers.append("来源节点已合并")
        if target.merged_into_node_id is not None:
            blockers.append("目标节点已合并，请选择当前目标")
        if source.status != "adopted" or target.status != "adopted":
            blockers.append("只能合并已加入地图册的节点")
        if source.level not in STRUCTURE_LEVELS or target.level not in STRUCTURE_LEVELS:
            blockers.append("当前只支持区域、城市、街区、街道或室内空间节点")
        if source.level != target.level or source.parent_id != target.parent_id:
            blockers.append("来源和目标必须处于同一层级和同一上级")
        if (
            source.level_type_ref != target.level_type_ref
            or source.level_type_revision_id != target.level_type_revision_id
        ):
            blockers.append("来源和目标的固定层级类型不同，不能合并")
        if source.location_entity_id is not None or target.location_entity_id is not None:
            blockers.append("绑定世界地点的节点需要先在地点资料中处理")
        if source_revision is None or target_revision is None:
            blockers.append("来源和目标都需要有已保存的空间版本")
        elif source_revision.status != "saved" or target_revision.status != "saved":
            blockers.append("来源和目标当前版本都必须是已保存版本")

        parent = None
        if source.parent_id is not None:
            parent = await db.scalar(
                select(MapAtlasNode).where(
                    MapAtlasNode.novel_id == source.novel_id,
                    MapAtlasNode.id == source.parent_id,
                )
            )
            if (
                parent is None
                or parent.status != "adopted"
                or parent.merged_into_node_id is not None
            ):
                blockers.append("共同上级已变化，请先整理地图层级")

        incoming_merges = list(
            (
                await db.scalars(
                    select(MapAtlasNode.id)
                    .where(
                        MapAtlasNode.novel_id == source.novel_id,
                        MapAtlasNode.merged_into_node_id == source.id,
                    )
                    .order_by(MapAtlasNode.id)
                )
            ).all()
        )
        if incoming_merges:
            blockers.append("来源地图仍接收其他节点的合并，请先撤回这些合并")

        resource_state, resource_blockers = await self._resource_state(
            db, novel_id, source, target
        )
        blockers.extend(resource_blockers)
        source_document = None
        target_document = None
        try:
            if source_revision is not None:
                source_document = MapDocument.model_validate(source_revision.document)
            if target_revision is not None:
                target_document = MapDocument.model_validate(target_revision.document)
        except SchemaValidationError:
            blockers.append("来源或目标地图版本结构已损坏，请先在工作台核对")
        merged_document = None
        count_preview = None
        affected_count = 0
        if source_document is not None and target_document is not None:
            if source_document.images or target_document.images:
                blockers.append("含有底图或插图的空间版本暂不支持节点合并")
            if source_document.annotation_bindings or target_document.annotation_bindings:
                blockers.append("含有图片标注绑定的空间版本暂不支持节点合并")
            if len(source_document.features) + len(target_document.features) > 200:
                blockers.append("合并后图元超过 200 项上限")
            if (
                len(source_document.constraints)
                + len(source_document.journeys)
                + len(target_document.constraints)
                + len(target_document.journeys)
                > 400
            ):
                blockers.append("合并后关系和行程超过 400 项上限")
            if source_document.author_decision != target_document.author_decision:
                blockers.append("两份地图的作者安排来源不同，不能合并")
            if any(
                feature.target_node_id == source.id
                for document in (source_document, target_document)
                for feature in document.features
            ):
                blockers.append("地图中仍有跳转指向来源节点，需先改正跳转")
            try:
                count_preview = _combine_documents(
                    source.id, source_document, target_document
                )
                affected_count = (
                    len(changed_items(target_document, count_preview)) + 1
                )  # Retire the source from official map projections.
                if affected_count > 20:
                    blockers.append(
                        f"此次合并涉及 {affected_count} 项实际地图变更，"
                        "超过单次 20 项上限"
                    )
            except (SchemaValidationError, TypeError, ValueError):
                blockers.append("地图内容无法安全合并，请先在工作台核对")
            if not blockers:
                try:
                    merged_document = count_preview
                    structure = MapStructureService()
                    await structure.validate_document(
                        db, novel_id, target, merged_document
                    )
                    for document in (source_document, target_document):
                        for item in [
                            *document.features,
                            *document.constraints,
                            *document.journeys,
                        ]:
                            for source_ref in item.sources:
                                await structure.source(db, novel_id, source_ref)
                except DomainError:
                    merged_document = None
                    blockers.append("地图来源、作者安排或固定类型需要先在工作台核对")
                except (TypeError, ValueError):
                    merged_document = None
                    blockers.append("地图内容无法安全合并，请先在工作台核对")

        blockers = list(dict.fromkeys(blockers))
        state = {
            "source": _node_state(source, source_revision),
            "target": _node_state(target, target_revision),
            "parent": _node_state(parent, await self._head(db, parent))
            if parent is not None
            else None,
            "resources": resource_state,
            "incoming_merges": [str(value) for value in incoming_merges],
            "merged_document": (
                merged_document.model_dump(mode="json") if merged_document else None
            ),
            "affected_count": affected_count,
            "blockers": blockers,
        }
        fingerprint = stable_hash(state)
        return MapNodeMergePreview(
            source_node_id=source.id,
            target_node_id=target.id,
            source_title=source.title,
            target_title=target.title,
            source_hierarchy={
                "level": source.level,
                "parent_id": str(source.parent_id) if source.parent_id else None,
                "parent_title": parent.title if parent else None,
                "level_type_ref": (
                    str(source.level_type_ref) if source.level_type_ref else None
                ),
                "level_type_revision_id": (
                    str(source.level_type_revision_id)
                    if source.level_type_revision_id
                    else None
                ),
            },
            target_hierarchy={
                "level": target.level,
                "parent_id": str(target.parent_id) if target.parent_id else None,
                "parent_title": parent.title if parent else None,
                "level_type_ref": (
                    str(target.level_type_ref) if target.level_type_ref else None
                ),
                "level_type_revision_id": (
                    str(target.level_type_revision_id)
                    if target.level_type_revision_id
                    else None
                ),
            },
            source_revision_id=source.current_revision_id,
            target_revision_id=target.current_revision_id,
            source_document=source_document,
            target_document=target_document,
            merged_document=merged_document,
            fingerprint=fingerprint,
            can_execute=not blockers,
            blockers=blockers,
            affected_count=affected_count,
        )

    async def apply(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MapNodeMergeApplyRequest,
    ) -> dict[str, Any]:
        await require_active_project_exclusive(db, novel_id)
        source, target = await self._pair(
            db,
            novel_id,
            data.source_node_id,
            data.target_node_id,
            lock=True,
        )
        preview = await self.preview(
            db,
            novel_id,
            source.id,
            target.id,
            lock=True,
        )
        if preview.fingerprint != data.preview_fingerprint:
            raise ConflictError("地图节点或来源已变化，请重新预览合并")
        if not preview.can_execute:
            reason = "；".join(preview.blockers)
            raise ValidationError("此节点组合并暂不可执行：" + reason)
        if not data.confirmed_source_disposition:
            raise ValidationError("需要明确确认来源节点将保留为合并跳转")
        assert preview.merged_document is not None
        assert target.current_revision_id is not None
        assert source.current_revision_id is not None

        from modules.world.map_structure_geometry import geometry_hash
        from modules.world.services.common import current_writing_chapter_index

        async with db.begin_nested():
            merged_revision = MapAtlasRevision(
                novel_id=target.novel_id,
                node_id=target.id,
                base_revision_id=target.current_revision_id,
                status="saved",
                document=preview.merged_document.model_dump(mode="json"),
                geometry_hash=geometry_hash(preview.merged_document),
                problems=[],
                change_summary={
                    "operation": "map_node_merge",
                    "source_node_id": str(source.id),
                    "source_revision_id": str(source.current_revision_id),
                },
                writing_chapter_index=await current_writing_chapter_index(db, novel_id),
            )
            db.add(merged_revision)
            await db.flush()
            receipt = {
                "version": 1,
                "source_revision_id": str(source.current_revision_id),
                "source_geometry_hash": preview.source_document
                and geometry_hash(preview.source_document),
                "target_previous_revision_id": str(target.current_revision_id),
                "target_merged_revision_id": str(merged_revision.id),
                "preview_fingerprint": preview.fingerprint,
            }
            now = datetime.now(UTC)
            cas = await db.execute(
                update(MapAtlasNode)
                .where(
                    MapAtlasNode.novel_id == source.novel_id,
                    MapAtlasNode.id.in_({source.id, target.id}),
                    or_(
                        and_(
                            MapAtlasNode.id == source.id,
                            MapAtlasNode.current_revision_id
                            == source.current_revision_id,
                            MapAtlasNode.merged_into_node_id.is_(None),
                            MapAtlasNode.updated_at == source.updated_at,
                        ),
                        and_(
                            MapAtlasNode.id == target.id,
                            MapAtlasNode.current_revision_id
                            == target.current_revision_id,
                            MapAtlasNode.merged_into_node_id.is_(None),
                            MapAtlasNode.updated_at == target.updated_at,
                        ),
                    ),
                )
                .values(
                    current_revision_id=case(
                        (MapAtlasNode.id == target.id, merged_revision.id),
                        else_=MapAtlasNode.current_revision_id,
                    ),
                    merged_into_node_id=case(
                        (MapAtlasNode.id == source.id, target.id),
                        else_=MapAtlasNode.merged_into_node_id,
                    ),
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if cas.rowcount != 2:
                raise ConflictError("地图版本已变化，请重新预览合并")
            receipt_cas = await db.execute(
                update(MapAtlasNode)
                .where(
                    MapAtlasNode.novel_id == source.novel_id,
                    MapAtlasNode.id == source.id,
                    MapAtlasNode.current_revision_id == source.current_revision_id,
                    MapAtlasNode.merged_into_node_id == target.id,
                    MapAtlasNode.updated_at == now,
                )
                .values(merge_metadata=receipt)
                .execution_options(synchronize_session=False)
            )
            if receipt_cas.rowcount != 1:
                raise ConflictError("地图来源状态已变化，请重新预览合并")
            source.merged_into_node_id = target.id
            source.merge_metadata = receipt
            target.current_revision_id = merged_revision.id
            source.updated_at = now
            target.updated_at = now
            await db.flush()

        undo = await self.preview_undo(db, novel_id, source.id, target.id)
        return {
            "type": "map_node_merge",
            "source_node_id": str(source.id),
            "source_title": source.title,
            "target_node_id": str(target.id),
            "target_title": target.title,
            "merged_revision_id": str(merged_revision.id),
            "undo_fingerprint": undo.fingerprint if undo.can_undo else None,
            "label": f"已将“{source.title}”合并到“{target.title}”",
        }

    async def preview_undo(
        self,
        db: AsyncSession,
        novel_id: str,
        source_node_id: str | UUID,
        target_node_id: str | UUID,
        *,
        lock: bool = False,
    ) -> MapNodeMergeUndoPreview:
        await require_active_project(db, novel_id)
        source, target = await self._pair(
            db, novel_id, source_node_id, target_node_id, lock=lock
        )
        blockers: list[str] = []
        if target.merged_into_node_id is not None:
            blockers.append("目标地图也已合并，请先处理后续合并，不能跨目标撤回")
        receipt = source.merge_metadata or {}
        merged_revision_id = receipt.get("target_merged_revision_id")
        restored_revision_id = receipt.get("target_previous_revision_id")
        if source.merged_into_node_id != target.id or receipt.get("version") != 1:
            blockers.append("找不到这两个节点之间可撤回的合并记录")
        if (
            str(source.current_revision_id) != receipt.get("source_revision_id")
            or str(target.current_revision_id) != merged_revision_id
        ):
            blockers.append("合并后节点已有新变化，不能自动撤回")
        merged_revision = await self._head(db, target)
        previous_revision = (
            await db.scalar(
                select(MapAtlasRevision).where(
                    MapAtlasRevision.novel_id == target.novel_id,
                    MapAtlasRevision.node_id == target.id,
                    MapAtlasRevision.id
                    == parse_uuid(restored_revision_id, "restored_revision_id"),
                    MapAtlasRevision.status == "saved",
                )
            )
            if restored_revision_id
            else None
        )
        valid_merged_revision_id = None
        if merged_revision_id:
            try:
                valid_merged_revision_id = parse_uuid(
                    merged_revision_id, "merged_revision_id"
                )
            except ValidationError:
                blockers.append("合并版本引用无效，不能自动撤回")
        if (
            merged_revision is None
            or valid_merged_revision_id is None
            or merged_revision.id != valid_merged_revision_id
            or previous_revision is None
            or merged_revision.base_revision_id != previous_revision.id
        ):
            blockers.append("合并前的地图版本不完整，不能自动撤回")
        elif (
            (merged_revision.change_summary or {}).get("operation") != "map_node_merge"
            or (merged_revision.change_summary or {}).get("source_node_id")
            != str(source.id)
            or (merged_revision.change_summary or {}).get("source_revision_id")
            != str(source.current_revision_id)
        ):
            blockers.append("目标合并版本与来源节点不匹配，不能自动撤回")
        source_revision = await self._head(db, source)
        from modules.world.map_structure_geometry import geometry_hash

        try:
            source_hash = (
                geometry_hash(MapDocument.model_validate(source_revision.document))
                if source_revision
                else None
            )
        except SchemaValidationError:
            source_hash = None
        if (
            source_revision is None
            or source_revision.geometry_hash != receipt.get("source_geometry_hash")
            or source_hash != source_revision.geometry_hash
        ):
            blockers.append("来源节点历史版本已变化，不能自动撤回")
        resource_state, resource_blockers = await self._resource_state(
            db, novel_id, source, target
        )
        blockers.extend(resource_blockers)
        affected_count = 0
        if merged_revision is not None and previous_revision is not None:
            try:
                current_document = MapDocument.model_validate(merged_revision.document)
                previous_document = MapDocument.model_validate(previous_revision.document)
                affected_count = (
                    len(changed_items(current_document, previous_document)) + 1
                )  # Restore the source to official map projections.
                if affected_count > 20:
                    blockers.append(
                        f"此次撤回涉及 {affected_count} 项实际地图变更，"
                        "超过单次 20 项上限"
                    )
            except SchemaValidationError:
                blockers.append("合并前后的地图版本结构已损坏，不能自动撤回")
        blockers = list(dict.fromkeys(blockers))
        state = {
            "source": _node_state(source, source_revision),
            "target": _node_state(target, merged_revision),
            "receipt": receipt,
            "previous_revision": (
                {
                    "id": str(previous_revision.id),
                    "document": previous_revision.document,
                    "geometry_hash": previous_revision.geometry_hash,
                }
                if previous_revision
                else None
            ),
            "resources": resource_state,
            "affected_count": affected_count,
            "blockers": blockers,
        }
        return MapNodeMergeUndoPreview(
            source_node_id=source.id,
            target_node_id=target.id,
            merged_revision_id=(
                parse_uuid(merged_revision_id, "merged_revision_id")
                if merged_revision_id
                else None
            ),
            restored_revision_id=(
                parse_uuid(restored_revision_id, "restored_revision_id")
                if restored_revision_id
                else None
            ),
            fingerprint=stable_hash(state),
            can_undo=not blockers,
            blockers=blockers,
            affected_count=affected_count,
        )

    async def undo(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MapNodeMergeUndoRequest,
    ) -> dict[str, Any]:
        await require_active_project_exclusive(db, novel_id)
        source, target = await self._pair(
            db,
            novel_id,
            data.source_node_id,
            data.target_node_id,
            lock=True,
        )
        preview = await self.preview_undo(db, novel_id, source.id, target.id, lock=True)
        if not preview.can_undo:
            raise ConflictError("当前状态不能撤回合并：" + "；".join(preview.blockers))
        if preview.fingerprint != data.preview_fingerprint:
            raise ConflictError("合并后的地图已变化，请重新预览撤回")
        if not data.confirmed:
            raise ValidationError("需要确认恢复来源节点并追加目标恢复版本")

        previous_revision = await db.scalar(
            select(MapAtlasRevision).where(
                MapAtlasRevision.novel_id == target.novel_id,
                MapAtlasRevision.node_id == target.id,
                MapAtlasRevision.id == preview.restored_revision_id,
                MapAtlasRevision.status == "saved",
            )
        )
        merged_revision_id = preview.merged_revision_id
        if previous_revision is None or merged_revision_id is None:
            raise ConflictError("合并前的地图版本不完整，不能自动撤回")
        from modules.world.map_structure_geometry import geometry_hash
        from modules.world.services.common import current_writing_chapter_index

        async with db.begin_nested():
            restored_revision = MapAtlasRevision(
                novel_id=target.novel_id,
                node_id=target.id,
                base_revision_id=merged_revision_id,
                status="saved",
                document=previous_revision.document,
                geometry_hash=geometry_hash(
                    MapDocument.model_validate(previous_revision.document)
                ),
                problems=previous_revision.problems,
                change_summary={
                    "operation": "map_node_merge_undo",
                    "source_node_id": str(source.id),
                    "undone_merge_revision_id": str(merged_revision_id),
                    "restored_revision_id": str(previous_revision.id),
                },
                writing_chapter_index=await current_writing_chapter_index(db, novel_id),
            )
            db.add(restored_revision)
            await db.flush()
            now = datetime.now(UTC)
            cas = await db.execute(
                update(MapAtlasNode)
                .where(
                    MapAtlasNode.novel_id == source.novel_id,
                    MapAtlasNode.id.in_({source.id, target.id}),
                    or_(
                        and_(
                            MapAtlasNode.id == source.id,
                            MapAtlasNode.current_revision_id
                            == source.current_revision_id,
                            MapAtlasNode.merged_into_node_id == target.id,
                            MapAtlasNode.updated_at == source.updated_at,
                        ),
                        and_(
                            MapAtlasNode.id == target.id,
                            MapAtlasNode.current_revision_id == merged_revision_id,
                            MapAtlasNode.updated_at == target.updated_at,
                        ),
                    ),
                )
                .values(
                    current_revision_id=case(
                        (MapAtlasNode.id == target.id, restored_revision.id),
                        else_=MapAtlasNode.current_revision_id,
                    ),
                    merged_into_node_id=case(
                        (MapAtlasNode.id == source.id, None),
                        else_=MapAtlasNode.merged_into_node_id,
                    ),
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if cas.rowcount != 2:
                raise ConflictError("合并后的地图已变化，请重新预览撤回")
            receipt_cas = await db.execute(
                update(MapAtlasNode)
                .where(
                    MapAtlasNode.novel_id == source.novel_id,
                    MapAtlasNode.id == source.id,
                    MapAtlasNode.current_revision_id == source.current_revision_id,
                    MapAtlasNode.merged_into_node_id.is_(None),
                    MapAtlasNode.updated_at == now,
                )
                .values(merge_metadata=None)
                .execution_options(synchronize_session=False)
            )
            if receipt_cas.rowcount != 1:
                raise ConflictError("合并后的来源状态已变化，请重新预览撤回")
            source.merged_into_node_id = None
            source.merge_metadata = None
            target.current_revision_id = restored_revision.id
            source.updated_at = now
            target.updated_at = now
            await db.flush()
        return {
            "type": "map_node_merge_undo",
            "source_node_id": str(source.id),
            "target_node_id": str(target.id),
            "restored_revision_id": str(restored_revision.id),
            "label": f"已恢复“{source.title}”并追加目标地图恢复版本",
        }


__all__ = [
    "MapNodeMergeApplyRequest",
    "MapNodeMergePreview",
    "MapNodeMergePreviewRequest",
    "MapNodeMergeService",
    "MapNodeMergeUndoPreview",
    "MapNodeMergeUndoRequest",
]
