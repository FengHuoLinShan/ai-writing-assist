"""Pure operation catalog entries for author-confirmed Scene Director runs."""

from __future__ import annotations

from types import SimpleNamespace

from modules.project.facade import require_active_project
from modules.story.director_budget import (
    preview_director_budget,
    preview_director_continuation,
)
from modules.story.director_context import read_director_source
from modules.story.director_schemas import (
    DirectorBudgetPreviewRequest,
    DirectorContinueBudgetPreviewRequest,
    DirectorContinueRequest,
    DirectorStartRequest,
)
from modules.story.director_service import get_director_root, get_director_round


def _trace(model: type) -> dict:
    return {
        "parameter_fields": tuple(model.model_fields),
        "mode": "per_call",
        "parameter_policy": "schema_safe",
    }


def _metadata(
    *,
    description: str,
    risk: str,
    fee: str,
    produces: tuple[str, ...],
    preconditions: tuple[str, ...],
    transaction: str = "single_transaction",
    reversibility: str = "history_restore",
):
    return {
        "op_version": "1",
        "description": description,
        "risk_level": risk,
        "fee_category": fee,
        "reversibility": reversibility,
        "preconditions": preconditions,
        "produces": produces,
        "target_type": "scene_director",
        "ai_available": True,
        "transaction_mode": transaction,
    }


async def _prepare_preview(db, novel_id, args, *, context=None):
    await require_active_project(db, novel_id)
    source = await read_director_source(
        db,
        novel_id=novel_id,
        scene_id=args.scene_id,
        character_ids=args.character_ids,
        related_object_ids=args.related_object_ids,
    )
    return preview_director_budget(args, source)


async def _prepare_continue_preview(db, novel_id, args, *, context=None):
    root, _parent, preview = await _continuation_preview(db, novel_id, args)
    envelope = root.run_envelope_json or {}
    usage = envelope.get("usage") or {}
    preview["current_budget"] = {
        "requests_used": int(envelope.get("requests_started") or 0),
        "requests_authorized": envelope.get("request_limit"),
        "tokens_used": int(usage.get("total_tokens") or 0),
        "tokens_authorized": envelope.get("token_limit"),
        "unknown_requests": int(envelope.get("requests_unknown") or 0),
        "started_at": envelope.get("started_at"),
        "deadline_at": envelope.get("deadline_at"),
    }
    return preview


async def _prepare_start(db, novel_id, args, *, context=None):
    preview = await _prepare_preview(db, novel_id, args, context=context)
    if preview["preview_hash"] != args.budget_preview_hash:
        raise ValueError("场景、人物或档案资料已变化，请重新预览预算")
    return preview


async def _apply_start(db, novel_id, args, preview, *, context=None):
    from modules.story.director_api import submit_director_start

    await require_active_project(db, novel_id)
    result = await submit_director_start(db, args)
    return result.model_dump(mode="json")


async def _continuation_preview(db, novel_id, args):
    await require_active_project(db, novel_id)
    parent, _ = await get_director_round(db, novel_id, str(args.parent_round_id))
    root = await get_director_root(db, novel_id, str(parent.root_id))
    current_source = await read_director_source(
        db,
        novel_id=novel_id,
        scene_id=str(root.scene_id),
        character_ids=list((root.request_json or {}).get("character_ids") or []),
        related_object_ids=list(
            (root.request_json or {}).get("related_object_ids") or []
        ),
    )
    frozen_source = (parent.input_json or {}).get("source_snapshot")
    if not isinstance(frozen_source, dict):
        raise ValueError("所选回合缺少可恢复的来源快照")
    source = current_source if args.basis_choice == "current" else frozen_source
    intervention = args.intervention
    if args.selected_alternative:
        alternative = next(
            (
                item
                for item in (parent.output_json or {}).get("alternatives", [])
                if item.get("alternative_id") == args.selected_alternative
            ),
            None,
        )
        if alternative is None:
            raise ValueError("所选分支方案不属于这个回合")
        intervention = "\n\n".join(
            item
            for item in (
                intervention.strip(),
                str(alternative.get("branch_instruction") or "").strip(),
            )
            if item
        )
    request = SimpleNamespace(
        scene_id=str(root.scene_id),
        character_ids=list((root.request_json or {}).get("character_ids") or []),
        related_object_ids=list(
            (root.request_json or {}).get("related_object_ids") or []
        ),
        primary_character_ids=list(
            (root.request_json or {}).get("primary_character_ids") or []
        ),
        rounds=args.rounds,
        instructions=args.instructions,
        intervention=intervention,
        public_stimulus=args.public_stimulus,
        branch_kind=args.branch_kind,
        basis_choice=args.basis_choice,
        rewrite_character_id=args.rewrite_character_id,
        selected_alternative=args.selected_alternative,
    )
    return (
        root,
        parent,
        preview_director_continuation(
            request,
            source,
            parent_round_id=str(parent.id),
        ),
    )


