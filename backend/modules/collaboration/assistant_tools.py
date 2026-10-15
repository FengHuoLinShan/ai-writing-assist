"""Author-confirmed operation catalog for existing isolated collaboration workspaces."""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.token_estimation import estimate_token_count
from infrastructure.tasks.registry import TaskRegistry
from modules.account.facade import current_account_id
from modules.collaboration import cases, workspaces
from modules.collaboration.contracts import (
    Grant,
    InputManifest,
    MergeRequest,
    ResourcePatch,
    RunCreate,
    WorkspaceCreate,
    WorkspaceEdit,
)
from modules.collaboration.creative_manifest import (
    collect_creative_manifest,
    creative_context_text,
    revalidate_creative_manifest,
)
from modules.collaboration.merge import merge_workspace
from modules.collaboration.models import (
    CollaborationRun,
    CreativeMergeReceipt,
    CreativeWorkspace,
)
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
    require_active_project_exclusive,
)

CHECK_TASK_TYPE = "collaboration_run"
CHECK_ROOT_CAPABILITY = "collaboration.run"


class StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateWorkspaceArgs(StrictArgs):
    case_id: UUID
    operation_id: UUID
    label: str = Field(min_length=1, max_length=200)
    parent_revision_id: UUID | None = None
    expected_preview_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmed: bool = False


class WorkspaceEditArgs(StrictArgs):
    workspace_id: UUID
    expected_revision_id: UUID
    patches: list[ResourcePatch] = Field(min_length=1, max_length=16)
    expected_preview_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmed: bool = False


class WorkspaceInspectArgs(StrictArgs):
    workspace_id: UUID
    revision_id: UUID | None = None


class WorkspaceSealArgs(StrictArgs):
    workspace_id: UUID
    revision_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_preview_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmed: bool = False


class WorkspaceCheckArgs(StrictArgs):
    workspace_id: UUID
    operation_id: UUID
    expected_goal_version: int = Field(ge=1)
    workspace_revision_id: UUID
    expected_preview_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmed: bool = False


class AtomicAdoptionArgs(StrictArgs):
    workspace_id: UUID
    revision_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation_id: UUID
    editor_state: Literal["saved", "dirty"]
    expected_preview_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmed: bool = False


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _require_case_owner(db, novel_id, case_id, *, lock=False, execute=False):
    await require_active_project(db, str(novel_id))
    case = await cases.require_case(
        db, str(novel_id), str(case_id), lock=lock, execute=execute
    )
    if str(case.owner_id) != str(current_account_id()):
        raise NotFoundError("创作任务不可访问")
    return case


async def _create_prepare(db, novel_id, args, *, context=None):
    case = await _require_case_owner(db, novel_id, args.case_id, execute=True)
    grant = Grant.model_validate(case.grant_json)
    manifest = await collect_creative_manifest(
        db, str(novel_id), grant, case.goal_version
    )
    creative_context_text(manifest)
    parent_id = None
    if args.parent_revision_id:
        parent_workspace, parent = await workspaces.require_revision(
            db, str(novel_id), args.parent_revision_id
        )
        if parent_workspace.case_id != case.id:
            raise ConflictError("不能混合不同目标的试改版本")
        parent_id = str(parent.id)
    return {
        "case_id": str(case.id),
        "goal_version": case.goal_version,
        "grant_hash": content_hash(case.grant_json),
        "operation_id": str(args.operation_id),
        "label": args.label,
        "parent_revision_id": parent_id,
        "baseline_fingerprint": manifest.fingerprint,
        "resource_count": len(manifest.resources),
        "effect": "创建隔离试改基线，不修改作品正文、世界设定或授权。",
    }


