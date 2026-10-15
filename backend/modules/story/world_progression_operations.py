"""Pure operation-catalog entries for world progression (ADR-0038)."""

from __future__ import annotations

from core.container import get
from core.errors import ConflictError
from core.service_keys import ASSISTANT_IS_AUTHOR_TURN_RUN
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.story.generation import STORY_ONE_CLICK_ACTION
from modules.story.world_progression_budget import preview_progression_budget
from modules.story.world_progression_context import read_progression_source
from modules.story.world_progression_schemas import (
    ProgressionAdvanceRequest,
    ProgressionBudgetPreviewRequest,
    ProgressionCompareRequest,
    ProgressionHistoryRequest,
    ProgressionHookAdoptRequest,
    ProgressionHookPreviewRequest,
    ProgressionParticipant,
    ProgressionStartRequest,
    ProgressionTarget,
)
from modules.story.world_progression_service import (
    compare_progression_steps,
    get_progression_branch,
    get_progression_root,
    list_root_metrics,
    read_progression_history,
)


def _trace(model: type) -> dict:
    return {
        "parameter_fields": tuple(model.model_fields),
        "mode": "per_call",
        "parameter_policy": "schema_safe",
    }


def _metadata(
    *,
    description,
    risk,
    fee,
    produces,
    preconditions,
    transaction="single_transaction",
    reversibility="read_only",
):
    return {
        "op_version": "1",
        "description": description,
        "risk_level": risk,
        "fee_category": fee,
        "reversibility": reversibility,
        "preconditions": preconditions,
        "produces": produces,
        "target_type": "world_progression",
        "ai_available": True,
        "transaction_mode": transaction,
    }


def _require_project(novel_id: str, args) -> None:
    if str(args.novel_id) != str(novel_id):
        raise PermissionError("操作作品与当前作者工作范围不一致")


def _require_enabled() -> None:
    from modules.story.world_progression_api import _enabled

    _enabled()


def _model_name(snapshot: dict) -> str:
    return str((snapshot.get("profile") or {}).get("model") or "unknown")


async def _source(db, novel_id, args, *, snapshot=None):
    participants = [
        ProgressionParticipant.model_validate(item) for item in args.participants
    ]
    targets = [ProgressionTarget.model_validate(item) for item in args.targets]
    source = await read_progression_source(
        db,
        novel_id=novel_id,
        scene_id=args.scene_id,
        participants=participants,
        targets=targets,
    )
    if snapshot is not None:
        source["llm_execution_snapshot"] = snapshot
    return source


async def _prepare_budget(db, novel_id, args, *, context=None):
    _require_enabled()
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)
    snapshot = await build_project_llm_execution_snapshot(db, novel_id)
    source = await _source(db, novel_id, args, snapshot=snapshot)
    metrics = await list_root_metrics(db, novel_id)
    return preview_progression_budget(
        args, source, model_name=_model_name(snapshot), metrics=metrics
    )


async def _prepare_start(db, novel_id, args, *, context=None):
    preview = await _prepare_budget(db, novel_id, args, context=context)
    if preview["preview_hash"] != args.budget_preview_hash:
        raise ConflictError("世界、参与者或授权预算已变化，请重新预览")
    return preview


async def _apply_start(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    from modules.story.world_progression_api import api_start_progression

    result = await api_start_progression(args, db)
    return dict(result)


async def _prepare_history(db, novel_id, args, *, context=None):
    _require_enabled()
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)
    return await read_progression_history(
        db,
        novel_id,
        scene_id=args.scene_id,
        root_id=str(args.root_id) if args.root_id else None,
    )


async def _prepare_compare(db, novel_id, args, *, context=None):
    _require_enabled()
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)
    return await compare_progression_steps(
        db,
        novel_id=novel_id,
        first_step_id=str(args.first_step_id),
        second_step_id=str(args.second_step_id),
    )


