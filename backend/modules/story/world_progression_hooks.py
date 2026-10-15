"""Read-only rolling-window hook previews and author-confirmed Story adoption."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select

from core.dependencies import DbSession
from core.errors import ConflictError, NotFoundError
from infrastructure.llm.collaboration import content_hash
from modules.evidence.facade import (
    attach_result_ref,
    mark_asset_context_changed,
    require_fresh_confirmation,
)
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)
from modules.story.outline_state.models import OutlineArc, PlotThread, Scene
from modules.story.outline_state.p20_context import P20ContextBuilder
from modules.story.outline_state.p20_schemas import OutlineLayerGenerateRequest
from modules.story.outline_state.p20_window import window_bounds, window_limit_violation
from modules.story.outline_state.schemas import (
    OutlineArcCreate,
    PlotThreadCreate,
    SceneCreate,
)
from modules.story.outline_state.services import (
    OutlineArcService,
    PlotThreadService,
    SceneService,
)
from modules.story.world_progression_schemas import (
    ProgressionHookAdoptRequest,
    ProgressionHookPreviewRequest,
)
from modules.story.world_progression_service import (
    get_progression_branch,
    get_progression_root,
    get_progression_step,
)

router = APIRouter(tags=["story-world-progression"])


def _trace_fields(schema: type) -> dict[str, str]:
    return {field: f"data.{field}" for field in schema.model_fields}


def _raise_http(error: Exception) -> HTTPException:
    if isinstance(error, PermissionError):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, NotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ConflictError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=400, detail=str(error))
    return HTTPException(
        status_code=500,
        detail="世界推进钩子暂时无法完成该操作，请稍后重试。",
    )


async def _resolve_hook(db, novel_id: str, root_id: str, step_id: str, hook_id: str):
    root = await get_progression_root(db, novel_id, root_id)
    step = await get_progression_step(db, novel_id, step_id)
    if str(step.root_id) != str(root.id):
        raise ConflictError("钩子来源步骤不属于该推进根")
    await get_progression_branch(db, novel_id, str(step.branch_id))
    hooks = list((step.result_json or {}).get("plot_hooks") or [])
    for index, raw in enumerate(hooks):
        expected = content_hash(
            {
                "step_id": str(step.id),
                "output_hash": step.output_hash,
                "index": index,
                "hook": raw,
            }
        )[:32]
        if expected == hook_id:
            return root, step, index, dict(raw)
    raise NotFoundError("该推进步骤中没有找到此钩子候选")


def _window(data, hook: dict, root) -> tuple[int, int]:
    time_basis = (root.source_snapshot_json or {}).get("time_basis") or {}
    chapter = int((time_basis.get("cutoff") or {}).get("chapter_index") or 0)
    requested_start = data.start_chapter or hook.get("start_chapter") or chapter + 1
    start = max(chapter + 1, int(requested_start))
    bounds = window_bounds(data.asset_type, start)
    assert bounds is not None
    end = int(data.end_chapter or hook.get("end_chapter") or bounds[1])
    violation = window_limit_violation(data.asset_type, start, end)
    if violation:
        raise ValueError(violation)
    if end < start:
        raise ValueError("章节窗口结束位置不能早于开始位置")
    return start, end


def _default_draft(hook: dict, asset_type: str, start: int, end: int) -> dict:
    actors = [str(item) for item in hook.get("actor_ids") or []]
    if asset_type == "plot_thread":
        return {
            "name": hook.get("title") or "推进钩子",
            "thread_type": "world_progression",
            "summary": hook.get("summary") or "",
            "visible_goal": hook.get("summary") or "",
            "hidden_truth": "",
            "start_chapter": start,
            "planned_payoff_chapter": end,
            "related_character_ids": actors,
            "related_entity_ids": [],
        }
    if asset_type == "outline_arc":
        return {
            "title": hook.get("title") or "推进篇章",
            "start_chapter": start,
            "end_chapter": end,
            "arc_goal": hook.get("summary") or "",
            "core_conflict": "",
            "midpoint_turn": "",
            "climax": "",
            "result": "",
            "next_hook": "",
            "related_thread_ids": [],
            "related_character_ids": actors,
            "related_entity_ids": [],
        }
    return {
        "scene_index": 0,
        "title": hook.get("title") or "计划场景",
        "goal": hook.get("summary") or "",
        "core_conflict": "",
        "emotional_beat": "",
        "must_happen": "",
        "must_not_happen": "",
        "narrative_tag": "hook",
        "chapter_ids": [],
        "pov_character_id": actors[0] if actors else None,
        "structure_meta": {
            "planning_state": "planned",
            "planned_chapter_range": {"start": start, "end": end},
            "progression_related_character_ids": actors,
        },
    }


async def _prepare_hook_preview(db, data, *, confirmed_context=None):
    root, step, index, hook = await _resolve_hook(
        db, data.novel_id, str(data.root_id), str(data.step_id), data.hook_id
    )
    start, end = _window(data, hook, root)
    draft = data.draft or _default_draft(hook, data.asset_type, start, end)
    instruction = (
        f"作者已从世界推进候选中选择：{hook.get('title', '')}。"
        "此步骤只预览滚动规划范围与来源，不调用模型，不创建结构资产。"
    )
    p20_request = OutlineLayerGenerateRequest(
        novel_id=data.novel_id,
        context_confirmation_id=data.context_confirmation_id,
        target=data.asset_type,
        mode="create",
        instruction=instruction,
        start_chapter=start,
        end_chapter=end,
        rolling_window=True,
        operation_id=data.operation_id,
    )
    plan = await P20ContextBuilder().prepare(
        db, p20_request, confirmed_context=confirmed_context
    )
    author_refs = plan.reference_map
    actor_ids = set(map(str, hook.get("actor_ids") or []))
    allowed_actors = set(map(str, (author_refs.get("characters") or {}).values()))
    allowed_entities = set(map(str, (author_refs.get("entities") or {}).values()))
    if not actor_ids <= allowed_actors | allowed_entities:
        raise ConflictError("钩子关联身份不在当前规划确认来源中，请重新选择")
    if data.asset_type == "plot_thread":
        if not data.draft:
            draft["related_character_ids"] = sorted(actor_ids & allowed_actors)
            draft["related_entity_ids"] = sorted(actor_ids & allowed_entities)
        elif (
            not set(map(str, draft.get("related_character_ids") or [])) <= allowed_actors
            or not set(map(str, draft.get("related_entity_ids") or []))
            <= allowed_entities
        ):
            raise ConflictError("采用草稿关联了确认范围外的身份")
        PlotThreadCreate.model_validate(draft)
    elif data.asset_type == "outline_arc":
        if not data.draft:
            draft["related_character_ids"] = sorted(actor_ids & allowed_actors)
            draft["related_entity_ids"] = sorted(actor_ids & allowed_entities)
        elif (
            not set(map(str, draft.get("related_character_ids") or [])) <= allowed_actors
            or not set(map(str, draft.get("related_entity_ids") or []))
            <= allowed_entities
        ):
            raise ConflictError("采用草稿关联了确认范围外的身份")
        OutlineArcCreate.model_validate(draft)
    else:
        if not data.draft:
            draft["pov_character_id"] = next(
                (
                    actor
                    for actor in hook.get("actor_ids") or []
                    if actor in allowed_actors
                ),
                None,
            )
        elif (
            draft.get("pov_character_id")
            and str(draft["pov_character_id"]) not in allowed_actors
        ):
            raise ConflictError("计划场景视角人物不在确认范围内")
        SceneCreate.model_validate(draft)
    payload_hash = content_hash(
        {
            "root_id": str(root.id),
            "step_id": str(step.id),
            "step_output_hash": step.output_hash,
            "hook_id": data.hook_id,
            "hook": hook,
            "asset_type": data.asset_type,
            "window": [start, end],
            "source_fingerprint": plan.source_fingerprint,
            "confirmation_id": data.context_confirmation_id,
            "draft": draft,
        }
    )
    return {
        "root": root,
        "step": step,
        "hook": hook,
        "window": {"start_chapter": start, "end_chapter": end},
        "draft": draft,
        "preview_hash": payload_hash,
        "source_readset": {
            "fingerprint": plan.source_fingerprint,
            "story_outline_revision_id": plan.context_provenance.get(
                "story_outline_revision_id"
            ),
            "confirmation_id": data.context_confirmation_id,
        },
        "_plan": plan,
    }


@router.post(
    "/hooks/preview",
    openapi_extra={
        "x-novelcraft-operation-id": "story.world_progression.preview_hook",
        "x-novelcraft-operation-trace-fields": _trace_fields(
            ProgressionHookPreviewRequest
        ),
    },
)
async def api_progression_hook_preview(
    data: ProgressionHookPreviewRequest, db: DbSession
):
    from modules.story.world_progression_api import _enabled

    _enabled()
    await require_active_project(db, data.novel_id)
    try:
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action="outline.generate",
            confirmation_id=data.context_confirmation_id,
        )
        result = await _prepare_hook_preview(db, data)
        return {
            "hook": result["hook"],
            "asset_type": data.asset_type,
            "window": result["window"],
            "draft": result["draft"],
            "preview_hash": result["preview_hash"],
            "source_readset": result["source_readset"],
            "effect": (
                "按确认的滚动窗口创建一项可编辑 Story 结构资产；"
                "不会写入 World、正文或连续性。"
            ),
            "model_requests": 0,
            "writes": 0,
        }
    except Exception as error:
        raise _raise_http(error) from error


async def _find_adopted_operation(
    db, novel_id: str, asset_type: str, operation_id: str, preview_hash: str
):
    for current_type, model in (
        ("plot_thread", PlotThread),
        ("outline_arc", OutlineArc),
        ("planned_scene", Scene),
    ):
        rows = (
            await db.scalars(select(model).where(model.novel_id == UUID(novel_id)))
        ).all()
        for row in rows:
            provenance = (
                dict((row.structure_meta or {}).get("provenance") or {})
                if current_type == "planned_scene"
                else dict(row.provenance_meta or {})
            )
            if provenance.get("world_progression_operation_id") != operation_id:
                continue
            if (
                current_type != asset_type
                or provenance.get("world_progression_preview_hash") != preview_hash
            ):
                raise ConflictError("同一采用操作已用于另一钩子或草稿")
            return {
                "asset_type": (
                    "scene" if current_type == "planned_scene" else current_type
                ),
                "asset_id": str(row.id),
                "status": "adopted",
            }
    return None


async def _apply_hook_adoption(db, data):
    from modules.story.world_progression_api import _enabled

    _enabled()
    await require_active_project(db, data.novel_id)
    prior = await _find_adopted_operation(
        db, data.novel_id, data.asset_type, str(data.operation_id), data.preview_hash
    )
    if prior:
        return prior
    preview = await _prepare_hook_preview(db, data)
    if preview["preview_hash"] != data.preview_hash:
        raise ConflictError("钩子来源、滚动窗口或采用草稿已变化，请重新预览")
    fresh_plan = preview["_plan"]
    fresh_source_fingerprint = preview["source_readset"]["fingerprint"]
    await require_active_project_exclusive(db, data.novel_id)
    prior = await _find_adopted_operation(
        db, data.novel_id, data.asset_type, str(data.operation_id), data.preview_hash
    )
    if prior:
        return prior
    await require_fresh_confirmation(
        db,
        novel_id=data.novel_id,
        action="outline.generate",
        confirmation_id=data.context_confirmation_id,
        for_update=True,
    )
    locked = await _prepare_hook_preview(
        db, data, confirmed_context=fresh_plan.confirmed_context
    )
    if locked["source_readset"]["fingerprint"] != fresh_source_fingerprint:
        raise ConflictError("滚动规划来源在作者确认时发生变化")
    locked_plan = locked["_plan"]
    root = preview["root"]
    step = preview["step"]
    provenance = {
        "source": "world_progression",
        "world_progression_root_id": str(root.id),
        "world_progression_step_id": str(step.id),
        "world_progression_step_output_hash": step.output_hash,
        "world_progression_source_hash": step.source_hash,
        "world_progression_operation_id": str(data.operation_id),
        "world_progression_preview_hash": data.preview_hash,
        "p20_source_fingerprint": locked_plan.source_fingerprint,
        "p20_story_outline_revision_id": locked_plan.context_provenance.get(
            "story_outline_revision_id"
        ),
        "context_confirmation_id": data.context_confirmation_id,
        "author_adopted_at": datetime.now(UTC).isoformat(),
        "needs_review": False,
        "user_edited": True,
    }
    draft = dict(preview["draft"])
    async with db.begin_nested():
        if data.asset_type == "plot_thread":
            draft["provenance_meta"] = provenance
            asset = await PlotThreadService().create(
                db, data.novel_id, PlotThreadCreate.model_validate(draft)
            )
            asset_type = "plot_thread"
        elif data.asset_type == "outline_arc":
            draft["provenance_meta"] = provenance
            asset = await OutlineArcService().create(
                db, data.novel_id, OutlineArcCreate.model_validate(draft)
            )
            asset_type = "outline_arc"
        else:
            maximum = await db.scalar(
                select(func.max(Scene.scene_index)).where(
                    Scene.novel_id == UUID(data.novel_id)
                )
            )
            draft["scene_index"] = int(maximum) + 1 if maximum is not None else 0
            draft["source"] = "world_progression"
            draft["status"] = "draft"
            draft["structure_meta"] = {
                **dict(draft.get("structure_meta") or {}),
                "planning_state": "planned",
                "provenance": provenance,
            }
            asset = await SceneService().create(
                db, data.novel_id, SceneCreate.model_validate(draft)
            )
            asset_type = "scene"
        await attach_result_ref(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            result_type=asset_type,
            result_id=str(asset.id),
            status="adopted",
        )
        await mark_asset_context_changed(
            db,
            novel_id=data.novel_id,
            asset_type=asset_type,
            asset_id=str(asset.id),
            reason="source_changed",
            exclude_confirmation_id=data.context_confirmation_id,
        )
    return {
        "asset_type": asset_type,
        "asset_id": str(asset.id),
        "status": "adopted",
        "root_id": str(root.id),
        "step_id": str(step.id),
        "source_fingerprint": locked_plan.source_fingerprint,
        "needs_review": False,
    }


@router.post(
    "/hooks/adopt",
    status_code=http_status.HTTP_200_OK,
    openapi_extra={
        "x-novelcraft-operation-id": "story.world_progression.adopt_hook",
        "x-novelcraft-operation-trace-fields": _trace_fields(ProgressionHookAdoptRequest),
    },
)
async def api_progression_hook_adopt(data: ProgressionHookAdoptRequest, db: DbSession):
    try:
        return await _apply_hook_adoption(db, data)
    except Exception as error:
        raise _raise_http(error) from error