async def _create_apply(db, novel_id, args, preview, *, context=None):
    if context is None and (not args.confirmed or not args.expected_preview_hash):
        raise ConflictError("请确认创建这份隔离试改", code="CONFIRMATION_REQUIRED")
    prior = await db.scalar(
        select(CreativeWorkspace).where(
            CreativeWorkspace.novel_id == UUID(str(novel_id)),
            CreativeWorkspace.operation_id == args.operation_id,
        )
    )
    if prior is not None:
        return await workspaces.create_workspace(
            db,
            str(novel_id),
            args.case_id,
            WorkspaceCreate(
                operation_id=args.operation_id,
                label=args.label,
                parent_revision_id=args.parent_revision_id,
            ),
        )
    current = await _create_prepare(db, novel_id, args, context=context)
    if preview is not None and current != preview:
        raise ConflictError("目标或授权资料已变化，请重新准备", code="GOAL_CHANGED")
    if context is None and args.expected_preview_hash != _hash(current):
        raise ConflictError("目标或授权资料已变化，请重新准备", code="PREVIEW_STALE")
    return await workspaces.create_workspace(
        db,
        str(novel_id),
        args.case_id,
        WorkspaceCreate(
            operation_id=args.operation_id,
            label=args.label,
            parent_revision_id=args.parent_revision_id,
        ),
    )


async def _edit_prepare(db, novel_id, args, *, context=None):
    workspace = await workspaces.require_workspace(
        db, str(novel_id), args.workspace_id, execute=True
    )
    case = await _require_case_owner(db, novel_id, workspace.case_id, execute=True)
    parent_workspace, parent = await workspaces.require_revision(
        db, str(novel_id), args.expected_revision_id
    )
    if parent_workspace.id != workspace.id:
        raise NotFoundError("修订不属于此试改")
    if parent.goal_version != case.goal_version:
        raise ConflictError("作者目标已变化，请重建试改", code="GOAL_CHANGED")
    grant = Grant.model_validate(case.grant_json)
    keys = [patch.key for patch in args.patches]
    if len(keys) != len(set(keys)) or set(keys) - {ref.key for ref in grant.resources}:
        raise ValidationError("试改超出授权资源或重复覆盖", code="GRANT_SCOPE_CONFLICT")
    cumulative = {
        value["kind"] + ":" + value["id"]: value for value in parent.patches_json
    }
    cumulative.update(
        {patch.key: patch.model_dump(mode="json") for patch in args.patches}
    )
    values = list(cumulative.values())
    workspaces.overlay(InputManifest.model_validate(parent.manifest_json), values)
    if workspace.current_revision_id != args.expected_revision_id:
        replay = await workspaces._find_edit_replay(
            db,
            str(novel_id),
            workspace_id=workspace.id,
            parent_revision_id=parent.id,
            patches=values,
        )
        if replay is None:
            raise ConflictError("试改版本已变化，请重新读取", code="WORKSPACE_CHANGED")
    return {
        "workspace_id": str(workspace.id),
        "case_id": str(case.id),
        "goal_version": case.goal_version,
        "expected_revision_id": str(parent.id),
        "before_digest": parent.digest,
        "patches": [patch.model_dump(mode="json") for patch in args.patches],
        "effect": "只创建新的隔离覆盖修订；作者资产保持不变。",
    }


async def _edit_apply(db, novel_id, args, preview, *, context=None):
    if context is None and (not args.confirmed or not args.expected_preview_hash):
        raise ConflictError("请确认保存这份隔离试改", code="CONFIRMATION_REQUIRED")
    current = await _edit_prepare(db, novel_id, args, context=context)
    if current != preview or (
        context is None and args.expected_preview_hash != _hash(current)
    ):
        raise ConflictError("试改版本或授权范围已变化", code="WORKSPACE_CHANGED")
    return await workspaces.edit_workspace(
        db,
        str(novel_id),
        args.workspace_id,
        WorkspaceEdit(
            expected_revision_id=args.expected_revision_id,
            patches=args.patches,
        ),
    )


async def _inspect_prepare(db, novel_id, args, *, context=None):
    return await workspaces.workspace_view(
        db,
        str(novel_id),
        args.workspace_id,
        revision_id=args.revision_id,
    )


