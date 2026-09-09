"""Unified node-owned map revisions, image calibration and safe reader projections."""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.tasks.facade import (
    get_completed_task_payload,
    list_task_lifecycle_contracts,
)
from modules.evidence.contracts import VisibilityContextContract
from modules.evidence.facade import (
    inspect_novel_target,
    prepare_confirmed_ai_action,
    read_novel_evidence,
)
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)
from modules.story.facade import get_reader_reveal_decision
from modules.world.map_atlas_models import (
    MapAtlasAnnotation,
    MapAtlasNode,
    MapAtlasPage,
    MapAtlasRevision,
)
from modules.world.map_atlas_schemas import ATLAS_LEVEL_RANK
from modules.world.map_atlas_service import MapAtlasService
from modules.world.map_structure_geometry import (
    affine_transform,
    diagnose,
    geometry_hash,
    layout,
)
from modules.world.map_structure_schemas import (
    STRUCTURE_LEVELS,
    MapDocument,
    MapExtractionSummary,
    MapLayoutResponse,
    MapLink,
    MapLinkQuery,
    MapLinksResponse,
    MapNodeCreate,
    MapNodeMapResponse,
    MapProblem,
    MapRevisionResponse,
    MapRevisionReview,
    MapSaveRequest,
    MapSource,
)
from modules.world.models import CoreEntity, WorldBiblePage
from modules.writing.contracts import SourceRangeRefContract
from shared.constants import TASK_MAX_HEARTBEAT_GAP
from shared.utils import parse_uuid

MAP_ACTION = "world.map_atlas.structure"
MAP_TASK = "world_map_schematic_generate"
_CALIBRATION_HISTORY_LIMIT = 100


def source_payload(item) -> dict:
    if isinstance(item, CoreEntity):
        return {
            key: getattr(item, key)
            for key in (
                "name",
                "summary",
                "public_info",
                "hidden_truth",
                "content_json",
                "status",
                "reveal_level",
            )
        }
    return {
        key: getattr(item, key, None)
        for key in ("title", "free_text", "sections_json", "status", "version_number")
    }


def source_digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def source_text(payload) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return "\n".join(source_text(value) for value in payload.values())
    if isinstance(payload, list):
        return "\n".join(source_text(value) for value in payload)
    return ""


