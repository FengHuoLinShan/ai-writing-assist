"""Deterministic text-planning and page-by-page image workflow."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy import func, select, update

from infrastructure.llm.image_client import ImageGenerationError
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.tasks.facade import (
    enqueue_task,
    list_task_lifecycle_contracts,
    require_running_task_attempt,
    require_task_checkpoint_session,
)
from modules.project.facade import (
    create_project_snapshot_llm_client,
    open_project_image_client,
    require_active_project,
    restore_project_llm_execution_settings,
)
from modules.world.map_atlas_models import (
    MapAtlasAnnotation,
    MapAtlasNode,
    MapAtlasPage,
    MapAtlasRun,
)
from modules.world.map_atlas_schemas import (
    ATLAS_LEVEL_RANK,
    AtlasPlan,
    MapAtlasNodeProposal,
)
from modules.world.map_atlas_storage import (
    MapAtlasStorage,
    delete_unreferenced_page_object,
    page_object_key,
    require_owned_page_object_key,
    validate_png,
)
from modules.world.models import CoreEntity
from shared.constants import TASK_MAX_HEARTBEAT_GAP
from shared.utils import parse_uuid

_NO_TEXT = (
    "画面内绝对不要出现文字、字母、数字、符号、图例或水印；"
    "地点名称只用于理解地理语义，应用会在图片上方另加可编辑标注。"
)
logger = logging.getLogger(__name__)


def _plan_prompt(
    *,
    context: str,
    schema: dict[str, Any],
    style_note: str | None,
    include_interiors: bool,
    prior_atlas: list[dict[str, Any]],
    source_manifest: dict[str, list[Any]],
    run_kind: str,
    allowed_update_targets: dict[str, list[str]] | None = None,
) -> str:
    update_rule = (
        "这是完整重做，重新规划全部必要页面。"
        if run_kind in {"initial", "rebuild"}
        else "这是补全/更新：只规划缺失地点，或资料来源已经变化的地点。"
    )
    return f"""你是小说作者的地图册规划助手。请只输出符合 JSON Schema 的对象。

目标：规划一套可由图像模型逐页生成、可从父图进入子图的小说地图册。
规则：
- 最多 20 页，父级必须先于子级；默认最深到街道。
- 更新已有地点的子图时，用 existing_parent_node_id 引用已有父节点。
- 不要为资料没有变化的父图生成新页。
- 室内图：{'允许' if include_interiors else '不允许'}。
- {update_rule}
- 每页必须把资料分成 supported、visual_fill、conflicts；视觉补全不是正式设定。
- source_status=working 的工作稿不属于正式设定，不得单独支持 supported。
- 此类内容必须放入 visual_fill 或 conflicts 并明确标注。
- annotations 是前端覆盖文字，不要求图片模型绘制文字。
- 来源必须来自下方资料，不得伪造 open_target。
- open_target 如存在，其资料 ID 必须出现在允许来源清单中。
- 地点完整名称必须出现在 visual_brief 中作为语义锚点。

作者风格要求：{style_note or '无额外要求'}
已有地图册：{json.dumps(prior_atlas, ensure_ascii=False)}
服务端判定的可更新目标：{json.dumps(allowed_update_targets or {}, ensure_ascii=False)}
允许来源清单：{json.dumps(source_manifest, ensure_ascii=False)}
JSON Schema：{json.dumps(schema, ensure_ascii=False)}

作者资料（其中标记 working 的内容仅作非正式参考）：
{context}
"""


def _image_prompt(page: MapAtlasPage, style_brief: str) -> str:
    evidence = page.evidence or {}
    supported = "；".join(evidence.get("supported", [])) or "无"
    visual_fill = "；".join(evidence.get("visual_fill", [])) or "无"
    conflicts = "；".join(evidence.get("conflicts", [])) or "无"
    return (
        f"为小说地图册绘制“{page.title}”。\n"
        f"整体视觉：{style_brief}\n"
        f"本页视觉说明：{page.visual_brief}\n"
        f"资料直接支持：{supported}\n"
        f"允许的视觉补全：{visual_fill}\n"
        f"资料冲突：{conflicts}\n"
        f"{_NO_TEXT}"
    )


def _semantic_part(value: str) -> str:
    compact = re.sub(r"\s+", "", value).casefold()
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()[:20]


_SOURCE_KIND_ALIASES: dict[str, set[str]] = {
    "entity": {"entity", "core_entity", "world_entity"},
    "profile": {"profile", "core_entity", "world_entity"},
    "event": {"event", "world_event", "core_entity", "world_entity"},
    "world_bible_page": {"world_bible_page"},
    "world_bible_draft": {"world_bible_draft", "world_bible_page"},
    "scene": {"scene", "outline_scene"},
    "scenes": {"scene", "scenes", "outline_scene"},
    "outline_scene": {"scene", "outline_scene"},
    "rag": {"writing"},
}
_FORMAL_SOURCE_STATUSES = frozenset({"canonical", "confirmed", "published"})
_RETAINED_SOURCE_STATUSES = _FORMAL_SOURCE_STATUSES | {"working"}
_TARGET_ID_KEYS = (
    "id",
    "page_id",
    "entity_id",
    "scene_id",
    "draft_id",
    "source_id",
    "chunk_id",
)


def _open_target(
    source_type: str,
    source_id: str,
    entry: dict[str, Any],
) -> dict[str, str] | None:
    if source_type == "rag":
        try:
            chapter_index = int(entry.get("chapter_index") or 0)
        except (TypeError, ValueError):
            return None
        return (
            {
                "kind": "writing",
                "chapter_index": str(chapter_index),
                "chunk_id": source_id,
            }
            if chapter_index > 0
            else None
        )
    kind = {
        "entity": "world_entity",
        "profile": "profile",
        "event": "world_event",
        "world_bible_page": "world_bible_page",
        "world_bible_draft": "world_bible_draft",
        "scene": "scene",
        "scenes": "scene",
        "outline_scene": "outline_scene",
    }.get(source_type, "")
    id_key = {
        "entity": "entity_id",
        "profile": "entity_id",
        "event": "entity_id",
        "world_bible_page": "page_id",
        "world_bible_draft": "draft_id",
        "scene": "scene_id",
        "scenes": "scene_id",
        "outline_scene": "scene_id",
    }.get(source_type)
    return {"kind": kind, id_key: source_id} if kind and id_key else None


def _atlas_source_manifest(
    source_manifest: dict[str, list[Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Keep only sources with a deterministic author-facing destination."""
    filtered: dict[str, list[dict[str, Any]]] = {}
    for source_type, entries in source_manifest.items():
        if source_type not in _SOURCE_KIND_ALIASES:
            continue
        for raw in entries:
            entry = dict(raw) if isinstance(raw, dict) else {"source_id": str(raw)}
            source_id = str(entry.get("source_id") or entry.get("id") or "").strip()
            source_status = str(entry.get("status") or "").strip().lower()
            target = _open_target(source_type, source_id, entry)
            if (
                not source_id
                or source_status not in _RETAINED_SOURCE_STATUSES
                or target is None
            ):
                continue
            entry["source_id"] = source_id
            entry["status"] = source_status
            entry["title"] = str(entry.get("label") or source_id)[:255]
            entry["summary"] = str(entry.get("summary") or "已保留资料")[:1000]
            entry["open_target"] = target
            filtered.setdefault(source_type, []).append(entry)
    return filtered