async def _seal_prepare(db, novel_id, args, *, context=None):
    workspace = await workspaces.require_workspace(
        db, str(novel_id), args.workspace_id, execute=True
    )
    _case = await _require_case_owner(db, novel_id, workspace.case_id, execute=True)
    _revision_workspace, revision = await workspaces.require_revision(
        db, str(novel_id), args.revision_id
    )
    if (
        revision.workspace_id != workspace.id
        or workspace.current_revision_id != revision.id
        or revision.digest != args.expected_digest
    ):
        raise ConflictError("待封存版本已变化", code="WORKSPACE_CHANGED")
    view = await workspaces.workspace_view(
        db, str(novel_id), workspace.id, revision_id=revision.id
    )
    if (
        view["stale"]
        or not view["can_seal"]
        or workspace.status not in {"open", "sealed"}
    ):
        raise ConflictError("资料已变化或检查未通过，不能封存", code="CHECK_REQUIRED")
    return {
        "workspace_id": str(workspace.id),
        "revision_id": str(revision.id),
        "digest": revision.digest,
        "goal_version": revision.goal_version,
        "changes": view["changes"],
        "effect": "只封存隔离试改版本；这一步不会写入作品资产。",
    }


async def _seal_apply(db, novel_id, args, preview, *, context=None):
    if context is None and not args.confirmed:
        raise ConflictError("请确认封存这份试改", code="CONFIRMATION_REQUIRED")
    current = await _seal_prepare(db, novel_id, args, context=context)
    if current != preview or (
        context is None and args.expected_preview_hash != _hash(current)
    ):
        raise ConflictError("试改或资料已变化，请重新读取", code="WORKSPACE_CHANGED")
    from modules.collaboration.contracts import RevisionRequest

    return await workspaces.seal_workspace(
        db,
        str(novel_id),
        args.workspace_id,
        RevisionRequest(
            revision_id=args.revision_id, expected_digest=args.expected_digest
        ),
    )


