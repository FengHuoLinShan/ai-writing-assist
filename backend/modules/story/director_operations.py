"""Pure operation catalog entries for author-confirmed Scene Director runs."""

from __future__ import annotations

from types import SimpleNamespace

from modules.project.facade import require_active_project
from modules.story.director_budget import (
    preview_director_budget,
    preview_director_continuation,
)
from modules.story.director_candidate_transfer import (
    preview_director_candidate_transfer,
    transfer_director_candidate,
)
from modules.story.director_context import read_director_source
from modules.story.director_schemas import (
    DirectorAdvanceRequest,
    DirectorBudgetPreviewRequest,
    DirectorCandidateTransferOperationRequest,
    DirectorConsistencyCheckRequest,
    DirectorContinueBudgetPreviewRequest,
    DirectorContinueRequest,
    DirectorHistoryReadRequest,
    DirectorSaveReferenceRequest,
    DirectorStartRequest,
)
from modules.story.director_service import (
    get_director_root,
    get_director_round,
    read_director_history_view,
    recheck_director_round_consistency,
    save_director_reference,
)


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


def _require_project(novel_id: str, args) -> None:
    if str(args.novel_id) != str(novel_id):
        raise PermissionError("操作作品与当前作者工作范围不一致")
    from modules.story.director_feature import require_scene_director_enabled

    require_scene_director_enabled()