async def _assert_author_turn(db, novel_id, args, context) -> dict:
    if context is None:
        raise PermissionError("R1 世界推进只能从已授权的普通作者助手回合执行")
    if not await get(ASSISTANT_IS_AUTHOR_TURN_RUN)(
        db,
        novel_id=str(novel_id),
        run_id=str(context.run_id),
        owner_id=str(context.owner_id),
    ):
        raise PermissionError("目标运行或自动任务不能代替普通作者助手推进世界")
    root = await get_progression_root(db, novel_id, str(args.root_id))
    branch = await get_progression_branch(db, novel_id, str(args.branch_id))
    if str(branch.root_id) != str(root.id):
        raise ConflictError("推进分支与运行根不匹配")
    if context.work.scene_id is None or str(context.work.scene_id) != str(root.scene_id):
        raise PermissionError("助手工作 Scene 与已授权世界推进截止点不一致")
    if context.work.context_confirmation_action != STORY_ONE_CLICK_ACTION or str(
        context.work.context_confirmation_id or ""
    ) != str(args.context_confirmation_id):
        raise PermissionError("助手必须沿用同一 Scene 的原资料确认")
    return {"root": root, "branch": branch}


async def _prepare_advance(db, novel_id, args, *, context=None):
    _require_enabled()
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)
    selected = await _assert_author_turn(db, novel_id, args, context)
    from infrastructure.llm.schemas import read_ai_run_envelope
    from modules.story.world_progression_service import get_progression_step

    root, branch = selected["root"], selected["branch"]
    parent = await get_progression_step(db, novel_id, str(args.parent_step_id))
    if str(parent.root_id) != str(root.id) or str(parent.branch_id) != str(branch.id):
        raise ConflictError("R1 推进父步骤与已授权分支不匹配")
    envelope = read_ai_run_envelope(root.run_envelope_json)
    if envelope is None or envelope.run_id != str(root.id):
        raise ConflictError("原运行累计预算不可恢复")
    if (
        envelope.requests_unknown
        or not envelope.usage_complete
        or envelope.requests_started / max(1, envelope.request_limit) >= 0.8
        or envelope.usage.total_tokens / max(1, envelope.token_limit) >= 0.8
    ):
        raise ConflictError("原运行已达到 80% 或包含未知计费请求，不能继续")
    return {
        "root_id": str(root.id),
        "branch_id": str(branch.id),
        "parent_step_id": str(parent.id),
        "basis_choice": args.basis_choice,
        "source_hash": branch.source_hash,
        "original_budget": {
            "requests_started": envelope.requests_started,
            "request_limit": envelope.request_limit,
            "tokens_used": envelope.usage.total_tokens,
            "token_limit": envelope.token_limit,
            "deadline_at": envelope.deadline_at.isoformat()
            if envelope.deadline_at
            else None,
        },
    }