async def _check_prepare(db, novel_id, args, *, context=None):
    if TaskRegistry().get_root_capability(CHECK_TASK_TYPE) != CHECK_ROOT_CAPABILITY:
        raise ConflictError("创作试改任务根未注册", code="TASK_ROOT_UNAVAILABLE")
    definition = TaskRegistry().get_definition(CHECK_TASK_TYPE)
    if (
        definition is None
        or definition.recovery_policy != "manual_resume"
        or definition.run_request_limit != 30
        or definition.run_deadline_seconds != 1800
    ):
        raise ConflictError("创作试改预算或恢复契约不可用", code="TASK_ROOT_UNAVAILABLE")
    workspace = await workspaces.require_workspace(
        db, str(novel_id), args.workspace_id, execute=True
    )
    case = await _require_case_owner(db, novel_id, workspace.case_id, execute=True)
    if case.goal_version != args.expected_goal_version:
        raise ConflictError("作者目标已变化", code="GOAL_CHANGED")
    if case.requests_used + 4 > Grant.model_validate(case.grant_json).request_limit:
        raise ConflictError("累计额度不足以完成生成与复核", code="BUDGET_EXCEEDED")
    active_id = await db.scalar(
        select(CollaborationRun.id).where(
            CollaborationRun.case_id == case.id,
            CollaborationRun.novel_id == case.novel_id,
            CollaborationRun.status.in_(["pending", "running"]),
        )
    )
    if active_id:
        raise ConflictError("此创作任务仍在运行", code="ACTIVE_RUN_CONFLICT")
    if workspace.current_revision_id != args.workspace_revision_id:
        raise ConflictError("试改版本已变化", code="WORKSPACE_CHANGED")
    revision_workspace, revision = await workspaces.require_revision(
        db, str(novel_id), args.workspace_revision_id
    )
    if (
        revision_workspace.id != workspace.id
        or revision.goal_version != case.goal_version
    ):
        raise ConflictError("待检查版本不属于当前目标", code="WORKSPACE_CHANGED")
    view = await workspaces.workspace_view(
        db, str(novel_id), workspace.id, revision_id=revision.id
    )
    if view["stale"]:
        raise ConflictError(
            "资料或目标已变化，请基于当前资料重建试改", code="SOURCE_STALE"
        )
    manifest = InputManifest.model_validate(revision.manifest_json)
    grant = Grant.model_validate(case.grant_json)
    await revalidate_creative_manifest(db, str(novel_id), grant, manifest)
    candidate = manifest.model_copy(
        update={
            "resources": workspaces.overlay(manifest, revision.patches_json),
            "workspace_revision_id": revision.id,
        }
    )
    material = creative_context_text(candidate)
    snapshot = await build_project_llm_execution_snapshot(db, str(novel_id))
    role_snapshots = {
        role: await build_project_llm_execution_snapshot(
            db, str(novel_id), provider_id=provider_id
        )
        for role, provider_id in grant.model_connections.items()
    }
    web_snapshot = None
    if grant.allow_web:
        from infrastructure.llm.web_search import search_snapshot

        web_snapshot = search_snapshot()
    budget = Grant.model_validate(case.grant_json)
    safe = {
        "workspace_id": str(workspace.id),
        "case_id": str(case.id),
        "goal_version": case.goal_version,
        "workspace_revision_id": str(revision.id),
        "workspace_digest": revision.digest,
        "grant_hash": manifest.grant_hash,
        "manifest_fingerprint": manifest.fingerprint,
        "selected_material_count": len(manifest.resources),
        "selected_material_kinds": sorted({item.kind for item in manifest.resources}),
        "estimated_selected_material_tokens": estimate_token_count(
            material, model=(snapshot.get("profile") or {}).get("model")
        ),
        "author_project_snapshot_fingerprint": content_hash(snapshot),
        "role_snapshot_fingerprints": {
            key: content_hash(value) for key, value in role_snapshots.items()
        },
        "web_search_selected": bool(web_snapshot),
        "case_requests_used": case.requests_used,
        "case_request_limit": budget.request_limit,
        "case_requests_remaining": max(0, budget.request_limit - case.requests_used),
        "run_request_limit": budget.run_request_limit,
        "minimum_requests_required": 4,
        "task_root_capability_id": CHECK_ROOT_CAPABILITY,
        "task_request_limit": definition.run_request_limit,
        "task_max_attempts": definition.max_attempts,
        "task_recovery_policy": definition.recovery_policy,
        "task_deadline_seconds": definition.run_deadline_seconds,
        "envelope_version": 2,
        "task_token_limit": definition.run_token_limit,
        "domain_token_limit": None,
        "domain_budget_started_at_semantics": (
            "提交时冻结在CollaborationRun budget_json；恢复沿用原started_at和累计用量。"
        ),
        "envelope_started_at_semantics": (
            "首个worker领取时冻结；manual_resume沿用同一run信封和deadline。"
        ),
        "unknown_charge_stop_policy": (
            "AgentRunBudget 在每次 provider 预留前 fail closed；"
            "manual_resume 对 usage_unknown 拒绝。"
        ),
        "possible_charge": True,
        "source_stale": False,
        "effect": "准备只读取已授权资料并校验精确试改；未创建运行、未排队、未调用模型。",
    }
    safe["preview_hash"] = _hash(
        {
            **safe,
            "operation_id": str(args.operation_id),
            "expected_goal_version": args.expected_goal_version,
        }
    )
    return safe


async def _check_apply(db, novel_id, args, preview, *, context=None):
    if context is not None:
        raise ConflictError(
            (
                "Collaboration 试改使用独立 collaboration.run 根；"
                "请在创作试验工作台单独核对资料与预算并确认。"
            ),
            code="ROOT_BUDGET_ADAPTER_UNAVAILABLE",
        )
    if context is None and not args.confirmed:
        raise ConflictError("单独确认后才会创建模型试验", code="CONFIRMATION_REQUIRED")
    request = f"preview:{args.expected_preview_hash or ''}"
    existing = await db.scalar(
        select(CollaborationRun).where(
            CollaborationRun.novel_id == UUID(str(novel_id)),
            CollaborationRun.operation_id == args.operation_id,
        )
    )
    if existing is not None:
        await _require_case_owner(db, novel_id, existing.case_id, execute=True)
        return await cases.submit_run(
            db,
            str(novel_id),
            str(existing.case_id),
            RunCreate(
                operation_id=args.operation_id,
                expected_goal_version=args.expected_goal_version,
                workspace_revision_id=args.workspace_revision_id,
                request=request,
            ),
        )
    await require_active_project_exclusive(db, str(novel_id))
    current = await _check_prepare(db, novel_id, args, context=context)
    if (
        (preview is not None and current != preview)
        or not args.expected_preview_hash
        or current["preview_hash"] != args.expected_preview_hash
    ):
        raise ConflictError(
            "授权、资料或试改版本已变化，请重新预览", code="PREVIEW_STALE"
        )
    return await cases.submit_run(
        db,
        str(novel_id),
        str(current["case_id"]),
        RunCreate(
            operation_id=args.operation_id,
            expected_goal_version=args.expected_goal_version,
            workspace_revision_id=args.workspace_revision_id,
            request=request,
        ),
    )