def _manifest_lookup(
    source_manifest: dict[str, list[Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    lookup: dict[str, dict[str, dict[str, Any]]] = {}
    for source_type, entries in source_manifest.items():
        bucket: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if isinstance(entry, dict):
                source_id = str(entry.get("source_id") or entry.get("id") or "").strip()
                source_hash = str(entry.get("source_hash") or "").strip()
            else:
                source_id = str(entry).strip()
                source_hash = ""
            if not source_id:
                continue
            canonical = dict(entry) if isinstance(entry, dict) else {}
            canonical["source_hash"] = (
                source_hash if len(source_hash) == 64 else hashlib.sha256(
                    f"{source_type}:{source_id}".encode()
                ).hexdigest()
            )
            bucket[source_id] = canonical
        lookup[str(source_type)] = bucket
    return lookup


def _source_identity(source: Any) -> tuple[str, str]:
    return _source_identity_values(source.source_type, source.open_target or {})


def _source_identity_values(
    source_type_value: Any,
    target_value: Any,
) -> tuple[str, str]:
    source_type = str(source_type_value).strip()
    target = target_value if isinstance(target_value, dict) else {}
    source_ids = {
        str(target[key]).strip()
        for key in _TARGET_ID_KEYS
        if str(target.get(key) or "").strip()
    }
    if len(source_ids) != 1:
        raise ValueError("atlas source must contain exactly one source identity")
    kind = str(target.get("kind") or "").strip()
    allowed_kinds = _SOURCE_KIND_ALIASES.get(source_type)
    if not allowed_kinds:
        raise ValueError("atlas source type has no author-facing destination")
    if kind not in allowed_kinds:
        raise ValueError("atlas source kind does not match its source type")
    return source_type, next(iter(source_ids))


async def _require_attempt(db, task, novel_id: str, run_id: str) -> MapAtlasRun:
    await require_running_task_attempt(
        db,
        task_id=str(task.id),
        task_type=str(task.task_type),
        novel_id=novel_id,
        lease_id=str(task.lease_id or ""),
        attempt=int(task.attempt or 0),
    )
    run = await _load_run(db, novel_id, run_id, lock=True)
    if run.task_id != task.id:
        raise asyncio.CancelledError
    return run


async def _load_run(db, novel_id: str, run_id: str, *, lock: bool = False):
    statement = select(MapAtlasRun).where(
        MapAtlasRun.novel_id == parse_uuid(novel_id, "novel_id"),
        MapAtlasRun.id == parse_uuid(run_id, "run_id"),
    )
    if lock:
        statement = statement.with_for_update()
    run = (await db.execute(statement)).scalar_one_or_none()
    if run is None:
        raise ValueError("map atlas run not found")
    return run


async def _existing_atlas_summary(db, novel_id: str) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(MapAtlasNode, MapAtlasPage)
            .join(MapAtlasPage, MapAtlasPage.node_id == MapAtlasNode.id)
            .where(
                MapAtlasNode.novel_id == parse_uuid(novel_id, "novel_id"),
                MapAtlasPage.review_status == "adopted",
            )
            .order_by(MapAtlasNode.sort_order, MapAtlasPage.created_at)
        )
    ).all()
    summaries: dict[uuid.UUID, dict[str, Any]] = {}
    for node, page in rows:
        summary = summaries.setdefault(
            node.id,
            {
                "node_id": str(node.id),
                "semantic_key": node.semantic_key,
                "location_entity_id": (
                    str(node.location_entity_id) if node.location_entity_id else None
                ),
                "title": node.title,
                "level": node.level,
                "sources": [],
            },
        )
        for item in page.source_manifest or []:
            if isinstance(item, dict) and item not in summary["sources"]:
                summary["sources"].append(item)
    return list(summaries.values())


async def _compile_context(db, run: MapAtlasRun) -> dict[str, Any]:
    from core.container import get
    from modules.world.facade import list_world_bible_working_page_ids

    working_ids = (
        await list_world_bible_working_page_ids(db, str(run.novel_id))
        if run.include_working_drafts
        else []
    )
    provider = get("context.generation_background")
    return await provider(
        db,
        novel_id=str(run.novel_id),
        task="规划 AI 地图册",
        include_world_synopsis=True,
        selected_world_bible_draft_ids=working_ids,
        operation="world.map_atlas.generate",
        prompt_name="world.map_atlas.plan.structured",
        model=str(
            (run.llm_execution_snapshot or {})
            .get("profile", {})
            .get("model")
            or "project-default"
        ),
        focus_text=run.style_note or "",
        source_snapshot={"run_id": str(run.id), "run_kind": run.run_kind},
    )


def _validate_plan_sources(
    plan: AtlasPlan,
    novel_id: str,
    source_manifest: dict[str, list[Any]],
) -> None:
    allowed = _manifest_lookup(source_manifest)
    for node in plan.nodes:
        sources = [
            *node.sources,
            *(
                annotation.source_ref
                for annotation in node.annotations
                if annotation.source_ref is not None
            ),
        ]
        for source in sources:
            target = source.open_target or {}
            if not target:
                raise ValueError("atlas source must include an open target")
            target_novel = target.get("novel_id")
            if target_novel is not None and str(target_novel) != novel_id:
                raise ValueError("atlas source reference crosses novel boundary")
            source_type, source_id = _source_identity(source)
            if source_id not in allowed.get(source_type, {}):
                raise ValueError("atlas source reference was not in compiled context")
            canonical = allowed[source_type][source_id]
            expected_target = canonical.get("open_target")
            if not isinstance(expected_target, dict):
                raise ValueError("atlas source has no canonical open target")
            comparable_target = {
                key: value for key, value in target.items() if key != "novel_id"
            }
            if comparable_target != expected_target:
                raise ValueError("atlas source open target was not canonical")
            source.title = str(canonical.get("title") or source_id)
            source.summary = str(canonical.get("summary") or "已保留资料")
            source.open_target = dict(expected_target)
            source.source_hash = str(canonical["source_hash"])
            source.source_status = str(canonical.get("status") or "").lower()
        formal_sources = [
            source
            for source in node.sources
            if source.source_status in _FORMAL_SOURCE_STATUSES
        ]
        if node.evidence.supported and not formal_sources:
            raise ValueError("working sources cannot be the sole formal support")


def _plan_semantic_keys(
    plan: AtlasPlan,
    prior_atlas: list[dict[str, Any]],
) -> dict[str, str]:
    existing_by_id = {
        str(item.get("node_id")): str(item.get("semantic_key"))
        for item in prior_atlas
        if item.get("node_id") and item.get("semantic_key")
    }
    by_plan_key: dict[str, str] = {}
    for item in plan.nodes:
        parent_semantic = (
            existing_by_id.get(str(item.existing_parent_node_id))
            if item.existing_parent_node_id
            else by_plan_key.get(item.parent_plan_key or "", "root")
        )
        if not parent_semantic:
            raise ValueError("atlas existing parent was not in the current atlas")
        by_plan_key[item.plan_key] = (
            f"entity:{item.location_entity_id}"
            if item.location_entity_id
            else f"path:{parent_semantic}:{_semantic_part(item.title)}"
        )
    return by_plan_key


def _validate_update_targets(
    plan: AtlasPlan,
    prior_atlas: list[dict[str, Any]],
    *,
    changed_semantic_keys: set[str],
    missing_location_ids: set[str],
    new_source_identities: set[tuple[str, str]] | None = None,
) -> None:
    prior_by_semantic = {
        str(item.get("semantic_key")): item
        for item in prior_atlas
        if item.get("semantic_key")
    }
    semantic_keys = _plan_semantic_keys(plan, prior_atlas)
    for item in plan.nodes:
        semantic_key = semantic_keys[item.plan_key]
        if semantic_key not in prior_by_semantic:
            if (
                item.location_entity_id
                and item.location_entity_id not in missing_location_ids
            ):
                raise ValueError(
                    "atlas update attempted to add a non-missing location"
                )
            if not item.location_entity_id:
                identities = {
                    _source_identity(source)
                    for source in item.sources
                    if source.source_status in _FORMAL_SOURCE_STATUSES
                }
                if not identities.intersection(new_source_identities or set()):
                    raise ValueError(
                        "atlas update path nodes require a newly retained source"
                    )
            continue
        if semantic_key not in changed_semantic_keys:
            raise ValueError(
                "atlas update attempted to regenerate an unchanged existing node"
            )


def _changed_update_targets(
    prior_atlas: list[dict[str, Any]],
    current_manifest: dict[str, list[Any]],
) -> tuple[set[str], set[str]]:
    current = _manifest_lookup(current_manifest)
    changed_semantic_keys: set[str] = set()
    changed_source_ids: set[str] = set()
    changed_source_identities: set[tuple[str, str]] = set()
    for item in prior_atlas:
        for source in item.get("sources") or []:
            try:
                source_type, source_id = _source_identity_values(
                    source.get("source_type"), source.get("open_target")
                )
            except (TypeError, ValueError):
                continue
            if (current.get(source_type, {}).get(source_id) or {}).get(
                "source_hash"
            ) != source.get("source_hash"):
                changed_semantic_keys.add(str(item["semantic_key"]))
                changed_source_ids.add(source_id)
                changed_source_identities.add((source_type, source_id))
    if changed_source_identities:
        for item in prior_atlas:
            for source in item.get("sources") or []:
                try:
                    identity = _source_identity_values(
                        source.get("source_type"), source.get("open_target")
                    )
                except (TypeError, ValueError):
                    continue
                if identity in changed_source_identities:
                    changed_semantic_keys.add(str(item["semantic_key"]))
    return changed_semantic_keys, changed_source_ids


def _new_source_identities(
    prior_manifest: dict[str, list[Any]],
    current_manifest: dict[str, list[Any]],
) -> set[tuple[str, str]]:
    prior = {
        (source_type, source_id): source
        for source_type, bucket in _manifest_lookup(prior_manifest).items()
        for source_id, source in bucket.items()
    }
    return {
        (source_type, source_id)
        for source_type, bucket in _manifest_lookup(current_manifest).items()
        for source_id, source in bucket.items()
        if str(source.get("status") or "").lower() in _FORMAL_SOURCE_STATUSES
        and (
            (source_type, source_id) not in prior
            or prior[(source_type, source_id)].get("source_hash")
            != source.get("source_hash")
            or str(prior[(source_type, source_id)].get("status") or "").lower()
            != str(source.get("status") or "").lower()
        )
    }


async def _previous_source_manifest(
    db,
    run: MapAtlasRun,
) -> dict[str, list[dict[str, Any]]]:
    previous = await db.scalar(
        select(MapAtlasRun)
        .where(
            MapAtlasRun.novel_id == run.novel_id,
            MapAtlasRun.id != run.id,
            MapAtlasRun.run_kind.in_({"initial", "update", "rebuild"}),
            MapAtlasRun.status.in_({"review_ready", "partial", "completed"}),
        )
        .order_by(MapAtlasRun.created_at.desc(), MapAtlasRun.id.desc())
        .limit(1)
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in previous.source_manifest if previous is not None else []:
        if not isinstance(item, dict) or not item.get("source_type"):
            continue
        source = dict(item)
        source_type = str(source.pop("source_type"))
        grouped.setdefault(source_type, []).append(source)
    return grouped


async def _persist_plan(db, task, run: MapAtlasRun, plan: AtlasPlan) -> None:
    context_entity_ids = {
        str(item.get("source_id"))
        for item in run.source_manifest or []
        if isinstance(item, dict)
        and item.get("source_type") == "entity"
        and item.get("source_id")
    }
    valid_entity_ids = {
        str(value)
        for value in (
            await db.execute(
                select(CoreEntity.id).where(
                    CoreEntity.novel_id == run.novel_id,
                    CoreEntity.entity_type == "location",
                    CoreEntity.status == "canonical",
                )
            )
        ).scalars()
        if str(value) in context_entity_ids
    }
    existing_parent_ids = {
        parse_uuid(item.existing_parent_node_id, "existing_parent_node_id")
        for item in plan.nodes
        if item.existing_parent_node_id
    }
    existing_parents = {
        item.id: item
        for item in (
            await db.execute(
                select(MapAtlasNode).where(
                    MapAtlasNode.novel_id == run.novel_id,
                    MapAtlasNode.id.in_(existing_parent_ids),
                    MapAtlasNode.status == "adopted",
                )
            )
        ).scalars()
    }
    if len(existing_parents) != len(existing_parent_ids):
        raise ValueError("atlas existing parent was not adopted in this project")
    node_by_key: dict[str, MapAtlasNode] = {}
    parent_by_key: dict[str, MapAtlasNode | None] = {}
    semantic_by_key: dict[str, str] = {}
    for index, item in enumerate(plan.nodes):
        if item.level == "interior" and not run.include_interiors:
            raise ValueError("atlas plan contains an unapproved interior page")
        if item.location_entity_id and item.location_entity_id not in valid_entity_ids:
            raise ValueError("atlas location entity is not canonical project context")
        parent = (
            existing_parents.get(
                parse_uuid(item.existing_parent_node_id, "existing_parent_node_id")
            )
            if item.existing_parent_node_id
            else node_by_key.get(item.parent_plan_key or "")
        )
        if item.level in {"cover", "world"} and parent is not None:
            raise ValueError("atlas cover and world nodes must be roots")
        if parent is not None and (
            ATLAS_LEVEL_RANK[parent.level] >= ATLAS_LEVEL_RANK[item.level]
        ):
            raise ValueError("atlas parent level must be strictly above its child")
        parent_semantic = (
            parent.semantic_key
            if item.existing_parent_node_id and parent is not None
            else semantic_by_key.get(item.parent_plan_key or "", "root")
        )
        semantic_key = (
            f"entity:{item.location_entity_id}"
            if item.location_entity_id
            else f"path:{parent_semantic}:{_semantic_part(item.title)}"
        )
        node = (
            await db.execute(
                select(MapAtlasNode).where(
                    MapAtlasNode.novel_id == run.novel_id,
                    MapAtlasNode.semantic_key == semantic_key,
                )
            )
        ).scalar_one_or_none()
        if node is None:
            node = MapAtlasNode(
                novel_id=run.novel_id,
                created_by_run_id=run.id,
                parent_id=parent.id if parent else None,
                location_entity_id=(
                    parse_uuid(item.location_entity_id, "location_entity_id")
                    if item.location_entity_id
                    else None
                ),
                semantic_key=semantic_key,
                title=item.title,
                level=item.level,
                status="provisional",
                summary=item.summary,
                sort_order=index,
            )
            db.add(node)
            await db.flush()
        node_by_key[item.plan_key] = node
        parent_by_key[item.plan_key] = parent
        semantic_by_key[item.plan_key] = semantic_key
    for index, item in enumerate(plan.nodes):
        node = node_by_key[item.plan_key]
        page = MapAtlasPage(
            novel_id=run.novel_id,
            run_id=run.id,
            node_id=node.id,
            title=item.title,
            visual_brief=item.visual_brief,
            prompt="",
            node_proposal=MapAtlasNodeProposal(
                node_id=node.id,
                parent_id=(
                    parent_by_key[item.plan_key].id
                    if parent_by_key[item.plan_key] is not None
                    else None
                ),
                title=item.title,
                level=item.level,
                summary=item.summary,
                sort_order=index,
            ).model_dump(mode="json"),
            evidence=item.evidence.model_dump(mode="json"),
            source_manifest=[source.model_dump(mode="json") for source in item.sources],
            sort_order=index,
        )
        page.prompt = _image_prompt(page, plan.style_brief)
        db.add(page)
        await db.flush()
        for annotation_index, annotation in enumerate(item.annotations):
            target = node_by_key.get(annotation.target_plan_key or "")
            db.add(
                MapAtlasAnnotation(
                    novel_id=run.novel_id,
                    page_id=page.id,
                    target_node_id=target.id if target else None,
                    label=annotation.label,
                    position_x=annotation.position_x,
                    position_y=annotation.position_y,
                    source_ref=(
                        annotation.source_ref.model_dump(mode="json")
                        if annotation.source_ref
                        else {}
                    ),
                    sort_order=annotation_index,
                )
            )
    run.atlas_plan = plan.model_dump(mode="json")
    run.planned_page_count = len(plan.nodes)
    run.status = "generating"
    await _require_attempt(db, task, str(run.novel_id), str(run.id))
    await db.commit()


async def _plan(db, task, run: MapAtlasRun) -> None:
    previous_manifest = await _previous_source_manifest(db, run)
    background = await _compile_context(db, run)
    rendered = str(background.get("rendered_context") or "")
    usage = dict(background.get("context_usage") or {})
    run.context_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    run.context_snapshot = {
        "context_snapshot_id": usage.get("context_snapshot_id"),
        "rendered_context": rendered,
        "warnings": usage.get("warnings", []),
    }
    raw_manifest = (
        usage.get("included_asset_manifest")
        or usage.get("included_asset_ids")
        or {}
    )
    manifest = _atlas_source_manifest(raw_manifest)
    run.source_manifest = [
        {
            "source_type": source_type,
            **(
                dict(source)
                if isinstance(source, dict)
                else {"source_id": str(source)}
            ),
        }
        for source_type, sources in manifest.items()
        for source in sources
    ]
    prior = await _existing_atlas_summary(db, str(run.novel_id))
    changed_semantic_keys, changed_source_ids = _changed_update_targets(
        prior, manifest
    )
    new_source_identities = _new_source_identities(previous_manifest, manifest)
    manifest_location_ids = set(_manifest_lookup(manifest).get("entity", {}))
    canonical_location_ids = {
        str(item)
        for item in (
            await db.execute(
                select(CoreEntity.id).where(
                    CoreEntity.novel_id == run.novel_id,
                    CoreEntity.entity_type == "location",
                    CoreEntity.status == "canonical",
                )
            )
        ).scalars()
        if str(item) in manifest_location_ids
    }
    existing_location_ids = {
        str(item["location_entity_id"])
        for item in prior
        if item.get("location_entity_id")
    }
    missing_location_ids = canonical_location_ids - existing_location_ids
    allowed_update_targets = {
        "changed_semantic_keys": sorted(changed_semantic_keys),
        "changed_source_ids": sorted(changed_source_ids),
        "missing_location_entity_ids": sorted(missing_location_ids),
        "new_source_identities": sorted(
            f"{source_type}:{source_id}"
            for source_type, source_id in new_source_identities
        ),
    }
    if not manifest and run.run_kind in {"initial", "rebuild"}:
        await require_active_project(db, str(run.novel_id))
        run = await _require_attempt(db, task, str(run.novel_id), str(run.id))
        run.atlas_plan = {"style_brief": "", "nodes": []}
        run.planned_page_count = 0
        run.status = "failed"
        run.error_code = "insufficient_sources"
        run.error_message = (
            "已确认资料不足；请先补充或发布世界书、地点设定或正文，"
            "也可以明确开启工作稿后重试"
        )
        await db.commit()
        return
    if (
        run.run_kind == "update"
        and not changed_semantic_keys
        and not missing_location_ids
        and not new_source_identities
    ):
        await require_active_project(db, str(run.novel_id))
        run = await _require_attempt(db, task, str(run.novel_id), str(run.id))
        run.atlas_plan = {"style_brief": "", "nodes": []}
        run.planned_page_count = 0
        run.status = "review_ready"
        await db.commit()
        return
    settings = await restore_project_llm_execution_settings(
        db,
        str(run.novel_id),
        dict(run.llm_execution_snapshot or {}),
    )
    await db.commit()
    client = create_project_snapshot_llm_client(settings, novel_id=str(run.novel_id))
    try:
        plan = await client.generate_structured(
            LLMCallRequest(
                messages=[
                    LLMMessage(
                        role="user",
                        content=_plan_prompt(
                            context=rendered,
                            schema=AtlasPlan.model_json_schema(),
                            style_note=run.style_note,
                            include_interiors=run.include_interiors,
                            prior_atlas=prior,
                            source_manifest=manifest,
                            run_kind=run.run_kind,
                            allowed_update_targets=allowed_update_targets,
                        ),
                    )
                ],
                temperature=0.2,
                max_tokens=12000,
            ),
            AtlasPlan,
            max_fix_attempts=2,
        )
    finally:
        await client.close()
    _validate_plan_sources(plan, str(run.novel_id), manifest)
    if not plan.nodes:
        await require_active_project(db, str(run.novel_id))
        run = await _require_attempt(db, task, str(run.novel_id), str(run.id))
        run.atlas_plan = plan.model_dump(mode="json")
        run.planned_page_count = 0
        run.status = "review_ready"
        await db.commit()
        return
    if run.run_kind == "update":
        _validate_update_targets(
            plan,
            prior,
            changed_semantic_keys=changed_semantic_keys,
            missing_location_ids=missing_location_ids,
            new_source_identities=new_source_identities,
        )
    await require_active_project(db, str(run.novel_id))
    run = await _require_attempt(db, task, str(run.novel_id), str(run.id))
    run.context_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    run.context_snapshot = {
        "context_snapshot_id": usage.get("context_snapshot_id"),
        "rendered_context": rendered,
        "warnings": usage.get("warnings", []),
    }
    run.source_manifest = [
        {
            "source_type": source_type,
            **(
                dict(source)
                if isinstance(source, dict)
                else {"source_id": str(source)}
            ),
        }
        for source_type, sources in manifest.items()
        for source in sources
    ]
    await _persist_plan(db, task, run, plan)


async def _reference_images(db, storage: MapAtlasStorage, page: MapAtlasPage):
    reference_ids = [
        parse_uuid(item, "reference_page_id") for item in page.reference_page_ids
    ]
    parent_id = await db.scalar(
        select(MapAtlasNode.parent_id).where(MapAtlasNode.id == page.node_id)
    )
    if parent_id:
        parent_page = await db.scalar(
            select(MapAtlasPage)
            .where(
                MapAtlasPage.novel_id == page.novel_id,
                MapAtlasPage.node_id == parent_id,
                MapAtlasPage.generation_status == "review_ready",
                MapAtlasPage.run_id == page.run_id,
            )
            .order_by(MapAtlasPage.created_at.desc())
        )
        if parent_page is None:
            parent_page = await db.scalar(
                select(MapAtlasPage)
                .where(
                    MapAtlasPage.novel_id == page.novel_id,
                    MapAtlasPage.node_id == parent_id,
                    MapAtlasPage.generation_status == "review_ready",
                    MapAtlasPage.review_status == "adopted",
                )
                .order_by(MapAtlasPage.created_at.desc())
            )
        if parent_page and parent_page.id not in reference_ids and len(reference_ids) < 8:
            reference_ids.append(parent_page.id)
    reference_ids = list(dict.fromkeys(reference_ids))
    if len(reference_ids) > 8:
        raise ValueError("map atlas image generation accepts at most 8 references")
    if not reference_ids:
        return []
    refs = list(
        (
            await db.execute(
                select(MapAtlasPage).where(
                    MapAtlasPage.novel_id == page.novel_id,
                    MapAtlasPage.id.in_(reference_ids),
                    MapAtlasPage.object_key.isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {item.id: item for item in refs}
    ordered = [by_id[item] for item in reference_ids if item in by_id]
    await db.commit()
    images = []
    for index, item in enumerate(ordered):
        key = require_owned_page_object_key(
            str(item.object_key or ""),
            str(item.novel_id),
            str(item.id),
        )
        images.append(
            (f"reference-{index}.png", await storage.get_png(key), "image/png")
        )
    return images


async def _mark_page_failure(
    db,
    task,
    page_id: uuid.UUID,
    *,
    code: str,
    message: str,
    possible_charge: bool,
) -> None:
    page = await db.get(MapAtlasPage, page_id)
    if page is None:
        return
    run = await _require_attempt(
        db, task, str(page.novel_id), str(page.run_id)
    )
    page = (
        await db.execute(
            select(MapAtlasPage)
            .where(
                MapAtlasPage.novel_id == run.novel_id,
                MapAtlasPage.run_id == run.id,
                MapAtlasPage.id == page_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if page is None:
        return
    page.generation_status = (
        "retry_requires_confirmation" if possible_charge else "failed"
    )
    page.error_code = code
    page.error_message = message
    run.status = "partial"
    run.error_code = code
    run.error_message = message
    await db.commit()


async def _compensate_uploaded_object(
    db,
    storage: MapAtlasStorage,
    key: str,
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


def _attempt_object_key(run: MapAtlasRun, page: MapAtlasPage, task: Any) -> str:
    return page_object_key(
        str(run.novel_id),
        str(page.id),
        attempt_token=f"{task.id}-{int(task.attempt)}",
    )


async def _recover_uploaded_page(
    db,
    task,
    run: MapAtlasRun,
    page: MapAtlasPage,
    storage: MapAtlasStorage,
) -> bool:
    if not page.object_key:
        return False
    key = require_owned_page_object_key(
        page.object_key,
        str(page.novel_id),
        str(page.id),
    )
    payload = await storage.get_png_if_exists(key)
    if payload is None:
        return False
    metadata = validate_png(payload)
    await require_active_project(db, str(run.novel_id))
    run = await _require_attempt(db, task, str(run.novel_id), str(run.id))
    locked = (
        await db.execute(
            select(MapAtlasPage)
            .where(
                MapAtlasPage.novel_id == run.novel_id,
                MapAtlasPage.run_id == run.id,
                MapAtlasPage.id == page.id,
                MapAtlasPage.generation_status == "prepared",
                MapAtlasPage.object_key == key,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if locked is None:
        raise asyncio.CancelledError
    locked.sha256 = metadata.sha256
    locked.media_type = "image/png"
    locked.width = metadata.width
    locked.height = metadata.height
    locked.byte_size = metadata.byte_size
    locked.generation_status = "review_ready"
    locked.error_code = None
    locked.error_message = None
    await db.flush()
    run.completed_page_count = int(
        await db.scalar(
            select(func.count(MapAtlasPage.id)).where(
                MapAtlasPage.run_id == run.id,
                MapAtlasPage.generation_status == "review_ready",
            )
        )
        or 0
    )
    await db.commit()
    return True


async def _generate_page(db, task, run: MapAtlasRun, page: MapAtlasPage) -> bool:
    page_id = page.id
    storage = MapAtlasStorage()
    try:
        if await _recover_uploaded_page(db, task, run, page, storage):
            return True
        references = await _reference_images(db, storage, page)
        mask = None
        if page.mask_object_key:
            mask_key = require_owned_page_object_key(
                page.mask_object_key,
                str(page.novel_id),
                str(page.id),
            )
            mask = (
                "mask.png",
                await storage.get_png(mask_key),
                "image/png",
            )
        async with open_project_image_client(
            db,
            str(run.novel_id),
            snapshot=dict(run.image_execution_snapshot or {}),
        ) as client:
            await db.commit()
            await require_active_project(db, str(run.novel_id))
            run = await _require_attempt(
                db, task, str(run.novel_id), str(run.id)
            )
            key = _attempt_object_key(run, page, task)
            claimed = await db.execute(
                update(MapAtlasPage)
                .where(
                    MapAtlasPage.novel_id == run.novel_id,
                    MapAtlasPage.id == page.id,
                    MapAtlasPage.run_id == run.id,
                    MapAtlasPage.generation_status == "prepared",
                )
                .values(
                    generation_status="provider_in_flight",
                    object_key=key,
                    error_code=None,
                    error_message=None,
                )
            )
            if claimed.rowcount != 1:
                raise asyncio.CancelledError
            await db.commit()
            for attempt in range(3):
                try:
                    if page.derived_from_page_id or references:
                        result = await client.edit(
                            prompt=(
                                f"{page.prompt}\n修改要求：{page.edit_instruction}"
                                if page.edit_instruction
                                else page.prompt
                            ),
                            images=references,
                            mask=mask,
                            size=(
                                "2048x1152"
                                if run.layout == "landscape"
                                else "1024x1024"
                            ),
                            quality="high" if run.quality == "fine" else "medium",
                        )
                    else:
                        result = await client.generate(
                            prompt=page.prompt,
                            size=(
                                "2048x1152"
                                if run.layout == "landscape"
                                else "1024x1024"
                            ),
                            quality="high" if run.quality == "fine" else "medium",
                        )
                    break
                except ImageGenerationError as error:
                    if error.retryable and not error.possible_charge and attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    await _mark_page_failure(
                        db,
                        task,
                        page_id,
                        code=error.code,
                        message=str(error),
                        possible_charge=error.possible_charge,
                    )
                    return False
                except BaseException as error:
                    logger.warning(
                        "Map atlas image provider interrupted: %s",
                        redact_diagnostic(error, limit=300),
                    )
                    await _mark_page_failure(
                        db,
                        task,
                        page_id,
                        code="image_provider_interrupted",
                        message="图片服务请求中断，结果可能未知",
                        possible_charge=True,
                    )
                    raise
    except asyncio.CancelledError:
        raise
    except BaseException as error:
        logger.warning(
            "Map atlas image preparation failed: %s",
            redact_diagnostic(error, limit=300),
        )
        current = await db.get(MapAtlasPage, page_id)
        if current is not None and current.generation_status == "prepared":
            await _mark_page_failure(
                db,
                task,
                page_id,
                code="image_preparation_failed",
                message="图片生成准备失败，请检查参考图后重试",
                possible_charge=False,
            )
            return False
        raise
    uploaded_durable = False
    try:
        await require_active_project(db, str(run.novel_id))
        run = await _require_attempt(db, task, str(run.novel_id), str(run.id))
        metadata = await storage.put_png(key, result.data)
        run = await _require_attempt(db, task, str(run.novel_id), str(run.id))
        locked = (
            await db.execute(
                select(MapAtlasPage)
                .where(
                    MapAtlasPage.novel_id == run.novel_id,
                    MapAtlasPage.id == page_id,
                    MapAtlasPage.generation_status == "provider_in_flight",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if locked is None:
            raise asyncio.CancelledError
        locked.object_key = key
        locked.sha256 = metadata.sha256
        locked.media_type = "image/png"
        locked.width = metadata.width
        locked.height = metadata.height
        locked.byte_size = metadata.byte_size
        locked.provider_request_id = result.request_id
        locked.generation_status = "review_ready"
        run.completed_page_count += 1
        await db.commit()
        uploaded_durable = True
        return True
    except asyncio.CancelledError:
        await db.rollback()
        if not uploaded_durable:
            await _compensate_uploaded_object(db, storage, key)
        raise
    except BaseException:
        await db.rollback()
        if not uploaded_durable:
            await _compensate_uploaded_object(db, storage, key)
            try:
                await _mark_page_failure(
                    db,
                    task,
                    page_id,
                    code="image_storage_failed",
                    message=(
                        "图片已生成但存储失败；"
                        "确认可能重复扣费后才能重试"
                    ),
                    possible_charge=True,
                )
            except asyncio.CancelledError:
                raise
            return False
        raise


async def _finalize_uploaded_pages(db, task, run: MapAtlasRun) -> None:
    await require_active_project(db, str(run.novel_id))
    run = await _require_attempt(db, task, str(run.novel_id), str(run.id))
    pages = list(
        (
            await db.execute(
                select(MapAtlasPage)
                .where(
                    MapAtlasPage.run_id == run.id,
                    MapAtlasPage.generation_status == "uploaded",
                    MapAtlasPage.object_key.isnot(None),
                )
                .order_by(MapAtlasPage.sort_order)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if not pages:
        await db.commit()
        return
    for page in pages:
        page.generation_status = "review_ready"
    run.completed_page_count += len(pages)
    await db.commit()


async def _converge_workflow_failure(
    db,
    task,
    novel_id: str,
    run_id: str,
    error: BaseException,
) -> None:
    logger.warning(
        "Map atlas workflow failed: %s",
        redact_diagnostic(error, limit=500),
    )
    await db.rollback()
    try:
        await require_active_project(db, novel_id)
        run = await _require_attempt(db, task, novel_id, run_id)
    except BaseException:
        await db.rollback()
        return
    pages = list(
        (
            await db.execute(
                select(MapAtlasPage)
                .where(MapAtlasPage.run_id == run.id)
                .with_for_update()
            )
        ).scalars()
    )
    for page in pages:
        if page.generation_status == "provider_in_flight":
            page.generation_status = "retry_requires_confirmation"
            page.error_code = "possible_duplicate_charge"
            page.error_message = "上次图片请求结果未知"
        elif page.generation_status == "uploaded" and page.object_key:
            page.generation_status = "review_ready"
    run.completed_page_count = sum(
        page.generation_status == "review_ready" for page in pages
    )
    if not pages:
        run.status = "failed"
    elif any(page.generation_status == "retry_requires_confirmation" for page in pages):
        run.status = "partial"
        run.error_code = "retry_requires_confirmation"
        run.error_message = "上次图片请求结果未知；确认后才能重试"
        await db.commit()
        return
    else:
        run.status = "partial"
    run.error_code = "map_atlas_workflow_failed"
    run.error_message = "地图册生成服务中断，已保留完成内容"
    await db.commit()


async def _run_map_atlas_workflow(db, task, novel_id: str, run_id: str) -> dict[str, Any]:
    await require_active_project(db, novel_id)
    run = await _require_attempt(db, task, novel_id, run_id)
    stale_in_flight = await db.scalar(
        select(func.count(MapAtlasPage.id)).where(
            MapAtlasPage.run_id == run.id,
            MapAtlasPage.generation_status == "provider_in_flight",
        )
    )
    if stale_in_flight:
        pages = list(
            (
                await db.execute(
                    select(MapAtlasPage)
                    .where(
                        MapAtlasPage.run_id == run.id,
                        MapAtlasPage.generation_status == "provider_in_flight",
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        for page in pages:
            page.generation_status = "retry_requires_confirmation"
        run.status = "partial"
        run.error_code = "retry_requires_confirmation"
        run.error_message = "上次图片请求结果未知；确认可能重复扣费后才能继续"
        await db.commit()
        return {"run_id": run_id, "status": "retry_requires_confirmation"}
    if not run.atlas_plan and run.run_kind not in {"edit", "regenerate"}:
        await db.commit()
        await _plan(db, task, run)
    else:
        await db.commit()
    run = await _load_run(db, novel_id, run_id)
    await _finalize_uploaded_pages(db, task, run)
    pages = list(
        (
            await db.execute(
                select(MapAtlasPage)
                .where(
                    MapAtlasPage.novel_id == parse_uuid(novel_id, "novel_id"),
                    MapAtlasPage.run_id == parse_uuid(run_id, "run_id"),
                    MapAtlasPage.generation_status == "prepared",
                )
                .order_by(MapAtlasPage.sort_order, MapAtlasPage.created_at)
            )
        ).scalars()
    )
    await db.commit()
    for page in pages:
        await require_active_project(db, novel_id)
        run = await _require_attempt(db, task, novel_id, run_id)
        if run.stop_requested:
            run.status = "paused"
            await db.commit()
            return {"run_id": run_id, "status": "paused"}
        await db.commit()
        await _generate_page(db, task, run, page)
    await require_active_project(db, novel_id)
    run = await _require_attempt(db, task, novel_id, run_id)
    failed = await db.scalar(
        select(func.count(MapAtlasPage.id)).where(
            MapAtlasPage.run_id == run.id,
            MapAtlasPage.generation_status.in_(
                {"failed", "retry_requires_confirmation"}
            ),
        )
    )
    run.status = "partial" if failed else "review_ready"
    await db.commit()
    return {
        "run_id": run_id,
        "status": run.status,
        "planned_pages": run.planned_page_count,
        "completed_pages": run.completed_page_count,
    }


async def run_map_atlas_workflow(db, task) -> dict[str, Any]:
    require_task_checkpoint_session(db)
    meta = dict(task.meta or {})
    novel_id = str(meta.get("novel_id") or "")
    run_id = str(meta.get("run_id") or "")
    if not novel_id or not run_id or not task.lease_id or int(task.attempt or 0) < 1:
        raise ValueError("invalid map atlas task identity")
    try:
        return await _run_map_atlas_workflow(db, task, novel_id, run_id)
    except asyncio.CancelledError:
        await db.rollback()
        raise
    except BaseException as error:
        await _converge_workflow_failure(db, task, novel_id, run_id, error)
        raise


async def reconcile_map_atlas_task_owners(db) -> int:
    """Converge atlas checkpoints after queue-level stale recovery."""
    runs = list(
        (
            await db.execute(
                select(MapAtlasRun)
                .where(MapAtlasRun.status.in_({"planning", "generating"}))
                .order_by(MapAtlasRun.novel_id, MapAtlasRun.created_at)
                .with_for_update()
            )
        ).scalars()
    )
    contracts: dict[str, Any] = {}
    by_novel: dict[str, list[MapAtlasRun]] = {}
    for run in runs:
        by_novel.setdefault(str(run.novel_id), []).append(run)
    for novel_id, novel_runs in by_novel.items():
        contracts.update(
            await list_task_lifecycle_contracts(
                db,
                task_ids=[str(run.task_id) for run in novel_runs if run.task_id],
                novel_id=novel_id,
                max_heartbeat_gap=TASK_MAX_HEARTBEAT_GAP,
            )
        )
    repaired = 0
    for run in runs:
        task = contracts.get(str(run.task_id))
        if task is not None and task.status == "pending":
            continue
        if task is not None and task.status == "running" and not task.stale:
            continue
        pages = list(
            (
                await db.execute(
                    select(MapAtlasPage)
                    .where(MapAtlasPage.run_id == run.id)
                    .with_for_update()
                )
            ).scalars()
        )
        for page in pages:
            if page.generation_status == "provider_in_flight":
                page.generation_status = "retry_requires_confirmation"
                page.error_code = "possible_duplicate_charge"
                page.error_message = "上次图片请求结果未知"
            elif page.generation_status == "uploaded" and page.object_key:
                page.generation_status = "review_ready"
        run.completed_page_count = sum(
            page.generation_status == "review_ready" for page in pages
        )
        if not pages:
            run.status = "failed"
        else:
            run.status = "partial"
        run.error_code = (
            "retry_requires_confirmation"
            if any(
                page.generation_status == "retry_requires_confirmation"
                for page in pages
            )
            else "worker_interrupted"
        )
        run.error_message = "生成服务曾中断，已保留完成内容，可继续生成"
        repaired += 1
    if repaired:
        await db.flush()
    return repaired