class MapStructureService:
    async def node(self, db, novel_id: str, node_id: str, *, lock=False) -> MapAtlasNode:
        await require_active_project(db, novel_id)
        statement = select(MapAtlasNode).where(
            MapAtlasNode.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAtlasNode.id == parse_uuid(node_id, "node_id"),
        )
        if lock:
            statement = statement.with_for_update()
        node = await db.scalar(statement.execution_options(populate_existing=lock))
        if node is None:
            raise NotFoundError("地图不存在")
        return node

    async def revision(
        self, db, novel_id: str, node_id: str, revision_id
    ) -> MapAtlasRevision:
        row = await db.scalar(
            select(MapAtlasRevision).where(
                MapAtlasRevision.novel_id == parse_uuid(novel_id, "novel_id"),
                MapAtlasRevision.node_id == parse_uuid(node_id, "node_id"),
                MapAtlasRevision.id == parse_uuid(str(revision_id), "revision_id"),
            )
        )
        if row is None:
            raise NotFoundError("地图版本不存在")
        return row

    @staticmethod
    def response(row: MapAtlasRevision) -> MapRevisionResponse:
        return MapRevisionResponse(
            id=str(row.id),
            node_id=str(row.node_id),
            base_revision_id=str(row.base_revision_id) if row.base_revision_id else None,
            status=row.status,
            document=MapDocument.model_validate(row.document),
            geometry_hash=row.geometry_hash,
            problems=row.problems,
            created_at=row.created_at,
        )

    async def map_links(self, db, novel_id: str, query: MapLinkQuery) -> MapLinksResponse:
        await require_active_project(db, novel_id)
        query = MapLinkQuery.model_validate(query.model_dump())
        text = query.q.strip().casefold()
        if query.chapter_index is None and query.entity_id is None and not text:
            return MapLinksResponse()
        nid = parse_uuid(novel_id, "novel_id")
        # ponytail: scan at most 200 saved maps; add a search index if maps outgrow this.
        rows = (
            await db.execute(
                select(MapAtlasNode, MapAtlasRevision.document)
                .join(
                    MapAtlasRevision,
                    (
                        (MapAtlasRevision.id == MapAtlasNode.current_revision_id)
                        & (MapAtlasRevision.node_id == MapAtlasNode.id)
                        & (MapAtlasRevision.novel_id == MapAtlasNode.novel_id)
                    ),
                )
                .where(
                    MapAtlasNode.novel_id == nid,
                    MapAtlasNode.status == "adopted",
                    MapAtlasRevision.novel_id == nid,
                    MapAtlasRevision.status == "saved",
                )
                .order_by(MapAtlasNode.updated_at.desc(), MapAtlasNode.id)
                .limit(201)
            )
        ).all()
        response = MapLinksResponse(truncated=len(rows) > 200)
        for node, payload in rows[:200]:
            document = MapDocument.model_validate(payload)
            for feature in document.features:
                chapters = sorted(
                    {
                        source.source_ref["chapter_index"]
                        for source in feature.sources
                        if source.kind == "source_range"
                    }
                )
                if (
                    query.chapter_index is not None
                    and query.chapter_index not in chapters
                ):
                    continue
                if query.entity_id is not None and query.entity_id != feature.entity_id:
                    continue
                if (
                    text
                    and text not in feature.label.casefold()
                    and text not in node.title.casefold()
                ):
                    continue
                if len(response.items) == query.limit:
                    response.truncated = True
                    return response
                response.items.append(
                    MapLink(
                        node_id=node.id,
                        node_title=node.title,
                        level=node.level,
                        feature_id=feature.id,
                        feature_label=feature.label,
                        entity_id=feature.entity_id,
                        chapter_indices=chapters,
                    )
                )
        return response

    async def create_node(self, db, novel_id: str, data: MapNodeCreate):
        await require_active_project_exclusive(db, novel_id)
        if data.parent_id:
            parent = await self.node(db, novel_id, str(data.parent_id))
            if ATLAS_LEVEL_RANK[parent.level] >= ATLAS_LEVEL_RANK[data.level]:
                raise ValidationError("上级地图的范围必须大于当前地图")
        if data.location_entity_id:
            entity = await db.scalar(
                select(CoreEntity).where(
                    CoreEntity.novel_id == parse_uuid(novel_id, "novel_id"),
                    CoreEntity.id == data.location_entity_id,
                    CoreEntity.entity_type == "location",
                    CoreEntity.status == "canonical",
                )
            )
            if entity is None:
                raise ValidationError("请选择当前作品已采用的地点")
            semantic_key = f"entity:{entity.id}"
            existing = await db.scalar(
                select(MapAtlasNode).where(
                    MapAtlasNode.novel_id == entity.novel_id,
                    MapAtlasNode.semantic_key == semantic_key,
                )
            )
            if existing:
                return MapAtlasService._node_dict(existing, [], [])
        else:
            semantic_key = f"manual:{uuid.uuid4()}"
        node = MapAtlasNode(
            novel_id=parse_uuid(novel_id, "novel_id"),
            parent_id=data.parent_id,
            location_entity_id=data.location_entity_id,
            semantic_key=semantic_key,
            title=data.title.strip(),
            level=data.level,
            status="adopted",
        )
        db.add(node)
        await db.flush()
        await self.save(
            db,
            novel_id,
            str(node.id),
            MapSaveRequest(base_revision_id=None, document=MapDocument()),
        )
        return MapAtlasService._node_dict(node, [], [])

    async def source(self, db, novel_id: str, ref: MapSource) -> str:
        if ref.kind == "source_range":
            if (
                str(ref.source_ref.get("draft_id")) != str(ref.id)
                or ref.source_ref.get("source_hash") != ref.source_hash
            ):
                raise ValidationError("原文引用与地图来源不一致")
            try:
                result = await read_novel_evidence(
                    db,
                    novel_id=novel_id,
                    source_ref=SourceRangeRefContract(**ref.source_ref),
                    visibility=VisibilityContextContract(mode="author"),
                    before=0,
                    after=0,
                )
            except (ValueError, TypeError) as exc:
                raise ConflictError("地图原文来源已失效，请更新资料") from exc
            text = str(result.get("text") or "")
        else:
            model = CoreEntity if ref.kind == "entity" else WorldBiblePage
            item = await db.scalar(
                select(model)
                .where(
                    model.novel_id == parse_uuid(novel_id, "novel_id"), model.id == ref.id
                )
                .execution_options(populate_existing=True)
            )
            if item is None or item.status not in {"canonical", "confirmed"}:
                raise ValidationError("地图来源不存在、尚未采用或不属于当前作品")
            payload = source_payload(item)
            if source_digest(payload) != ref.source_hash:
                raise ConflictError("地图资料已经变化，请重新核对来源")
            text = source_text(payload)
        if ref.quote and ref.quote not in text:
            raise ValidationError("地图引文与来源不一致")
        return text

    async def validate_document(self, db, novel_id, node, document: MapDocument):
        for feature in document.features:
            if feature.entity_id:
                entity = await db.scalar(
                    select(CoreEntity.id).where(
                        CoreEntity.novel_id == node.novel_id,
                        CoreEntity.id == feature.entity_id,
                        CoreEntity.status == "canonical",
                    )
                )
                if entity is None:
                    raise ValidationError("地图图元必须引用当前作品已采用的对象")
            if feature.target_node_id:
                target = await self.node(db, novel_id, str(feature.target_node_id))
                if target.id == node.id or target.status != "adopted":
                    raise ValidationError("子图跳转目标无效")
        previous = (
            await self.revision(db, novel_id, str(node.id), node.current_revision_id)
            if node.current_revision_id
            else None
        )
        previous_document = (
            MapDocument.model_validate(previous.document) if previous else MapDocument()
        )
        previous_sources = {
            (type(item), item.id): {ref.model_dump_json() for ref in item.sources}
            for item in [*previous_document.features, *previous_document.constraints]
        }
        checked, problems = {}, []
        for item in [*document.features, *document.constraints]:
            for ref in item.sources:
                key = ref.model_dump_json()
                if key not in checked:
                    try:
                        await self.source(db, novel_id, ref)
                        checked[key] = None
                    except ConflictError as exc:
                        checked[key] = exc
                if checked[key] is not None:
                    if key not in previous_sources.get((type(item), item.id), set()):
                        raise checked[key]
                    ids = (
                        [item.id]
                        if hasattr(item, "points")
                        else [item.subject, item.target]
                    )
                    problems.append(
                        MapProblem(
                            code="source_stale",
                            message="已有空间资料发生变化，请核对来源；阅读预览暂不展示相关内容",
                            feature_ids=ids,
                        )
                    )
        for placement in document.images:
            page = await db.scalar(
                select(MapAtlasPage).where(
                    MapAtlasPage.novel_id == node.novel_id,
                    MapAtlasPage.node_id == node.id,
                    MapAtlasPage.id == placement.page_id,
                )
            )
            if page is None:
                raise ValidationError("图片必须属于当前地图")
            if (
                page.review_status != "adopted"
                or page.generation_status != "review_ready"
            ):
                # Retain old image references without reactivating unavailable images.
                previous = (
                    await self.revision(
                        db, novel_id, str(node.id), node.current_revision_id
                    )
                    if node.current_revision_id
                    else None
                )
                prior_images = (
                    (previous.document or {}).get("images", []) if previous else []
                )
                if placement.model_dump(mode="json") not in prior_images:
                    raise ValidationError("请先采用这张图片")
            if placement.role == "background":
                try:
                    affine_transform(placement, document)
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
                if placement.geometry_hash is None:
                    placement.geometry_hash = geometry_hash(document)
                elif placement.geometry_hash != geometry_hash(document):
                    previous = (
                        await self.revision(
                            db, novel_id, str(node.id), node.current_revision_id
                        )
                        if node.current_revision_id
                        else None
                    )
                    prior = (
                        next(
                            (
                                item
                                for item in (previous.document or {}).get("images", [])
                                if item.get("page_id") == str(page.id)
                            ),
                            None,
                        )
                        if previous
                        else None
                    )
                    if (
                        prior is None
                        or prior.get("geometry_hash") != placement.geometry_hash
                    ):
                        raise ValidationError("底图校准必须绑定当前空间版本")
            if (
                placement.reader_from_chapter is not None
                and placement.reader_image_hash != page.sha256
            ):
                raise ConflictError("图片已变化，需重新确认整图的阅读展示范围")
        for binding in document.annotation_bindings:
            annotation = await db.scalar(
                select(MapAtlasAnnotation.id)
                .join(MapAtlasPage, MapAtlasPage.id == MapAtlasAnnotation.page_id)
                .where(
                    MapAtlasAnnotation.novel_id == node.novel_id,
                    MapAtlasPage.novel_id == node.novel_id,
                    MapAtlasPage.node_id == node.id,
                    MapAtlasAnnotation.id == binding.annotation_id,
                )
            )
            if annotation is None:
                raise ValidationError("标注不属于当前地图")

        return problems

    async def save(
        self,
        db,
        novel_id: str,
        node_id: str,
        data: MapSaveRequest,
        *,
        _trusted_generation: bool = False,
    ):
        await require_active_project_exclusive(db, novel_id)
        node = await self.node(db, novel_id, node_id, lock=True)
        if node.level not in STRUCTURE_LEVELS:
            raise ValidationError("空间图支持区域、城市、街区和街道，原图片仍可浏览")
        if node.current_revision_id != data.base_revision_id:
            raise ConflictError("地图已在别处更新；当前编辑仍保留，请先比较版本")
        document = data.document.model_copy(deep=True)
        if not _trusted_generation:
            previous = (
                await self.revision(db, novel_id, node_id, node.current_revision_id)
                if node.current_revision_id
                else None
            )
            prior = (
                {
                    item.id: item
                    for item in MapDocument.model_validate(previous.document).constraints
                }
                if previous
                else {}
            )
            for item in document.constraints:
                if item.generated_by_task_id is None:
                    continue
                old = prior.get(item.id)
                if old is None or old.generated_by_task_id != item.generated_by_task_id:
                    raise ValidationError("手工保存不能指定空间提取任务来源")
                if old != item:
                    # An author edit owns the relation from now on.
                    item.generated_by_task_id = None
        source_problems = await self.validate_document(db, novel_id, node, document)
        row = MapAtlasRevision(
            novel_id=node.novel_id,
            node_id=node.id,
            base_revision_id=node.current_revision_id,
            status="saved",
            document=document.model_dump(mode="json"),
            geometry_hash=geometry_hash(document),
            problems=[p.model_dump() for p in [*diagnose(document), *source_problems]],
        )
        db.add(row)
        await db.flush()
        node.current_revision_id = row.id
        await MapAtlasService()._adopt_ancestors(db, node)
        await db.flush()
        return self.response(row)

    async def history(self, db, novel_id, node_id):
        await self.node(db, novel_id, node_id)
        rows = (
            await db.scalars(
                select(MapAtlasRevision)
                .where(
                    MapAtlasRevision.novel_id == parse_uuid(novel_id, "novel_id"),
                    MapAtlasRevision.node_id == parse_uuid(node_id, "node_id"),
                )
                .order_by(MapAtlasRevision.created_at.desc(), MapAtlasRevision.id.desc())
                .limit(50)
            )
        ).all()
        return [self.response(row) for row in rows]

    async def preview_revision(self, db, novel_id, node_id, revision_id):
        await self.node(db, novel_id, node_id)
        row = await self.revision(db, novel_id, node_id, revision_id)
        document = MapDocument.model_validate(row.document)
        problems = list(row.problems)
        for item in [*document.features, *document.constraints]:
            for source in item.sources:
                try:
                    await self.source(db, novel_id, source)
                except (ConflictError, ValidationError):
                    problems.append(
                        {
                            "code": "source_stale",
                            "message": "此版本的部分来源已变化或不可用，请核对后再使用",
                            "feature_ids": [item.id]
                            if hasattr(item, "points")
                            else [item.subject, item.target],
                        }
                    )
                    break
        return MapLayoutResponse(
            document=document,
            geometry_hash=row.geometry_hash,
            problems=problems,
            image_layers=await self.image_layers(db, novel_id, node_id, document),
        )

    async def _adoption_document(self, db, novel_id, node_id, node, row, data):
        from modules.world.map_structure_review import (
            apply_revision_changes,
            document_items,
        )

        if node.current_revision_id != data.base_revision_id:
            raise ConflictError("地图已更新，请重新比较后再操作")
        if row.status != "candidate" or row.base_revision_id != node.current_revision_id:
            raise ConflictError("候选基于旧地图，请重新生成或手动比较")
        if not row.confirmation_id:
            raise ConflictError("候选缺少原参考资料确认，请重新生成")
        try:
            prepared = await prepare_confirmed_ai_action(
                db,
                novel_id=novel_id,
                action=MAP_ACTION,
                confirmation_id=str(row.confirmation_id),
            )
        except ValueError as exc:
            raise ConflictError("候选参考资料已经失效，请重新生成") from exc
        if prepared.confirmation.context_fingerprint != row.context_fingerprint:
            raise ConflictError("候选来源已变化，请重新生成")
        candidate = MapDocument.model_validate(row.document)
        baseline = (
            MapDocument.model_validate(
                (
                    await self.revision(db, novel_id, node_id, row.base_revision_id)
                ).document
            )
            if row.base_revision_id
            else MapDocument()
        )
        document, applied, expanded = apply_revision_changes(
            baseline, candidate, data.change_keys
        )
        items = document_items(document)
        for key in applied:
            item = items.get(key)
            if item is not None and key.startswith(("feature:", "constraint:")):
                for source in item.sources:
                    await self.source(db, novel_id, source)
        return document, applied, expanded

    async def review_preview(
        self, db, novel_id, node_id, revision_id, data: MapRevisionReview
    ):
        from modules.world.map_structure_schemas import MapReviewPreview

        if data.action != "adopt":
            raise ValidationError("采用范围预览只接受采用操作")
        node = await self.node(db, novel_id, node_id)
        row = await self.revision(db, novel_id, node_id, revision_id)
        _, applied, expanded = await self._adoption_document(
            db, novel_id, node_id, node, row, data
        )
        return MapReviewPreview(
            candidate_revision_id=str(row.id),
            base_revision_id=str(row.base_revision_id) if row.base_revision_id else None,
            applied_change_keys=applied,
            expanded_change_keys=expanded,
        )

    async def review(self, db, novel_id, node_id, revision_id, data: MapRevisionReview):
        from modules.world.map_structure_review import changed_items

        await require_active_project_exclusive(db, novel_id)
        node = await self.node(db, novel_id, node_id, lock=True)
        row = await self.revision(db, novel_id, node_id, revision_id)
        if data.action == "reject":
            if row.status != "candidate":
                raise ConflictError("只能拒绝尚未采用的候选")
            row.status = "rejected"
            await db.flush()
            return self.response(row)
        if node.current_revision_id != data.base_revision_id:
            raise ConflictError("地图已更新，请重新比较后再操作")
        candidate = MapDocument.model_validate(row.document)
        document, applied, expanded = candidate, [], []
        if data.action == "adopt":
            document, applied, expanded = await self._adoption_document(
                db, novel_id, node_id, node, row, data
            )
        elif row.status != "saved":
            raise ConflictError("只能恢复已保存的历史版本")
        result = await self.save(
            db,
            novel_id,
            node_id,
            MapSaveRequest(
                base_revision_id=data.base_revision_id,
                document=document,
            ),
            _trusted_generation=True,
        )
        if data.action == "adopt":
            result.applied_change_keys = applied
            result.expanded_change_keys = expanded
            if changed_items(document, candidate):
                # The original complete candidate was never fully adopted. Retire it
                # without making its unchecked remainder restorable as saved history.
                row.status = "rejected"
                remaining = MapAtlasRevision(
                    novel_id=row.novel_id,
                    node_id=row.node_id,
                    base_revision_id=uuid.UUID(result.id),
                    status="candidate",
                    document=candidate.model_dump(mode="json"),
                    geometry_hash=geometry_hash(candidate),
                    problems=list(row.problems),
                    confirmation_id=row.confirmation_id,
                    context_fingerprint=row.context_fingerprint,
                )
                # The remaining full candidate retains the same dependency-valid
                # document and exact confirmation; only its comparison base changes.
                db.add(remaining)
                await db.flush()
                result.remaining_candidate_id = str(remaining.id)
            else:
                row.status = "saved"
        await db.flush()
        return result

    async def image_layers(self, db, novel_id, node_id, document):
        layers = []
        fingerprint = geometry_hash(document)
        for placement in document.images:
            page = await db.scalar(
                select(MapAtlasPage).where(
                    MapAtlasPage.novel_id == parse_uuid(novel_id, "novel_id"),
                    MapAtlasPage.node_id == parse_uuid(node_id, "node_id"),
                    MapAtlasPage.id == placement.page_id,
                )
            )
            state = "ready"
            if (
                page is None
                or page.review_status != "adopted"
                or page.generation_status != "review_ready"
            ):
                state = "unavailable"
            elif (
                placement.role == "background" and placement.geometry_hash != fingerprint
            ):
                state = "stale"
            transform = None
            if state == "ready" and placement.role == "background":
                try:
                    transform = affine_transform(placement, document)
                except ValueError:
                    state = "stale"
            calibration_revision_id = None
            calibration_status = None
            if placement.role == "background":
                calibration_status = "not_found"
                if page is not None and placement.geometry_hash:
                    # ponytail: inspect 100 matching versions; add an indexed image
                    # lookup if long histories regularly exhaust this visible cap.
                    history = (
                        await db.execute(
                            select(
                                MapAtlasRevision.id,
                                MapAtlasRevision.document["images"].label("images"),
                            )
                            .where(
                                MapAtlasRevision.novel_id
                                == parse_uuid(novel_id, "novel_id"),
                                MapAtlasRevision.node_id
                                == parse_uuid(node_id, "node_id"),
                                MapAtlasRevision.status == "saved",
                                MapAtlasRevision.geometry_hash == placement.geometry_hash,
                            )
                            .order_by(
                                MapAtlasRevision.created_at.desc(),
                                MapAtlasRevision.id.desc(),
                            )
                            .limit(_CALIBRATION_HISTORY_LIMIT + 1)
                        )
                    ).all()
                    anchors = [
                        anchor.model_dump(mode="json") for anchor in placement.anchors
                    ]
                    for version in history[:_CALIBRATION_HISTORY_LIMIT]:
                        if any(
                            isinstance(item, dict)
                            and item.get("page_id") == str(placement.page_id)
                            and item.get("role") == "background"
                            and item.get("geometry_hash") == placement.geometry_hash
                            and item.get("anchors") == anchors
                            for item in (version.images or [])
                        ):
                            calibration_revision_id = str(version.id)
                            calibration_status = "found"
                            break
                    else:
                        if len(history) > _CALIBRATION_HISTORY_LIMIT:
                            calibration_status = "truncated"
            layers.append(
                {
                    "page_id": str(placement.page_id),
                    "role": placement.role,
                    "feature_id": placement.feature_id,
                    "state": state,
                    "transform": transform,
                    "opacity": placement.opacity,
                    "image_hash": page.sha256 if page else None,
                    "calibration_revision_id": calibration_revision_id,
                    "calibration_lookup_status": calibration_status,
                }
            )
        return layers

    async def get_map(self, db, novel_id, node_id):
        node = await self.node(db, novel_id, node_id)
        current = (
            await self.revision(db, novel_id, node_id, node.current_revision_id)
            if node.current_revision_id
            else None
        )
        candidates = (
            await db.scalars(
                select(MapAtlasRevision)
                .where(
                    MapAtlasRevision.novel_id == node.novel_id,
                    MapAtlasRevision.node_id == node.id,
                    MapAtlasRevision.status == "candidate",
                )
                .order_by(MapAtlasRevision.created_at.desc())
                .limit(10)
            )
        ).all()
        revision = self.response(current) if current else None
        candidate_responses = [self.response(row) for row in candidates]
        checked = {}
        for response in [revision, *candidate_responses]:
            if response is None:
                continue
            response.problems = [p for p in response.problems if p.code != "source_stale"]
            for item in [*response.document.features, *response.document.constraints]:
                for ref in item.sources:
                    key = ref.model_dump_json()
                    if key not in checked:
                        try:
                            await self.source(db, novel_id, ref)
                            checked[key] = True
                        except (ConflictError, NotFoundError, ValidationError):
                            checked[key] = False
                    if not checked[key]:
                        response.problems.append(
                            MapProblem(
                                code="source_stale",
                                message="已有空间资料发生变化，请核对来源；阅读预览暂不展示相关内容",
                                feature_ids=[item.id]
                                if hasattr(item, "points")
                                else [item.subject, item.target],
                            )
                        )
                        break
        tasks = (
            await list_task_lifecycle_contracts(
                db,
                task_ids=[str(node.structure_task_id)],
                novel_id=novel_id,
                max_heartbeat_gap=TASK_MAX_HEARTBEAT_GAP,
            )
            if node.structure_task_id
            else {}
        )
        task = tasks.get(str(node.structure_task_id))
        summary = None
        if task and task.status == "done":
            completed = await get_completed_task_payload(
                db,
                task_id=str(node.structure_task_id),
                task_type=MAP_TASK,
                novel_id=novel_id,
            )
            if completed and isinstance(completed.result.get("summary"), dict):
                summary = MapExtractionSummary.model_validate(completed.result["summary"])
        return MapNodeMapResponse(
            node_id=node_id,
            revision=revision,
            task_id=str(node.structure_task_id) if node.structure_task_id else None,
            task_status=task.status if task else None,
            generation_summary=summary,
            candidates=candidate_responses,
            image_layers=await self.image_layers(
                db, novel_id, node_id, MapDocument.model_validate(current.document)
            )
            if current
            else [],
        )

    async def preview_layout(self, db, novel_id, node_id, data: MapSaveRequest):
        node = await self.node(db, novel_id, node_id)
        if node.current_revision_id != data.base_revision_id:
            raise ConflictError("地图已更新，请先比较版本")
        document = data.document.model_copy(deep=True)
        source_problems = await self.validate_document(db, novel_id, node, document)
        result = layout(document)
        result.problems.extend(source_problems)
        result.image_layers = await self.image_layers(
            db, novel_id, node_id, result.document
        )
        return result

    async def reader_source_visible(self, db, novel_id, ref, visibility):
        try:
            await self.source(db, novel_id, ref)
            if ref.kind == "source_range":
                await read_novel_evidence(
                    db,
                    novel_id=novel_id,
                    source_ref=SourceRangeRefContract(**ref.source_ref),
                    visibility=visibility,
                    before=0,
                    after=0,
                )
                return True
            inspected = await inspect_novel_target(
                db,
                novel_id=novel_id,
                target_ref={"target_type": ref.kind, "target_id": str(ref.id)},
                content_mode="canonical",
                visibility=visibility,
            )
            item = inspected.get("item") or {}
            if not inspected.get("visible") or inspected.get("warnings"):
                return False
            if ref.kind == "entity":
                reveal = await get_reader_reveal_decision(
                    db,
                    novel_id=novel_id,
                    target_type="entity",
                    target_id=str(ref.id),
                    cutoff_chapter=visibility.cutoff_chapter,
                )
                if reveal.has_policy and not reveal.revealed:
                    return False
                if not reveal.has_policy and item.get("reveal_level") not in {
                    "revealed",
                    "fully_known",
                }:
                    return False
            safe_text = " ".join(
                str(item.get(key) or "")
                for key in ("name", "public_info", "reader_reveal_content")
            )
            return not ref.quote or ref.quote in safe_text
        except (ValueError, TypeError, NotFoundError, ValidationError, ConflictError):
            return False

    async def reader_preview(
        self, db, novel_id, node_id, *, chapter: int, revision_id=None
    ):
        node = await self.node(db, novel_id, node_id)
        if not (revision_id or node.current_revision_id):
            return {"features": [], "images": [], "chapter": chapter}
        row = await self.revision(
            db, novel_id, node_id, revision_id or node.current_revision_id
        )
        if row.status != "saved":
            raise NotFoundError("阅读预览只能使用已保存版本")
        document = MapDocument.model_validate(row.document)
        visibility = VisibilityContextContract(
            mode="reader", cutoff_chapter=chapter, cutoff_offset=0
        )
        blocked = {key for problem in diagnose(document) for key in problem.feature_ids}
        eligible, public_labels = set(), {}
        for feature in document.features:
            if (
                feature.id in blocked
                or feature.reader_from_chapter is None
                or feature.reader_from_chapter > chapter
            ):
                continue
            visible = True
            if feature.entity_id:
                inspected = await inspect_novel_target(
                    db,
                    novel_id=novel_id,
                    target_ref={
                        "target_type": "entity",
                        "target_id": str(feature.entity_id),
                    },
                    content_mode="canonical",
                    visibility=visibility,
                )
                item = inspected.get("item") or {}
                reveal = await get_reader_reveal_decision(
                    db,
                    novel_id=novel_id,
                    target_type="entity",
                    target_id=str(feature.entity_id),
                    cutoff_chapter=chapter,
                )
                visible = bool(inspected.get("visible")) and (
                    reveal.revealed
                    if reveal.has_policy
                    else item.get("reveal_level") in {"revealed", "fully_known"}
                )
                if visible:
                    public_labels[feature.id] = item.get("name") or feature.label
            for ref in feature.sources:
                if visible:
                    visible = await self.reader_source_visible(
                        db, novel_id, ref, visibility
                    )
            if visible:
                eligible.add(feature.id)
        # A visible line or hull must not reveal hidden dependencies.
        dependencies = {f.id: set(f.depends_on) for f in document.features}
        for constraint in document.constraints:
            group = {constraint.subject, constraint.target, *constraint.via}
            for source in constraint.sources:
                if not await self.reader_source_visible(db, novel_id, source, visibility):
                    eligible.difference_update(group)

            for key in group:
                dependencies[key].update(group - {key})
        while True:
            filtered = {key for key in eligible if dependencies[key].issubset(eligible)}
            if filtered == eligible:
                break
            eligible = filtered
        features = [
            {
                "id": f.id,
                "kind": f.kind,
                "label": public_labels.get(f.id, f.label),
                "points": [p.model_dump() for p in f.points],
            }
            for f in document.features
            if f.id in eligible
        ]
        layers = await self.image_layers(db, novel_id, node_id, document)
        images = []
        for placement, layer in zip(document.images, layers, strict=True):
            if (
                layer["state"] != "ready"
                or placement.reader_from_chapter is None
                or placement.reader_from_chapter > chapter
                or placement.reader_image_hash != layer["image_hash"]
            ):
                continue
            if placement.role == "background" and len(eligible) != len(document.features):
                continue
            if placement.feature_id and placement.feature_id not in eligible:
                continue
            if (
                not placement.feature_id
                and placement.role == "illustration"
                and len(eligible) != len(document.features)
            ):
                continue
            images.append(
                {
                    key: layer[key]
                    for key in ("page_id", "role", "feature_id", "transform", "opacity")
                }
            )
        return {"features": features, "images": images, "chapter": chapter}