async def _check_read_result(db, novel_id, args, *, context=None):
    try:
        run = await cases.require_run(db, str(novel_id), str(args.operation_id))
    except NotFoundError:
        return {"status": "not_submitted", "preview_only": True}
    if str(run.case_id) != str(
        (await workspaces.require_workspace(db, str(novel_id), args.workspace_id)).case_id
    ):
        raise NotFoundError("试验回执不可访问")
    return {
        "run_id": str(run.id),
        "task_id": str(run.task_id) if run.task_id else None,
        "status": run.status,
        "usage": run.budget_json,
        "error_code": run.error_code,
        "root_capability_id": CHECK_ROOT_CAPABILITY,
    }


async def _atomic_prepare(db, novel_id, args, *, context=None):
    workspace = await workspaces.require_workspace(
        db, str(novel_id), args.workspace_id, execute=True
    )
    case = await _require_case_owner(db, novel_id, workspace.case_id, execute=True)
    revision_workspace, revision = await workspaces.require_revision(
        db, str(novel_id), args.revision_id
    )
    if (
        revision_workspace.id != workspace.id
        or workspace.current_revision_id != revision.id
        or revision.digest != args.expected_digest
        or args.editor_state != "saved"
    ):
        raise ConflictError("待采用试改已变化或尚未保存", code="WORKSPACE_CHANGED")
    if workspace.status != "sealed" or case.goal_version != revision.goal_version:
        raise ConflictError("请重新检查并封存当前目标下的试改", code="CHECK_REQUIRED")
    check = await workspaces.checked_revision(db, str(novel_id), revision)
    grant = Grant.model_validate(case.grant_json)
    manifest = InputManifest.model_validate(revision.manifest_json)
    patches = [ResourcePatch.model_validate(item) for item in revision.patches_json]
    if not 1 <= len(patches) <= 16:
        raise ValidationError("一次采用需要一至十六项具体修改")
    if {patch.key for patch in patches} - {ref.key for ref in grant.resources}:
        raise ConflictError("试改超出本次授权", code="GRANT_SCOPE_CONFLICT")
    await revalidate_creative_manifest(db, str(novel_id), grant, manifest)
    view = await workspaces.workspace_view(
        db, str(novel_id), workspace.id, revision_id=revision.id
    )
    if view["stale"]:
        raise ConflictError("来源或目标已经变化，请重新检查试改", code="SOURCE_STALE")
    safe = {
        "workspace_id": str(workspace.id),
        "case_id": str(case.id),
        "revision_id": str(revision.id),
        "digest": revision.digest,
        "goal_version": revision.goal_version,
        "grant_hash": content_hash(case.grant_json),
        "manifest_fingerprint": manifest.fingerprint,
        "check_receipt_id": str(check.id),
        "read_set": [
            {
                "key": source.key,
                "kind": source.kind,
                "id": str(source.id),
                "label": source.label,
                "revision": source.revision,
                "source_hash": source.source_hash,
            }
            for source in manifest.resources
        ],
        "patch_set": sorted(patch.key for patch in patches),
        "changes": view["changes"],
        "author_confirmation_required": True,
        "effect": (
            "确认后由现有原子 merge 一次性应用整组跨域修改，"
            "并写入 merge receipt 与 outbox。"
        ),
    }
    safe["preview_hash"] = _hash(safe)
    return safe


