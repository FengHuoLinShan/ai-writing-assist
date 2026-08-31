"""Author-facing lifecycle for AI map-atlas runs, pages, and overlays."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.tasks.facade import enqueue_coalesced_task, enqueue_task
from modules.project.facade import (
    build_project_image_execution_snapshot,
    build_project_llm_execution_snapshot,
    require_active_project,
    require_active_project_exclusive,
)
from modules.world.map_atlas_models import (
    MapAtlasAnnotation,
    MapAtlasNode,
    MapAtlasPage,
    MapAtlasRun,
)
from modules.world.map_atlas_schemas import (
    ATLAS_LEVEL_RANK,
    MapAtlasAnnotationUpdate,
    MapAtlasConfirmPromptsRequest,
    MapAtlasDerivedRequest,
    MapAtlasEvidenceSummary,
    MapAtlasNodeProposal,
    MapAtlasNodeUpdate,
    MapAtlasPromptUpdate,
    MapAtlasReviewRequest,
    MapAtlasRunCreate,
)
from modules.world.map_atlas_storage import (
    MapAtlasStorage,
    delete_unreferenced_page_object,
    normalize_map_upload,
    page_object_key,
    require_matching_mask,
    require_owned_page_object_key,
)
from shared.utils import parse_uuid

MAP_ATLAS_TASK_TYPE = "map_atlas_generate"
ACTIVE_RUN_STATUSES = {"planning", "prompt_review", "generating"}
RECOVERABLE_RUN_ERROR_CODES = {"retry_requires_confirmation", "worker_interrupted"}
RECOVERABLE_PAGE_ERROR_CODES = {
    "possible_duplicate_charge",
    "retry_requires_confirmation",
    "worker_interrupted",
}


def _uuid(value: Any) -> str | None:
    return str(value) if value is not None else None


def _path_part(value: str) -> str:
    compact = re.sub(r"\s+", "", value).casefold()
    return hashlib.sha256(compact.encode()).hexdigest()[:20]


class MapAtlasService:
    def __init__(self, *, storage: MapAtlasStorage | None = None) -> None:
        self._storage = storage

    def _get_storage(self) -> MapAtlasStorage:
        return self._storage or MapAtlasStorage()

    async def create_run(
        self,
        db: AsyncSession,
        novel_id: str,
        data: MapAtlasRunCreate,
    ) -> dict[str, Any]:
        await require_active_project_exclusive(db, novel_id)
        active = await self._active_run(db, novel_id, for_update=True)
        if active is not None:
            return self._run_dict(active)
        llm_snapshot = await build_project_llm_execution_snapshot(db, novel_id)
        image_snapshot = (
            {}
            if data.review_image_prompts
            else await build_project_image_execution_snapshot(db, novel_id)
        )
        adopted_count = await db.scalar(
            select(func.count(MapAtlasPage.id)).where(
                MapAtlasPage.novel_id == parse_uuid(novel_id, "novel_id"),
                MapAtlasPage.review_status == "adopted",
            )
        )
        run_kind = (
            "rebuild" if data.full_rebuild else "update" if adopted_count else "initial"
        )
        run = MapAtlasRun(
            novel_id=parse_uuid(novel_id, "novel_id"),
            run_kind=run_kind,
            status="planning",
            style_note=data.style_note,
            include_working_drafts=data.include_working_drafts,
            include_interiors=data.include_interiors,
            review_image_prompts=data.review_image_prompts,
            layout=data.layout,
            quality=data.quality,
            page_limit=20,
            llm_execution_snapshot=llm_snapshot,
            image_execution_snapshot=image_snapshot,
            context_snapshot={
                "context_confirmation_id": data.context_confirmation_id,
            },
        )
        db.add(run)
        await db.flush()
        task_id = await self._enqueue_run_task(db, novel_id, run, mode="reuse_active")
        run.task_id = parse_uuid(task_id, "task_id")
        await db.flush()
        return self._run_dict(run)

    async def get_run(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        await require_active_project(db, novel_id)
        return self._run_dict(await self._require_run(db, novel_id, run_id))

    async def get_latest_run(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> dict[str, Any] | None:
        await require_active_project(db, novel_id)
        run = (
            await db.execute(
                select(MapAtlasRun)
                .where(
                    MapAtlasRun.novel_id == parse_uuid(novel_id, "novel_id"),
                    MapAtlasRun.run_kind != "upload",
                )
                .order_by(MapAtlasRun.created_at.desc(), MapAtlasRun.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return self._run_dict(run) if run is not None else None

    async def stop_run(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        await require_active_project_exclusive(db, novel_id)
        run = await self._require_run(db, novel_id, run_id, for_update=True)
        if run.status in {"failed", "review_ready", "completed"}:
            raise ConflictError("该地图册任务已经结束")
        run.stop_requested = True
        if run.status == "prompt_review":
            run.status = "paused"
        await db.flush()
        return {"run_id": str(run.id), "stop_requested": True}

    async def resume_run(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
        *,
        confirm_possible_duplicate_charge: bool,
    ) -> dict[str, Any]:
        await require_active_project_exclusive(db, novel_id)
        run = await self._require_run(db, novel_id, run_id, for_update=True)
        if run.status in {"failed", "prompt_review", "review_ready", "completed"}:
            raise ConflictError("该地图册任务无需继续")
        if run.status in {"planning", "generating"} and not run.stop_requested:
            return self._run_dict(run)
        other_active = await self._active_run(
            db, novel_id, exclude_run_id=str(run.id), for_update=True
        )
        if other_active is not None:
            raise ConflictError("当前项目已有地图册生成任务")
        in_flight = list(
            (
                await db.execute(
                    select(MapAtlasPage)
                    .where(
                        MapAtlasPage.novel_id == run.novel_id,
                        MapAtlasPage.run_id == run.id,
                        MapAtlasPage.generation_status.in_(
                            {"provider_in_flight", "retry_requires_confirmation"}
                        ),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        if in_flight and not confirm_possible_duplicate_charge:
            for page in in_flight:
                page.generation_status = "retry_requires_confirmation"
                page.error_code = "possible_duplicate_charge"
                page.error_message = "上次请求可能已经产生费用"
            await db.commit()
            raise ConflictError(
                "上次请求可能已经产生费用；确认可能重复扣费后才能继续",
                code="retry_requires_confirmation",
            )
        for page in in_flight:
            page.generation_status = "prepared"
            page.error_code = None
            page.error_message = None
        run.stop_requested = False
        if run.review_image_prompts and run.atlas_plan:
            prepared = await db.scalar(
                select(func.count(MapAtlasPage.id)).where(
                    MapAtlasPage.run_id == run.id,
                    MapAtlasPage.generation_status == "prepared",
                )
            )
            if prepared:
                run.status = "prompt_review"
                await db.flush()
                return self._run_dict(run)
        run.status = "generating" if run.atlas_plan else "planning"
        task_id = await self._enqueue_run_task(
            db, novel_id, run, mode="one_pending_follower"
        )
        run.task_id = parse_uuid(task_id, "task_id")
        await db.flush()
        return self._run_dict(run)

    async def get_tree(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        await require_active_project(db, novel_id)
        nid = parse_uuid(novel_id, "novel_id")
        run = await self._require_run(db, novel_id, run_id) if run_id else None
        page_conditions = [
            MapAtlasPage.novel_id == nid,
            MapAtlasPage.generation_status.in_(
                {"review_ready", "failed", "retry_requires_confirmation"}
                | ({"prepared", "prompt_only"} if run_id else set())
            ),
        ]
        if run is None:
            page_conditions.append(MapAtlasPage.review_status == "adopted")
        else:
            page_conditions.append(MapAtlasPage.run_id == run.id)
        pages = list(
            (
                await db.execute(
                    select(MapAtlasPage)
                    .where(*page_conditions)
                    .order_by(MapAtlasPage.sort_order, MapAtlasPage.created_at)
                )
            )
            .scalars()
            .all()
        )
        node_ids = {page.node_id for page in pages}
        nodes_by_id: dict[uuid.UUID, MapAtlasNode] = {}
        frontier = set(node_ids)
        while frontier:
            found = list(
                (
                    await db.execute(
                        select(MapAtlasNode).where(
                            MapAtlasNode.novel_id == nid,
                            MapAtlasNode.id.in_(frontier),
                        )
                    )
                )
                .scalars()
                .all()
            )
            frontier = {
                node.parent_id
                for node in found
                if node.parent_id is not None and node.parent_id not in nodes_by_id
            }
            nodes_by_id.update({node.id: node for node in found})
        annotations = (
            list(
                (
                    await db.execute(
                        select(MapAtlasAnnotation)
                        .where(
                            MapAtlasAnnotation.novel_id == nid,
                            MapAtlasAnnotation.page_id.in_([page.id for page in pages]),
                        )
                        .order_by(MapAtlasAnnotation.sort_order)
                    )
                )
                .scalars()
                .all()
            )
            if pages
            else []
        )
        adopted_targets = set(
            (
                await db.execute(
                    select(MapAtlasPage.node_id).where(
                        MapAtlasPage.novel_id == nid,
                        MapAtlasPage.review_status == "adopted",
                    )
                )
            ).scalars()
        )
        annotation_map: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for item in annotations:
            projected = self._annotation_dict(item)
            if item.target_node_id not in adopted_targets:
                projected["target_node_id"] = None
            annotation_map.setdefault(item.page_id, []).append(projected)
        page_map: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for page in pages:
            page_map.setdefault(page.node_id, []).append(
                self._page_dict(page, annotation_map.get(page.id, []))
            )
        children: dict[uuid.UUID | None, list[MapAtlasNode]] = {}
        for node in nodes_by_id.values():
            parent = node.parent_id if node.parent_id in nodes_by_id else None
            children.setdefault(parent, []).append(node)

        def project(node: MapAtlasNode) -> dict[str, Any]:
            return self._node_dict(
                node,
                page_map.get(node.id, []),
                [
                    project(child)
                    for child in sorted(
                        children.get(node.id, []),
                        key=lambda item: (item.sort_order, item.title),
                    )
                ],
            )

        roots = [
            project(node)
            for node in sorted(
                children.get(None, []),
                key=lambda item: (item.sort_order, item.title),
            )
        ]
        return {
            "mode": "review" if run else "atlas",
            "run": self._run_dict(run) if run else None,
            "nodes": roots,
            "total_pages": len(pages),
        }

    async def get_archived_pages(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[dict[str, Any]]:
        await require_active_project(db, novel_id)
        nid = parse_uuid(novel_id, "novel_id")
        latest_run_id = (
            select(MapAtlasRun.id)
            .where(MapAtlasRun.novel_id == nid, MapAtlasRun.run_kind != "upload")
            .order_by(MapAtlasRun.created_at.desc(), MapAtlasRun.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        upload_run = exists(
            select(MapAtlasRun.id).where(
                MapAtlasRun.id == MapAtlasPage.run_id,
                MapAtlasRun.novel_id == nid,
                MapAtlasRun.run_kind == "upload",
            )
        )
        pages = list(
            (
                await db.execute(
                    select(MapAtlasPage)
                    .where(
                        MapAtlasPage.novel_id == nid,
                        or_(
                            MapAtlasPage.review_status.in_({"deprecated", "rejected"}),
                            and_(
                                MapAtlasPage.review_status == "candidate",
                                MapAtlasPage.generation_status.in_(
                                    {
                                        "review_ready",
                                        "failed",
                                        "retry_requires_confirmation",
                                    }
                                ),
                                or_(upload_run, MapAtlasPage.run_id != latest_run_id),
                            ),
                        ),
                    )
                    .order_by(
                        MapAtlasPage.updated_at.desc(),
                        MapAtlasPage.created_at.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        return [self._page_dict(page, []) for page in pages]

    async def review_page(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        action: str,
        data: MapAtlasReviewRequest,
    ) -> dict[str, Any]:
        await require_active_project_exclusive(db, novel_id)
        page = await self._require_page(db, novel_id, page_id, for_update=True)
        if page.updated_at != data.expected_updated_at:
            raise ConflictError("页面已在别处更新，请刷新后重试")
        if action in {"adopt", "reject"} and (
            page.review_status != "candidate" or page.generation_status != "review_ready"
        ):
            raise ConflictError("只有生成完成的候选图片可以加入或不加入")
        if page.generation_status == "prompt_only":
            raise ConflictError("仅 Prompt 页面没有可处理的图片")
        now = datetime.now(UTC)
        if action == "adopt":
            conflicts = list((page.evidence or {}).get("conflicts") or [])
            if conflicts and not data.confirm_conflicts:
                raise ConflictError(
                    "该图片存在资料冲突；确认后才能加入地图册",
                    code="atlas_conflict_confirmation_required",
                )
            if page.generation_status != "review_ready":
                raise ConflictError("图片尚未生成完成")
            await self._adopt_proposed_path(db, page)
            page.review_status = "adopted"
            page.adopted_at = now
            page.rejected_at = None
            page.deprecated_at = None
        elif action == "reject":
            page.review_status = "rejected"
            page.rejected_at = now
        elif action == "archive":
            if page.review_status != "adopted":
                raise ConflictError("只有地图册已有图片可以移出")
            page.review_status = "deprecated"
            page.deprecated_at = now
        elif action == "restore":
            if page.review_status != "deprecated":
                raise ConflictError("只有已移出的图片可以恢复")
            page.review_status = "adopted"
            page.adopted_at = now
            page.deprecated_at = None
            await self._adopt_ancestors(db, page)
        else:
            raise ValidationError("unsupported map atlas page action")
        page.review_note = data.review_note
        await db.flush()
        return self._page_dict(page, [])

    async def update_annotation(
        self,
        db: AsyncSession,
        novel_id: str,
        annotation_id: str,
        data: MapAtlasAnnotationUpdate,
    ) -> dict[str, Any]:
        await require_active_project(db, novel_id)
        nid = parse_uuid(novel_id, "novel_id")
        item = (
            await db.execute(
                select(MapAtlasAnnotation)
                .where(
                    MapAtlasAnnotation.novel_id == nid,
                    MapAtlasAnnotation.id == parse_uuid(annotation_id, "annotation_id"),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if item is None:
            raise NotFoundError("地图标注不存在")
        if item.updated_at != data.expected_updated_at:
            raise ConflictError("标注已在别处更新，请刷新后重试")
        patch = data.model_dump(exclude={"expected_updated_at"}, exclude_unset=True)
        if patch.get("target_node_id"):
            target_id = parse_uuid(patch["target_node_id"], "target_node_id")
            adopted = await db.scalar(
                select(func.count(MapAtlasPage.id)).where(
                    MapAtlasPage.novel_id == nid,
                    MapAtlasPage.node_id == target_id,
                    MapAtlasPage.review_status == "adopted",
                )
            )
            if not adopted:
                raise ValidationError("目标地点加入地图册后才能建立跳转")
            patch["target_node_id"] = target_id
        for key, value in patch.items():
            setattr(item, key, value)
        await db.flush()
        return self._annotation_dict(item)

    async def get_prompt(
        self, db: AsyncSession, novel_id: str, page_id: str
    ) -> dict[str, Any]:
        await require_active_project(db, novel_id)
        page = await self._require_page(db, novel_id, page_id)
        run = await self._require_run(db, novel_id, str(page.run_id))
        return self._prompt_dict(
            page, run.status == "prompt_review" and page.generation_status == "prepared"
        )

    async def update_prompt(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        data: MapAtlasPromptUpdate,
    ) -> dict[str, Any]:
        await require_active_project_exclusive(db, novel_id)
        page = await self._require_page(db, novel_id, page_id, for_update=True)
        run = await self._require_run(db, novel_id, str(page.run_id), for_update=True)
        if run.status != "prompt_review" or page.generation_status != "prepared":
            raise ConflictError("Prompt 已锁定，无法继续修改")
        if page.updated_at != data.expected_updated_at:
            raise ConflictError("Prompt 已在别处更新，请刷新后重试")
        page.prompt = data.prompt
        page.generation_choice = data.generation_choice
        await db.flush()
        return self._prompt_dict(page, True)

    async def confirm_prompts(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
        data: MapAtlasConfirmPromptsRequest,
    ) -> dict[str, Any]:
        await require_active_project_exclusive(db, novel_id)
        run = await self._require_run(db, novel_id, run_id, for_update=True)
        if run.status != "prompt_review":
            raise ConflictError("该任务不在 Prompt 确认阶段")
        pages = list(
            (
                await db.execute(
                    select(MapAtlasPage)
                    .where(
                        MapAtlasPage.novel_id == run.novel_id,
                        MapAtlasPage.run_id == run.id,
                    )
                    .order_by(MapAtlasPage.sort_order, MapAtlasPage.id)
                    .with_for_update()
                )
            ).scalars()
        )
        expected = {item.page_id: item.expected_updated_at for item in data.pages}
        if {page.id for page in pages} != set(expected):
            raise ConflictError("必须确认本次的全部 Prompt")
        if any(page.generation_status != "prepared" for page in pages):
            raise ConflictError("Prompt 页面状态已变化，请刷新后重试")
        if any(page.updated_at != expected[page.id] for page in pages):
            raise ConflictError("Prompt 已在别处更新，请刷新后重试")
        internal = [page for page in pages if page.generation_choice == "internal"]
        if not internal:
            for page in pages:
                page.generation_status = "prompt_only"
            run.completed_page_count = len(pages)
            run.status = "review_ready"
            await db.flush()
            return self._run_dict(run)
        # Build the image connection only after the author has confirmed prompts.
        # Failure leaves the durable prompt-review state untouched.
        image_snapshot = await build_project_image_execution_snapshot(db, novel_id)
        for page in pages:
            if page.generation_choice == "external":
                page.generation_status = "prompt_only"
        run.image_execution_snapshot = image_snapshot
        run.completed_page_count = len(pages) - len(internal)
        run.status = "generating"
        task_id = await self._enqueue_run_task(
            db, novel_id, run, mode="one_pending_follower"
        )
        run.task_id = parse_uuid(task_id, "task_id")
        await db.flush()
        return self._run_dict(run)

    async def upload_page(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        payload: bytes,
        title: str | None,
        level: str | None,
        parent_id: str | None,
        node_id: str | None,
    ) -> dict[str, Any]:
        await require_active_project(db, novel_id)
        try:
            normalized, metadata = await asyncio.to_thread(normalize_map_upload, payload)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        nid = parse_uuid(novel_id, "novel_id")
        run_id, page_id = uuid.uuid4(), uuid.uuid4()
        key = page_object_key(novel_id, str(page_id), attempt_token=str(uuid.uuid4()))
        storage = self._get_storage()
        uploaded = False
        try:
            await storage.put_png(key, normalized)
            uploaded = True
            await require_active_project_exclusive(db, novel_id)
            if await self._active_run(db, novel_id, for_update=True) is not None:
                raise ConflictError("当前项目已有地图册生成任务")
            parent = None
            if parent_id:
                parent = await self._require_adopted_node(db, nid, parent_id)
            if node_id:
                node = await self._require_adopted_node(db, nid, node_id)
                if parent_id is not None or level is not None or title is not None:
                    raise ValidationError("选择已有地点时不能重写其层级信息")
                page_title = node.title
            else:
                page_title = (title or "").strip()
                if not page_title or level is None:
                    raise ValidationError("新地点必须填写名称和层级")
                if level in {"cover", "world"} and parent is not None:
                    raise ValidationError("封面与世界图不能有上级地图")
                if parent and ATLAS_LEVEL_RANK[parent.level] >= ATLAS_LEVEL_RANK[level]:
                    raise ValidationError("地图上下级层级无效")
                node = MapAtlasNode(
                    id=uuid.uuid4(),
                    novel_id=nid,
                    created_by_run_id=run_id,
                    parent_id=parent.id if parent else None,
                    semantic_key=f"manual:{uuid.uuid4()}",
                    title=page_title,
                    level=level,
                    status="provisional",
                    sort_order=0,
                )
            run = MapAtlasRun(
                id=run_id,
                novel_id=nid,
                run_kind="upload",
                status="review_ready",
                planned_page_count=1,
                completed_page_count=1,
            )
            page = MapAtlasPage(
                id=page_id,
                novel_id=nid,
                run_id=run.id,
                node_id=node.id,
                generation_status="review_ready",
                generation_choice="external",
                title=page_title,
                visual_brief="用户上传的地图",
                prompt="用户上传",
                node_proposal=(
                    MapAtlasNodeProposal(
                        node_id=node.id,
                        parent_id=node.parent_id,
                        title=node.title,
                        level=node.level,
                        summary=node.summary,
                        sort_order=node.sort_order,
                    ).model_dump(mode="json")
                    if node.status == "provisional"
                    else {}
                ),
                object_key=key,
                sha256=metadata.sha256,
                media_type="image/png",
                width=metadata.width,
                height=metadata.height,
                byte_size=metadata.byte_size,
                provider="user",
                model="external",
            )
            db.add_all([run, node, page] if node_id is None else [run, page])
            await db.flush()
            return self._page_dict(page, [])
        except BaseException:
            await db.rollback()
            if uploaded:
                await self._compensate_upload(db, storage, key)
            raise

    async def update_node(
        self,
        db: AsyncSession,
        novel_id: str,
        node_id: str,
        data: MapAtlasNodeUpdate,
    ) -> dict[str, Any]:
        await require_active_project_exclusive(db, novel_id)
        nid = parse_uuid(novel_id, "novel_id")
        nodes = list(
            (
                await db.execute(
                    select(MapAtlasNode)
                    .where(MapAtlasNode.novel_id == nid)
                    .order_by(MapAtlasNode.id)
                    .with_for_update()
                )
            ).scalars()
        )
        by_id = {item.id: item for item in nodes}
        node = by_id.get(parse_uuid(node_id, "node_id"))
        if node is None:
            raise NotFoundError("地图节点不存在")
        if node.updated_at != data.expected_updated_at:
            raise ConflictError("地图层级已在别处更新，请刷新后重试")
        run = await self._require_run(db, novel_id, str(node.created_by_run_id))
        if node.status == "provisional" and run.run_kind != "upload":
            raise ConflictError("该候选节点不能手动调整")
        if node.status == "adopted" and "title" in data.model_fields_set:
            raise ValidationError("已加入地图册的地点不能在此改名")
        new_parent_id = (
            data.parent_id if "parent_id" in data.model_fields_set else node.parent_id
        )
        new_level = data.level or node.level
        if new_parent_id == node.id:
            raise ValidationError("地图节点不能成为自己的上级")
        parent = by_id.get(new_parent_id) if new_parent_id else None
        if new_parent_id and (parent is None or parent.status != "adopted"):
            raise ValidationError("上级地图必须是已加入的地点")
        if new_level in {"cover", "world"} and parent is not None:
            raise ValidationError("封面与世界图不能有上级地图")
        if parent and ATLAS_LEVEL_RANK[parent.level] >= ATLAS_LEVEL_RANK[new_level]:
            raise ValidationError("地图上下级层级无效")
        cursor = parent
        while cursor is not None:
            if cursor.id == node.id:
                raise ValidationError("地图层级不能形成循环")
            cursor = by_id.get(cursor.parent_id) if cursor.parent_id else None
        children = [item for item in nodes if item.parent_id == node.id]
        if any(
            ATLAS_LEVEL_RANK[new_level] >= ATLAS_LEVEL_RANK[item.level]
            for item in children
        ):
            raise ValidationError("地图上下级层级无效")
        before_supplied = "before_node_id" in data.model_fields_set
        before = by_id.get(data.before_node_id) if data.before_node_id else None
        if before and (
            before.id == node.id
            or before.parent_id != new_parent_id
            or before.status != "adopted"
        ):
            raise ValidationError("插入位置必须是同一上级下的已加入地点")
        old_parent_id = node.parent_id
        old_semantic = node.semantic_key
        node.parent_id = new_parent_id
        node.level = new_level
        if data.title is not None:
            node.title = data.title.strip()
        if old_semantic.startswith("path:") and (
            new_parent_id != old_parent_id or data.title is not None
        ):
            parent_semantic = parent.semantic_key if parent else "root"
            replacement = f"path:{parent_semantic}:{_path_part(node.title)}"
            rewrites = {
                item.id: replacement + item.semantic_key[len(old_semantic) :]
                for item in nodes
                if item.semantic_key == old_semantic
                or item.semantic_key.startswith(f"{old_semantic}:")
            }
            untouched = {item.semantic_key for item in nodes if item.id not in rewrites}
            if (
                len(set(rewrites.values())) != len(rewrites)
                or set(rewrites.values()) & untouched
            ):
                raise ConflictError("移动后的地图路径与已有地点冲突")
            for item in nodes:
                if item.id in rewrites:
                    item.semantic_key = rewrites[item.id]
        target_adopted = [
            item
            for item in nodes
            if item.id != node.id
            and item.parent_id == new_parent_id
            and item.status == "adopted"
        ]
        target_adopted.sort(key=lambda item: (item.sort_order, item.id))
        if before_supplied:
            desired_index = (
                target_adopted.index(before)
                if before in target_adopted
                else len(target_adopted)
            )
        elif new_parent_id == old_parent_id:
            desired_index = min(node.sort_order, len(target_adopted))
        else:
            desired_index = min(node.sort_order, len(target_adopted))
        if node.status == "adopted":
            target_adopted.insert(desired_index, node)
            for index, item in enumerate(target_adopted):
                item.sort_order = index
            if old_parent_id != new_parent_id:
                old_siblings = [
                    item
                    for item in nodes
                    if item.id != node.id
                    and item.parent_id == old_parent_id
                    and item.status == "adopted"
                ]
                old_siblings.sort(key=lambda item: (item.sort_order, item.id))
                for index, item in enumerate(old_siblings):
                    item.sort_order = index
        else:
            node.sort_order = desired_index
        if node.status == "provisional":
            page = await db.scalar(
                select(MapAtlasPage)
                .where(
                    MapAtlasPage.novel_id == nid,
                    MapAtlasPage.run_id == run.id,
                    MapAtlasPage.node_id == node.id,
                )
                .with_for_update()
            )
            if page is not None:
                page.title = node.title
                page.node_proposal = MapAtlasNodeProposal(
                    node_id=node.id,
                    parent_id=node.parent_id,
                    title=node.title,
                    level=node.level,
                    summary=node.summary,
                    sort_order=node.sort_order,
                    base_node_updated_at=node.updated_at,
                ).model_dump(mode="json")
        await db.flush()
        return self._node_dict(node, [], [])

    async def read_page_image(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
    ) -> AsyncIterator[bytes]:
        await require_active_project(db, novel_id)
        page = await self._require_page(db, novel_id, page_id)
        if not page.object_key or page.generation_status not in {
            "uploaded",
            "review_ready",
        }:
            raise NotFoundError("地图图片不存在")
        key = require_owned_page_object_key(
            page.object_key,
            str(page.novel_id),
            str(page.id),
        )
        return self._get_storage().iter_png_chunks(key)

    async def retry_page(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        *,
        confirm_possible_duplicate_charge: bool,
    ) -> dict[str, Any]:
        await require_active_project_exclusive(db, novel_id)
        page = await self._require_page(db, novel_id, page_id, for_update=True)
        if page.generation_status not in {"failed", "retry_requires_confirmation"}:
            raise ConflictError("该图片当前不需要重试")
        if (
            page.generation_status == "retry_requires_confirmation"
            and not confirm_possible_duplicate_charge
        ):
            raise ConflictError(
                "上次请求可能已经产生费用；确认可能重复扣费后才能重试",
                code="retry_requires_confirmation",
            )
        run = await self._require_run(
            db,
            novel_id,
            str(page.run_id),
            for_update=True,
        )
        other_active = await self._active_run(
            db, novel_id, exclude_run_id=str(run.id), for_update=True
        )
        if other_active is not None:
            raise ConflictError("当前项目已有地图册生成任务")
        page.generation_status = "prepared"
        page.error_code = None
        page.error_message = None
        run.status = "generating"
        run.error_code = None
        run.error_message = None
        task_id = await self._enqueue_run_task(
            db, novel_id, run, mode="one_pending_follower"
        )
        run.task_id = parse_uuid(task_id, "task_id")
        await db.flush()
        return self._page_dict(page, [])

    async def create_derived_page(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        data: MapAtlasDerivedRequest,
        *,
        mode: str,
        mask: bytes | None = None,
    ) -> dict[str, Any]:
        await require_active_project(db, novel_id)
        source = await self._require_page(db, novel_id, page_id)
        if not source.object_key or source.generation_status != "review_ready":
            raise ConflictError("来源图片尚不可编辑")
        source_key = require_owned_page_object_key(
            source.object_key,
            str(source.novel_id),
            str(source.id),
        )
        if mode == "edit" and not data.instruction:
            raise ValidationError("请输入希望 AI 修改的内容")
        references = await self._require_reference_pages(
            db,
            novel_id,
            [page_id, *data.reference_page_ids],
        )
        image_snapshot = await build_project_image_execution_snapshot(db, novel_id)
        run = MapAtlasRun(
            id=uuid.uuid4(),
            novel_id=source.novel_id,
            run_kind="edit" if mode == "edit" else "regenerate",
            status="generating",
            style_note=None,
            layout="landscape" if source.width != source.height else "square",
            quality="standard",
            page_limit=1,
            planned_page_count=1,
            image_execution_snapshot=image_snapshot,
        )
        derived = MapAtlasPage(
            id=uuid.uuid4(),
            novel_id=source.novel_id,
            run_id=run.id,
            node_id=source.node_id,
            derived_from_page_id=source.id,
            title=source.title,
            visual_brief=source.visual_brief,
            prompt=source.prompt,
            edit_instruction=data.instruction,
            node_proposal=dict(source.node_proposal or {}),
            evidence=dict(source.evidence or {}),
            source_manifest=list(source.source_manifest or []),
            reference_page_ids=[str(page.id) for page in references],
            sort_order=0,
        )
        storage = self._get_storage()
        uploaded_mask_key: str | None = None
        try:
            if mask is not None:
                source_bytes = await storage.get_png(source_key)
                require_matching_mask(source_bytes, mask)
                uploaded_mask_key = page_object_key(
                    novel_id,
                    str(derived.id),
                    mask=True,
                )
                await storage.put_png(uploaded_mask_key, mask)
                derived.mask_object_key = uploaded_mask_key
            # Release the shared project lock before taking the short exclusive
            # creation fence. The uploaded mask remains covered by exact-key
            # compensation if deletion or another run wins between the locks.
            await db.commit()
            await require_active_project_exclusive(db, novel_id)
            if await self._active_run(db, novel_id, for_update=True) is not None:
                raise ConflictError("当前项目已有地图册生成任务")
            db.add(run)
            db.add(derived)
            await db.flush()
            task_id = await self._enqueue_run_task(db, novel_id, run, mode="reuse_active")
            run.task_id = parse_uuid(task_id, "task_id")
            await db.commit()
        except BaseException:
            await db.rollback()
            if uploaded_mask_key:
                try:
                    await delete_unreferenced_page_object(
                        db,
                        storage,
                        uploaded_mask_key,
                    )
                except Exception:
                    await db.rollback()
                    enqueue_task(
                        db,
                        "map_atlas_storage_cleanup",
                        meta={
                            "cleanup_kind": "object",
                            "object_key": uploaded_mask_key,
                            "delete_batch": str(uuid.uuid4()),
                        },
                        novel_id=None,
                    )
                    await db.commit()
            raise
        return self._page_dict(derived, [])

    async def _require_reference_pages(
        self,
        db: AsyncSession,
        novel_id: str,
        page_ids: list[str],
    ) -> list[MapAtlasPage]:
        unique_ids = list(dict.fromkeys(page_ids))
        parsed = [parse_uuid(item, "reference_page_id") for item in unique_ids]
        result = list(
            (
                await db.execute(
                    select(MapAtlasPage).where(
                        MapAtlasPage.novel_id == parse_uuid(novel_id, "novel_id"),
                        MapAtlasPage.id.in_(parsed),
                        MapAtlasPage.generation_status == "review_ready",
                        MapAtlasPage.object_key.isnot(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {item.id: item for item in result}
        if any(item not in by_id for item in parsed):
            raise ValidationError("参考图片不存在、未完成或不属于当前项目")
        ordered = [by_id[item] for item in parsed]
        for page in ordered:
            require_owned_page_object_key(
                str(page.object_key or ""),
                str(page.novel_id),
                str(page.id),
            )
        return ordered

    async def _adopt_ancestors(self, db: AsyncSession, page: MapAtlasPage) -> None:
        node_id: uuid.UUID | None = page.node_id
        seen: set[uuid.UUID] = set()
        while node_id is not None:
            if node_id in seen:
                raise ConflictError("地图层级存在循环")
            seen.add(node_id)
            node = (
                await db.execute(
                    select(MapAtlasNode)
                    .where(
                        MapAtlasNode.novel_id == page.novel_id,
                        MapAtlasNode.id == node_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if node is None:
                raise ConflictError("地图层级已变化，请刷新后重试")
            node.status = "adopted"
            node_id = node.parent_id

    async def _adopt_proposed_path(
        self,
        db: AsyncSession,
        page: MapAtlasPage,
    ) -> None:
        nodes = list(
            (
                await db.execute(
                    select(MapAtlasNode)
                    .where(MapAtlasNode.novel_id == page.novel_id)
                    .order_by(MapAtlasNode.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        nodes_by_id = {node.id: node for node in nodes}
        run_pages = list(
            (
                await db.execute(
                    select(MapAtlasPage)
                    .where(
                        MapAtlasPage.novel_id == page.novel_id,
                        MapAtlasPage.run_id == page.run_id,
                    )
                    .order_by(MapAtlasPage.sort_order, MapAtlasPage.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        proposals: dict[uuid.UUID, MapAtlasNodeProposal] = {}
        for candidate in run_pages:
            raw = candidate.node_proposal or {}
            if not raw:
                continue
            try:
                proposal = MapAtlasNodeProposal.model_validate(raw)
            except (TypeError, ValueError) as exc:
                raise ConflictError("地图层级候选数据已损坏") from exc
            if proposal.node_id != candidate.node_id:
                raise ConflictError("地图层级候选已变化，请刷新后重试")
            existing = proposals.get(candidate.node_id)
            if existing is not None and existing != proposal:
                raise ConflictError("同一地点存在冲突的层级候选")
            proposals[candidate.node_id] = proposal

        selected_proposal = proposals.get(page.node_id)
        path: list[tuple[MapAtlasNode, MapAtlasNodeProposal | None]] = []
        seen: set[uuid.UUID] = set()
        node_id: uuid.UUID | None = page.node_id
        while node_id is not None:
            if node_id in seen:
                raise ConflictError("地图层级存在循环")
            seen.add(node_id)
            node = nodes_by_id.get(node_id)
            if node is None:
                raise ConflictError("地图层级已变化，请刷新后重试")
            proposal = (
                selected_proposal if node_id == page.node_id else proposals.get(node_id)
            )
            parent_id = proposal.parent_id if proposal is not None else node.parent_id
            if (
                proposal is not None
                and proposal.level in {"cover", "world"}
                and parent_id
            ):
                raise ConflictError("封面与世界图不能有上级地图")
            if parent_id is not None:
                if parent_id in seen:
                    raise ConflictError("地图层级存在循环")
                parent = nodes_by_id.get(parent_id)
                if parent is None:
                    raise ConflictError("地图层级已变化，请刷新后重试")
                parent_proposal = proposals.get(parent_id)
                parent_level = (
                    parent_proposal.level if parent_proposal is not None else parent.level
                )
                node_level = proposal.level if proposal is not None else node.level
                if ATLAS_LEVEL_RANK[parent_level] >= ATLAS_LEVEL_RANK[node_level]:
                    raise ConflictError("地图上下级层级无效")
            path.append((node, proposal))
            node_id = parent_id

        newly_adopted: dict[uuid.UUID, MapAtlasNode] = {}
        for node, proposal in path:
            was_provisional = node.status == "provisional"
            if proposal is not None:
                if (
                    node.status == "adopted"
                    and proposal.base_node_updated_at is not None
                    and node.updated_at != proposal.base_node_updated_at
                ):
                    raise ConflictError("地图层级已变化，请刷新候选页")
                old_parent_id = node.parent_id
                node.parent_id = proposal.parent_id
                node.title = proposal.title
                node.level = proposal.level
                node.summary = proposal.summary
                siblings = [
                    item
                    for item in nodes
                    if item.id != node.id
                    and item.parent_id == proposal.parent_id
                    and item.status == "adopted"
                ]
                siblings.sort(key=lambda item: (item.sort_order, item.id))
                siblings.insert(min(proposal.sort_order, len(siblings)), node)
                for index, sibling in enumerate(siblings):
                    sibling.sort_order = index
                if old_parent_id != proposal.parent_id:
                    old_siblings = [
                        item
                        for item in nodes
                        if item.id != node.id
                        and item.parent_id == old_parent_id
                        and item.status == "adopted"
                    ]
                    old_siblings.sort(key=lambda item: (item.sort_order, item.id))
                    for index, sibling in enumerate(old_siblings):
                        sibling.sort_order = index
            node.status = "adopted"
            if was_provisional:
                newly_adopted[node.id] = node
        if newly_adopted:
            await db.flush()
            for candidate in run_pages:
                if candidate.review_status != "candidate" or not candidate.node_proposal:
                    continue
                proposal = MapAtlasNodeProposal.model_validate(candidate.node_proposal)
                adopted = newly_adopted.get(proposal.node_id)
                if adopted is None:
                    continue
                candidate.node_proposal = proposal.model_copy(
                    update={"base_node_updated_at": adopted.updated_at}
                ).model_dump(mode="json", exclude_none=True)
            await db.flush()

    async def _require_run(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str | None,
        *,
        for_update: bool = False,
    ) -> MapAtlasRun:
        if not run_id:
            raise ValidationError("run_id is required")
        statement = select(MapAtlasRun).where(
            MapAtlasRun.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAtlasRun.id == parse_uuid(run_id, "run_id"),
        )
        if for_update:
            statement = statement.with_for_update()
        run = (await db.execute(statement)).scalar_one_or_none()
        if run is None:
            raise NotFoundError("地图册生成记录不存在")
        return run

    async def _active_run(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        exclude_run_id: str | None = None,
        for_update: bool = False,
    ) -> MapAtlasRun | None:
        nid = parse_uuid(novel_id, "novel_id")
        recoverable_page = exists(
            select(MapAtlasPage.id).where(
                MapAtlasPage.novel_id == nid,
                MapAtlasPage.run_id == MapAtlasRun.id,
                or_(
                    MapAtlasPage.generation_status.in_(
                        {"provider_in_flight", "retry_requires_confirmation"}
                    ),
                    MapAtlasPage.error_code.in_(RECOVERABLE_PAGE_ERROR_CODES),
                ),
            )
        )
        statement = (
            select(MapAtlasRun)
            .where(
                MapAtlasRun.novel_id == nid,
                or_(
                    MapAtlasRun.status.in_({*ACTIVE_RUN_STATUSES, "paused"}),
                    and_(
                        MapAtlasRun.status == "partial",
                        or_(
                            MapAtlasRun.error_code.in_(RECOVERABLE_RUN_ERROR_CODES),
                            recoverable_page,
                        ),
                    ),
                ),
            )
            .order_by(MapAtlasRun.created_at.desc(), MapAtlasRun.id.desc())
            .limit(1)
        )
        if exclude_run_id:
            statement = statement.where(
                MapAtlasRun.id != parse_uuid(exclude_run_id, "run_id")
            )
        if for_update:
            statement = statement.with_for_update()
        return (await db.execute(statement)).scalar_one_or_none()

    @staticmethod
    async def _enqueue_run_task(
        db: AsyncSession,
        novel_id: str,
        run: MapAtlasRun,
        *,
        mode: str,
    ) -> str:
        queued = await enqueue_coalesced_task(
            db,
            task_type=MAP_ATLAS_TASK_TYPE,
            novel_id=novel_id,
            scope=("map_atlas_run", str(run.id)),
            meta={"run_id": str(run.id)},
            mode=mode,
        )
        return queued.task_id

    async def _require_page(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        *,
        for_update: bool = False,
    ) -> MapAtlasPage:
        statement = select(MapAtlasPage).where(
            MapAtlasPage.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAtlasPage.id == parse_uuid(page_id, "page_id"),
        )
        if for_update:
            statement = statement.with_for_update()
        page = (await db.execute(statement)).scalar_one_or_none()
        if page is None:
            raise NotFoundError("地图页面不存在")
        return page

    @staticmethod
    async def _require_adopted_node(
        db: AsyncSession, novel_id: uuid.UUID, node_id: str
    ) -> MapAtlasNode:
        node = await db.scalar(
            select(MapAtlasNode).where(
                MapAtlasNode.novel_id == novel_id,
                MapAtlasNode.id == parse_uuid(node_id, "node_id"),
                MapAtlasNode.status == "adopted",
            )
        )
        if node is None:
            raise ValidationError("地点不存在、未加入或不属于当前项目")
        return node

    @staticmethod
    async def _compensate_upload(
        db: AsyncSession, storage: MapAtlasStorage, key: str
    ) -> None:
        try:
            await delete_unreferenced_page_object(db, storage, key)
        except Exception:
            await db.rollback()
            enqueue_task(
                db,
                "map_atlas_storage_cleanup",
                meta={
                    "cleanup_kind": "object",
                    "object_key": key,
                    "delete_batch": str(uuid.uuid4()),
                },
                novel_id=None,
            )
            await db.commit()

    @staticmethod
    def _prompt_dict(page: MapAtlasPage, editable: bool) -> dict[str, Any]:
        return {
            "page_id": str(page.id),
            "prompt": page.prompt,
            "generation_choice": page.generation_choice,
            "editable": editable,
            "updated_at": page.updated_at,
        }

    @staticmethod
    def _run_dict(run: MapAtlasRun) -> dict[str, Any]:
        evidence_summary = MapAtlasEvidenceSummary.from_snapshot(
            dict(run.context_snapshot or {})
        )
        return {
            "id": str(run.id),
            "novel_id": str(run.novel_id),
            "task_id": _uuid(run.task_id),
            "run_kind": run.run_kind,
            "status": run.status,
            "style_note": run.style_note,
            "include_working_drafts": run.include_working_drafts,
            "include_interiors": run.include_interiors,
            "review_image_prompts": run.review_image_prompts,
            "layout": run.layout,
            "quality": run.quality,
            "page_limit": run.page_limit,
            "planned_page_count": run.planned_page_count,
            "completed_page_count": run.completed_page_count,
            "stop_requested": run.stop_requested,
            "error_code": run.error_code,
            "error_message": run.error_message,
            "evidence_summary": (
                evidence_summary.model_dump(mode="json") if evidence_summary else None
            ),
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }

    @staticmethod
    def _annotation_dict(item: MapAtlasAnnotation) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "page_id": str(item.page_id),
            "target_node_id": _uuid(item.target_node_id),
            "label": item.label,
            "position_x": item.position_x,
            "position_y": item.position_y,
            "source_ref": dict(item.source_ref or {}),
            "sort_order": item.sort_order,
            "updated_at": item.updated_at,
        }

    @staticmethod
    def _page_dict(
        page: MapAtlasPage,
        annotations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": str(page.id),
            "novel_id": str(page.novel_id),
            "run_id": str(page.run_id),
            "node_id": str(page.node_id),
            "derived_from_page_id": _uuid(page.derived_from_page_id),
            "generation_status": page.generation_status,
            "generation_choice": page.generation_choice,
            "review_status": page.review_status,
            "title": page.title,
            "visual_brief": page.visual_brief,
            "has_generation_prompt": bool(page.prompt),
            "evidence": dict(page.evidence or {}),
            "source_manifest": list(page.source_manifest or []),
            "reference_page_ids": list(page.reference_page_ids or []),
            "image_url": (
                f"/api/world/map-atlas/{page.novel_id}/pages/{page.id}/image"
                if page.object_key
                and page.generation_status in {"uploaded", "review_ready"}
                else None
            ),
            "width": page.width,
            "height": page.height,
            "byte_size": page.byte_size,
            "sort_order": page.sort_order,
            "review_note": page.review_note,
            "error_code": page.error_code,
            "error_message": page.error_message,
            "annotations": annotations,
            "created_at": page.created_at,
            "updated_at": page.updated_at,
        }

    @staticmethod
    def _node_dict(
        node: MapAtlasNode,
        pages: list[dict[str, Any]],
        children: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": str(node.id),
            "novel_id": str(node.novel_id),
            "parent_id": _uuid(node.parent_id),
            "location_entity_id": _uuid(node.location_entity_id),
            "title": node.title,
            "level": node.level,
            "status": node.status,
            "summary": node.summary,
            "sort_order": node.sort_order,
            "updated_at": node.updated_at,
            "pages": pages,
            "children": children,
        }


def parse_reference_page_ids(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValidationError("reference_page_ids 必须是 JSON 数组") from exc
    if not isinstance(parsed, list):
        raise ValidationError("reference_page_ids 必须是 JSON 数组")
    return [str(item) for item in parsed]