async def _apply_advance(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    await _assert_author_turn(db, novel_id, args, context)
    from modules.story.world_progression_api import api_advance_progression

    return dict(await api_advance_progression(str(args.root_id), args, db))


async def _prepare_hook_preview(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    from modules.story.world_progression_hooks import api_progression_hook_preview

    return await api_progression_hook_preview(args, db)


async def _prepare_hook_adopt(db, novel_id, args, *, context=None):
    _require_enabled()
    _require_project(novel_id, args)
    from modules.story.world_progression_hooks import _prepare_hook_preview

    preview = await _prepare_hook_preview(db, args)
    if preview["preview_hash"] != args.preview_hash:
        raise ConflictError("钩子候选或滚动规划依据已变化，请重新预览")
    return {
        "root_id": str(args.root_id),
        "step_id": str(args.step_id),
        "hook_id": args.hook_id,
        "asset_type": args.asset_type,
        "preview_hash": preview["preview_hash"],
        "source_readset": preview["source_readset"],
        "draft": preview["draft"],
    }


async def _apply_hook_adopt(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    from modules.story.world_progression_hooks import api_progression_hook_adopt

    return await api_progression_hook_adopt(args, db)


async def _read_continuous(db, novel_id, args, *, context=None):
    _require_enabled()
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)
    from modules.story.world_progression_continuous import read_continuous_authorization

    current = await read_continuous_authorization(db, novel_id)
    if current.get("root_id") not in {None, str(args.root_id)}:
        raise ConflictError("持续授权已绑定到另一条推进根")
    return current


def _operation(
    *,
    label,
    schema,
    prepare,
    permission,
    description,
    risk,
    fee,
    produces,
    preconditions,
    apply=None,
    transaction="single_transaction",
    reversibility="read_only",
):
    return {
        "label": label,
        "schema": schema,
        "prepare": prepare,
        "apply": apply,
        "permission": permission,
        **_metadata(
            description=description,
            risk=risk,
            fee=fee,
            produces=produces,
            preconditions=preconditions,
            transaction=transaction,
            reversibility=reversibility,
        ),
        "trace_rule": _trace(schema),
    }


OPERATIONS_SPEC = {
    "story.world_progression.history": _operation(
        label="查看世界推进历史",
        schema=ProgressionHistoryRequest,
        prepare=_prepare_history,
        permission="read",
        description="读取作品的不可变步骤、分支与运行预算；不会续算或启动任务。",
        risk="R0",
        fee="free",
        produces=("world_progression_history",),
        preconditions=("当前作者可访问所选作品",),
    ),
    "story.world_progression.compare": _operation(
        label="比较世界推进步骤",
        schema=ProgressionCompareRequest,
        prepare=_prepare_compare,
        permission="read",
        description="比较同一运行中的两个不可变步骤及其依据状态。",
        risk="R0",
        fee="free",
        produces=("world_progression_comparison",),
        preconditions=("两个步骤都属于当前作品和同一运行",),
    ),
    "story.world_progression.preview": _operation(
        label="预览世界推进预算",
        schema=ProgressionBudgetPreviewRequest,
        prepare=_prepare_budget,
        permission="read",
        description=(
            "按当前截止 Scene、角色可知资料、步长和作者预算预览请求、Token、"
            "时限及费用状态；不调用模型，也不估算金额。"
        ),
        risk="R0",
        fee="free",
        produces=("world_progression_budget_preview",),
        preconditions=("参与者与目标属于当前作品",),
    ),
    "story.world_progression.start": _operation(
        label="准备世界推进运行",
        schema=ProgressionStartRequest,
        prepare=_prepare_start,
        apply=_apply_start,
        permission="confirm",
        description="在作者单独确认的根预算内，运行 simulation_v3 世界推进候选。",
        risk="R4",
        fee="possible_model_charge",
        produces=("world_progression_candidate_run",),
        preconditions=(
            "作者已确认当前 Evidence 资料与 Scene",
            "预算预览指纹仍匹配",
            "作者明确给出请求、Token 与时限预算",
        ),
        transaction="multi_stage",
        reversibility="history_restore_30_days",
    ),
    "story.world_progression.advance": _operation(
        label="沿已授权世界推进根推进一步",
        schema=ProgressionAdvanceRequest,
        prepare=_prepare_advance,
        apply=_apply_advance,
        permission="suggest",
        description=(
            "只在普通作者助手回合内，沿同一作品、Scene、参与者和资料确认"
            "使用原根预算推进一步；不加预算、不写正史。"
        ),
        risk="R1",
        fee="possible_model_charge",
        produces=("world_progression_candidate_step",),
        preconditions=(
            "真实普通作者助手回合",
            "同一 Scene 和资料确认",
            "原累计预算未到 80% 且无未知计费结果",
        ),
        transaction="multi_stage",
        reversibility="history_restore_30_days",
    ),
    "story.world_progression.preview_hook": _operation(
        label="预览世界推进钩子",
        schema=ProgressionHookPreviewRequest,
        prepare=_prepare_hook_preview,
        permission="read",
        description=(
            "用 story.plan_structure 的滚动窗口只读预览钩子来源与章节范围；"
            "不调用模型、不创建资产。"
        ),
        risk="R0",
        fee="free",
        produces=("world_progression_hook_preview",),
        preconditions=("钩子属于当前作品的不可变推进步骤",),
    ),
    "story.world_progression.adopt_hook": _operation(
        label="采用世界推进钩子为大纲候选",
        schema=ProgressionHookAdoptRequest,
        prepare=_prepare_hook_adopt,
        apply=_apply_hook_adopt,
        permission="confirm",
        description=(
            "作者确认后，将钩子采用为可编辑剧情线、篇章或计划 Scene；"
            "按 CAS 重验来源，不写 World、continuity 或正文。"
        ),
        risk="R3",
        fee="free",
        produces=("world_progression_outline_candidate",),
        preconditions=(
            "R3 作者确认仍然新鲜",
            "滚动窗口来源与预览指纹未变化",
            "所选钩子属于该不可变步骤",
        ),
        transaction="single_transaction",
        reversibility="domain_revision",
    ),
    "story.world_progression.read_continuous_authorization": _operation(
        label="查看持续推进授权",
        schema=ProgressionHistoryRequest,
        prepare=_read_continuous,
        permission="read",
        description="只读查看当前根的持续授权与原预算，不触发任务或改变授权。",
        risk="R0",
        fee="free",
        produces=("world_progression_continuous_authorization",),
        preconditions=("当前作者可访问所选作品",),
    ),
}