async def _atomic_apply(db, novel_id, args, preview, *, context=None):
    if context is not None and getattr(context, "trace_actor_type", None) == "goal":
        raise ConflictError(
            "这次跨域采用需作者核对完整差异并单独确认",
            code="DOMAIN_CONFIRMATION_REQUIRED",
        )
    if context is None and (not args.confirmed or not args.expected_preview_hash):
        raise ConflictError(
            "每次采用都需要作者确认刚核对的预览", code="CONFIRMATION_REQUIRED"
        )
    prior = await db.scalar(
        select(CreativeMergeReceipt).where(
            CreativeMergeReceipt.novel_id == UUID(str(novel_id)),
            CreativeMergeReceipt.operation_id == args.operation_id,
        )
    )
    if prior is not None:
        return await merge_workspace(
            db,
            str(novel_id),
            args.workspace_id,
            MergeRequest(
                revision_id=args.revision_id,
                expected_digest=args.expected_digest,
                operation_id=args.operation_id,
                confirmed=True,
                editor_state=args.editor_state,
                expected_preview_hash=args.expected_preview_hash,
            ),
        )
    current = await _atomic_prepare(db, novel_id, args, context=context)
    if preview is not None and current != preview:
        raise ConflictError(
            "试改、资料或检查回执已变化，请重新准备", code="PREVIEW_STALE"
        )
    if (context is None and args.expected_preview_hash is None) or (
        args.expected_preview_hash is not None
        and args.expected_preview_hash != current["preview_hash"]
    ):
        raise ConflictError(
            "试改、资料或检查回执已变化，请重新准备", code="PREVIEW_STALE"
        )
    return await merge_workspace(
        db,
        str(novel_id),
        args.workspace_id,
        MergeRequest(
            revision_id=args.revision_id,
            expected_digest=args.expected_digest,
            operation_id=args.operation_id,
            confirmed=True,
            editor_state=args.editor_state,
            expected_preview_hash=args.expected_preview_hash,
        ),
    )


async def _atomic_read_result(db, novel_id, args, *, context=None):
    receipt = await db.scalar(
        select(CreativeMergeReceipt).where(
            CreativeMergeReceipt.novel_id == UUID(str(novel_id)),
            CreativeMergeReceipt.operation_id == args.operation_id,
        )
    )
    if receipt is None:
        return {"status": "not_applied", "preview_only": True}
    if receipt.revision_id != args.revision_id:
        raise ConflictError("采用标识已用于其他试改", code="OPERATION_MISMATCH")
    return {
        "status": "applied",
        "receipt_id": str(receipt.id),
        "revision_id": str(receipt.revision_id),
        "digest": receipt.digest,
        "authorization": receipt.authorization,
    }