async def _prepare_continue(db, novel_id, args, *, context=None):
    _root, _parent, preview = await _continuation_preview(db, novel_id, args)
    if preview["preview_hash"] != args.budget_preview_hash:
        raise ValueError("场景、人物或档案资料已变化，请重新预览预算")
    return preview


async def _apply_continue(db, novel_id, args, preview, *, context=None):
    from modules.story.director_api import continue_director_root

    await require_active_project(db, novel_id)
    parent, _ = await get_director_round(db, novel_id, str(args.parent_round_id))
    result = await continue_director_root(
        db,
        root_id=str(parent.root_id),
        data=args,
    )
    return result.model_dump(mode="json")


OPERATIONS_SPEC = {
    "story.scene_director.preview": {
        "label": "预览场景导演预算",
        "schema": DirectorBudgetPreviewRequest,
        "prepare": _prepare_preview,
        "apply": None,
        "permission": "read",
        **_metadata(
            description=(
                "按当前 Scene 与人物可知资料估算回合数、请求数、Token 与耗时区间；"
                "不请求模型、不显示金额。"
            ),
            risk="R0",
            fee="free",
            produces=("scene_director_budget_preview",),
            preconditions=("Scene 和对象身份属于当前作品",),
            reversibility="discard_preview",
        ),
        "trace_rule": _trace(DirectorBudgetPreviewRequest),
    },
    "story.scene_director.start": {
        "label": "开始场景排演",
        "schema": DirectorStartRequest,
        "prepare": _prepare_start,
        "apply": _apply_start,
        "permission": "confirm",
        **_metadata(
            description=(
                "在逐人物隔离意图、有限结算与候选历史中排演指定 Scene；"
                "不会写正文、正史或采用剧本。"
            ),
            risk="R4",
            fee="possible_model_charge",
            produces=("scene_director_candidate_history",),
            preconditions=(
                "作者确认 Evidence 资料范围",
                "预算预览指纹仍匹配",
                "作者已明确请求数和 Token 上限",
            ),
            transaction="multi_stage",
            reversibility="history_restore_30_days",
        ),
        "trace_rule": _trace(DirectorStartRequest),
    },
    "story.scene_director.continue_preview": {
        "label": "预览导演续算预算",
        "schema": DirectorContinueBudgetPreviewRequest,
        "prepare": _prepare_continue_preview,
        "apply": None,
        "permission": "read",
        **_metadata(
            description=(
                "基于所选父回合预览同一累计运行下新增分支的请求、Token "
                + "与剩余时限区间。"
            ),
            risk="R0",
            fee="free",
            produces=("scene_director_continuation_preview",),
            preconditions=("父回合属于当前导演运行", "当前或冻结来源依据明确"),
            reversibility="discard_preview",
        ),
        "trace_rule": _trace(DirectorContinueBudgetPreviewRequest),
    },
    "story.scene_director.continue": {
        "label": "在同一预算下继续场景排演",
        "schema": DirectorContinueRequest,
        "prepare": _prepare_continue,
        "apply": _apply_continue,
        "permission": "confirm",
        **_metadata(
            description="从指定的不可变导演回合继续、重排、介入或单人物重写，并在同一累计账本上增加作者明确授予的额度。",
            risk="R4",
            fee="possible_model_charge",
            produces=("scene_director_candidate_branch",),
            preconditions=(
                "作者确认当前或冻结资料依据",
                "续算额度由作者明确增加",
                "可能重复计费时作者单独确认",
            ),
            transaction="multi_stage",
            reversibility="history_restore_30_days",
        ),
        "trace_rule": _trace(DirectorContinueRequest),
    },
}