async def _prepare_preview(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
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
    _require_project(novel_id, args)
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
    _require_project(novel_id, args)
    from modules.story.director_api import submit_director_start

    await require_active_project(db, novel_id)
    result = await submit_director_start(db, args)
    return result.model_dump(mode="json")


async def _continuation_preview(db, novel_id, args):
    _require_project(novel_id, args)
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
    if not (args.additional_requests or args.additional_tokens) and args.rounds == 1:
        raise ValueError("单轮且不追加额度请使用原预算推进入口")
    _root, _parent, preview = await _continuation_preview(db, novel_id, args)
    if preview["preview_hash"] != args.budget_preview_hash:
        raise ValueError("场景、人物或档案资料已变化，请重新预览预算")
    return preview


async def _apply_continue(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    from modules.story.director_api import continue_director_root

    await require_active_project(db, novel_id)
    parent, _ = await get_director_round(db, novel_id, str(args.parent_round_id))
    result = await continue_director_root(
        db,
        root_id=str(parent.root_id),
        data=args,
    )
    return result.model_dump(mode="json")


async def _prepare_advance(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    root, _parent, preview = await _continuation_preview(db, novel_id, args)
    if context is not None:
        from core.container import get
        from core.service_keys import ASSISTANT_IS_AUTHOR_TURN_RUN

        # This operation schedules a separate Director task. Its model calls are
        # charged only to the already-authorized Director root, never to the
        # surrounding Assistant turn. Goal runs have no assistant_turn task.
        if (
            not await get(ASSISTANT_IS_AUTHOR_TURN_RUN)(
                db,
                novel_id=str(novel_id),
                run_id=str(context.run_id),
                owner_id=str(context.owner_id),
            )
            or context.work.scene_id is None
            or str(context.work.scene_id) != str(root.scene_id)
        ):
            raise PermissionError("仅当前 Scene 的普通作者助手可使用已授权导演根推进")
        if context.work.context_confirmation_id is not None and str(
            context.work.context_confirmation_id
        ) != str(args.context_confirmation_id):
            raise PermissionError("助手资料确认与导演推进请求不一致")
    if preview["preview_hash"] != args.budget_preview_hash:
        raise ValueError("场景、人物或档案资料已变化，请重新预览预算")
    return preview


async def _apply_advance(db, novel_id, args, preview, *, context=None):
    from modules.story.director_api import continue_director_root

    _require_project(novel_id, args)
    await require_active_project(db, novel_id)
    parent, _ = await get_director_round(db, novel_id, str(args.parent_round_id))
    result = await continue_director_root(db, root_id=str(parent.root_id), data=args)
    return result.model_dump(mode="json")


async def _prepare_history(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)
    return await read_director_history_view(db, novel_id, args.scene_id)


async def _prepare_consistency(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)
    return await recheck_director_round_consistency(db, novel_id, str(args.round_id))


async def _apply_consistency(db, novel_id, args, preview, *, context=None):
    return preview


async def _prepare_save_reference(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)
    row, _ = await get_director_round(db, novel_id, str(args.source_round_id))
    return {
        "source_round_id": str(row.id),
        "source_hash": row.source_hash,
        "output_hash": row.output_hash,
        "selected_material_ids": list(args.material_ids),
        "name": args.name,
    }


async def _apply_save_reference(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    row, _ = await get_director_round(db, novel_id, str(args.source_round_id))
    if (
        preview.get("source_hash") != row.source_hash
        or preview.get("output_hash") != row.output_hash
    ):
        raise ValueError("导演来源回合已变化，请重新核对")
    return await save_director_reference(
        db, novel_id, args, origin="author_via_assistant"
    )


async def _prepare_transfer_candidate(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    return await preview_director_candidate_transfer(db, str(args.round_id), args)


async def _apply_transfer_candidate(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    receipt = await transfer_director_candidate(db, str(args.round_id), args)
    return receipt.model_dump(mode="json")


OPERATIONS_SPEC = {
    "story.scene_director.transfer_world_candidate": {
        "label": "转入 World 待审核候选",
        "schema": DirectorCandidateTransferOperationRequest,
        "prepare": _prepare_transfer_candidate,
        "apply": _apply_transfer_candidate,
        "permission": "confirm",
        **_metadata(
            description=(
                "作者逐项确认冻结导演事件或对象引用后，创建一个有来源的 World "
                "待审核候选；不会成为正史。"
            ),
            risk="R3",
            fee="free",
            produces=("world_entity_candidate", "director_transfer_receipt"),
            preconditions=(
                "精确导演回合及输出指纹仍有效",
                "作者确认对象引用的类别；剧情事件只能转为事件",
                "当前 Scene 来源未变化",
            ),
            reversibility="candidate_review_required",
        ),
        "trace_rule": _trace(DirectorCandidateTransferOperationRequest),
    },
    "story.scene_director.history": {
        "label": "查看场景导演历史",
        "schema": DirectorHistoryReadRequest,
        "prepare": _prepare_history,
        "apply": None,
        "permission": "read",
        **_metadata(
            description="按当前作品和 Scene 查看导演根、分支、回合与参考副本。",
            risk="R0",
            fee="free",
            produces=("scene_director_history",),
            preconditions=("当前作者可访问所选作品",),
            reversibility="read_only",
        ),
        "trace_rule": _trace(DirectorHistoryReadRequest),
    },
    "story.scene_director.check_consistency": {
        "label": "核对导演回合一致性",
        "schema": DirectorConsistencyCheckRequest,
        "prepare": _prepare_consistency,
        "apply": _apply_consistency,
        "permission": "suggest",
        **_metadata(
            description="用当前确认来源重算精确结构化冲突；来源变化时旧知情、感知和身份结论保持未知，不改冻结回合。",
            risk="R1",
            fee="free",
            produces=("scene_director_consistency",),
            preconditions=("回合属于当前作品且未被作者删除",),
            reversibility="read_only",
        ),
        "trace_rule": _trace(DirectorConsistencyCheckRequest),
    },
    "story.scene_director.advance": {
        "label": "沿导演历史推进一轮",
        "schema": DirectorAdvanceRequest,
        "prepare": _prepare_advance,
        "apply": _apply_advance,
        "permission": "suggest",
        **_metadata(
            description="在现有导演根的剩余额度内推进一轮，不追加请求、Token 或时限。",
            risk="R1",
            fee="possible_model_charge",
            produces=("scene_director_candidate_branch",),
            preconditions=(
                "父回合属于当前作品",
                "原根账本完整且未达 80% 停止边界",
                "已有作者确认的 Scene 资料范围仍有效",
            ),
            transaction="multi_stage",
            reversibility="history_restore_30_days",
        ),
        "trace_rule": _trace(DirectorAdvanceRequest),
    },
    "story.scene_director.save_reference": {
        "label": "存为场景导演参考剧本",
        "schema": DirectorSaveReferenceRequest,
        "prepare": _prepare_save_reference,
        "apply": _apply_save_reference,
        "permission": "confirm",
        **_metadata(
            description="把作者确认的素材和角度保存为独立内容副本，来源记为作者经助手。",
            risk="R2",
            fee="free",
            produces=("scene_director_reference_copy",),
            preconditions=("来源回合属于当前作品", "作者确认所选素材与角度"),
            reversibility="soft_delete_restore_30_days",
        ),
        "trace_rule": _trace(DirectorSaveReferenceRequest),
    },
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