def _meta(
    *,
    description,
    risk,
    fee,
    reversible,
    preconditions,
    produces,
    target,
    fields,
    transaction="single_transaction",
    permission=None,
):
    return {
        "op_version": "1",
        "description": description,
        "risk_level": risk,
        "fee_category": fee,
        "reversibility": reversible,
        "preconditions": preconditions,
        "produces": produces,
        "target_type": target,
        "ai_available": True,
        "transaction_mode": transaction,
        "trace_rule": {
            "parameter_fields": fields,
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
        "permission": permission or ("read" if risk == "R0" else "confirm"),
    }


OPERATIONS_SPEC = {
    "collaboration.workspace.create": {
        "label": "创建隔离试改基线",
        "schema": CreateWorkspaceArgs,
        "prepare": _create_prepare,
        "apply": _create_apply,
        **_meta(
            description="在当前有效授权内创建一个隔离工作区；不新增或扩大任何授权。",
            risk="R2",
            fee="free",
            reversible="workspace_fork_or_discard",
            preconditions=("当前账户拥有作品与创作目标", "资料与可选父版本仍有效"),
            produces=("creative_workspace",),
            target="creative_workspace",
            fields=(
                "case_id",
                "operation_id",
                "label",
                "parent_revision_id",
                "expected_preview_hash",
                "confirmed",
            ),
        ),
    },
    "collaboration.workspace.edit": {
        "label": "保存隔离试改",
        "schema": WorkspaceEditArgs,
        "prepare": _edit_prepare,
        "apply": _edit_apply,
        **_meta(
            description=(
                "按当前工作区修订与现有 grant 校验完整覆盖后，"
                "追加一条隔离修订；不会修改作者资产。"
            ),
            risk="R2",
            fee="free",
            reversible="workspace_revision_fork_or_rebase",
            preconditions=(
                "试改仍开放",
                "当前修订与目标版本未变化",
                "所有覆盖均在 grant 范围内",
            ),
            produces=("creative_workspace_revision",),
            target="creative_workspace",
            fields=(
                "workspace_id",
                "expected_revision_id",
                "patches",
                "expected_preview_hash",
                "confirmed",
            ),
        ),
    },
    "collaboration.workspace.inspect": {
        "label": "查看试改差异与检查状态",
        "schema": WorkspaceInspectArgs,
        "prepare": _inspect_prepare,
        **_meta(
            description="读取隔离试改的当前基线、差异、检查和资料新鲜度，不写入任何内容。",
            risk="R0",
            fee="free",
            reversible="read_only",
            preconditions=("工作区属于当前作品"),
            produces=("creative_workspace_diff",),
            target="creative_workspace",
            fields=("workspace_id", "revision_id"),
        ),
    },
    "collaboration.workspace.seal": {
        "label": "封存已检查的试改版本",
        "schema": WorkspaceSealArgs,
        "prepare": _seal_prepare,
        "apply": _seal_apply,
        **_meta(
            description="冻结当前通过检查且资料未变的隔离试改修订，为逐次确认的原子采用准备。",
            risk="R2",
            fee="free",
            reversible="workspace_fork_or_rebase",
            preconditions=(
                "精确修订已通过检查",
                "作者目标、授权和来源未变化",
                "当前版本已保存",
            ),
            produces=("sealed_workspace_revision",),
            target="creative_workspace_revision",
            fields=(
                "workspace_id",
                "revision_id",
                "expected_digest",
                "expected_preview_hash",
                "confirmed",
            ),
        ),
    },
    "collaboration.workspace.check": {
        "label": "检查一份隔离试改",
        "schema": WorkspaceCheckArgs,
        "prepare": _check_prepare,
        "apply": _check_apply,
        "read_result": _check_read_result,
        **_meta(
            description=(
                "按冻结的授权资料检查精确试改；需单独确认，"
                "使用原 collaboration.run 预算根。"
            ),
            risk="R4",
            fee="possible_model_charge",
            reversible="check_receipt_only",
            preconditions=(
                "当前 grant 有足够累计与单轮额度",
                "目标、工作区与冻结资料均未变化",
                "作者单独确认",
            ),
            produces=("collaboration_run", "workspace_check_receipt"),
            target="creative_workspace_revision",
            fields=(
                "workspace_id",
                "operation_id",
                "expected_goal_version",
                "workspace_revision_id",
                "expected_preview_hash",
                "confirmed",
            ),
            transaction="multi_stage",
        ),
    },
    "collaboration.workspace.atomic_adopt": {
        "label": "原子采用整组试改",
        "schema": AtomicAdoptionArgs,
        "prepare": _atomic_prepare,
        "apply": _atomic_apply,
        "read_result": _atomic_read_result,
        **_meta(
            description="复核封存版本的完整读集、授权、来源和检查回执；每次原子跨域采用都需要作者明确确认。",
            risk="R3",
            fee="free",
            reversible="domain_revision_history_and_merge_receipt",
            preconditions=(
                "精确修订已通过全部检查",
                "完整读集与 grant 未变",
                "作者对本次摘要差异明确确认",
            ),
            produces=("creative_merge_receipt", "domain_outbox"),
            target="creative_workspace_revision",
            fields=(
                "workspace_id",
                "revision_id",
                "expected_digest",
                "operation_id",
                "editor_state",
                "expected_preview_hash",
                "confirmed",
            ),
        ),
    },
}
