"""World-owned review submission and findings projection (ADR-0022)."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from infrastructure.tasks.facade import update_task_projection
from modules.assistant.contracts import (
    AssistantOperation,
    AssistantOperationContext,
    WorkContext,
)
from modules.evidence.contracts import CompileOptions
from modules.evidence.facade import (
    confirm_context,
    prepare_confirmed_ai_action,
    preview_context_confirmation,
)
from modules.world.models import WorldValidationRun
from modules.world.schemas import WorldValidationRunCreate
from modules.world.services.worldbuilding.world_validation_service import (
    WorldValidationService,
    stable_hash,
)


class ReviewWorld(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root_type: Literal["core_entity", "world_bible_page", "world_bible_page_draft"]
    root_id: uuid.UUID


async def _prepare(db, novel_id, args, *, context=None):
    service = WorldValidationService()
    manifest, dependency, target = await service._freeze_manifest(
        db,
        novel_id=novel_id,
        scope="targeted",
        target_type="semantic_gap",
        target_id=str(args.root_id),
        root_type=args.root_type,
    )
    policy = await service.active_policy(db, novel_id)
    if policy is None and await service._active_policy_candidates(
        db, novel_id, include_disabled=True
    ):
        raise ConflictError("作者已关闭世界复核政策，请先在世界复核设置中调整")
    excluded = {
        value.rsplit(":", 1)[-1]
        for value in (context.work.excluded_targets if context else [])
    }
    fixed = None
    if context and context.work.context_confirmation_id:
        if context.work.context_confirmation_action != "world.validation.semantic":
            raise ConflictError("当前确认属于另一项工作，请在世界复核中确认适用资料")
        fixed = await prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action="world.validation.semantic",
            confirmation_id=str(context.work.context_confirmation_id),
        )
        excluded.update(
            str(value)
            for values in fixed.confirmation.excluded_asset_ids.values()
            for value in values
        )
    if str(args.root_id) in excluded or excluded.intersection(
        str(item.get("target_id")) for item in manifest.get("items", [])
    ):
        raise ConflictError("待复核的依赖含已排除资料，请先调整复核范围")
    items = [
        item
        for item in manifest.get("items", [])
        if str(item.get("target_id") or "") not in excluded
    ]
    entities = [
        str(item["target_id"])
        for item in items
        if item.get("target_type") in {"entity", "core_entity", "world_entity"}
    ]
    refs = [
        {
            "kind": "target",
            "target_ref": {
                "target_type": item["target_type"],
                "target_id": str(item["target_id"]),
                "target_path": "",
            },
        }
        for item in items
        if item.get("target_type") == "world_bible_page"
    ]
    parameters = {
        "task": "复核世界资料与已声明依赖",
        "scope": "world",
        "entity_ids": entities,
        "pinned_refs": refs,
        "selected_world_bible_draft_ids": [
            str(item["target_id"])
            for item in items
            if item.get("target_type") in {"world_bible_draft", "world_bible_page_draft"}
        ],
        "include_pending_objects": any(
            item.get("status") in {"draft", "candidate"} for item in items
        ),
        "reveal_mode": "author_full",
        "budget_tokens": 16000,
        "context_mode": "canonical",
        "content_mode": "canonical",
        "excluded_asset_ids": {"world_entities": sorted(excluded)},
        "user_note": "根据已确认的助手方案/主动服务范围物化；不代表逐项事实已经采用。",
    }
    material = (
        {
            "blockers": fixed.confirmation.blockers,
            "selected_asset_ids": fixed.confirmation.selected_asset_ids,
            "context_fingerprint": fixed.confirmation.context_fingerprint,
            "sources": fixed.confirmation.sections,
        }
        if fixed
        else await preview_context_confirmation(
            db,
            CompileOptions(
                novel_id=novel_id,
                consumer_action="world.validation.semantic",
                **parameters,
            ),
        )
    )
    if material["blockers"] or excluded.intersection(
        str(value)
        for values in material["selected_asset_ids"].values()
        for value in values
    ):
        raise ConflictError(
            "参考资料范围无法安全物化，请调整排除项或范围",
            code="assistant_context_blocked",
        )
    return {
        "target_key": f"world_review:{args.root_id}",
        "title": "复核世界资料与关联影响",
        "source_hash": stable_hash(manifest),
        "dependency_hash": dependency,
        "target_hash": target,
        "policy_hash": policy[1]
        if policy
        else stable_hash(service.assistant_advisory_policy().model_dump(mode="json")),
        "context_parameters": parameters,
        "context_confirmation_id": fixed.confirmation.id if fixed else None,
        "context_fingerprint": material["context_fingerprint"],
        "context_sources": material["sources"],
        "after": "按已有世界政策检查所选资料及已声明的一跳依赖",
        "effect": (
            "保存 World 建议性语义复核，不能作为正式采用许可，不自动修改资料"
            if not policy
            else "按作者已发布的 World 政策复核，不自动修改资料"
            + ("；当前政策未开启语义检查" if not policy[0].semantic_enabled else "")
        ),
    }


async def _submit(db, novel_id, args, internal_meta=None, *, context=None):
    preview = await _prepare(db, novel_id, args, context=context)
    if context and context.operation_id:
        try:
            existing = await WorldValidationService()._get_model(
                db, novel_id, context.operation_id
            )
        except NotFoundError:
            existing = None
        if existing is not None:
            if existing.scope_json.get("target_id") != str(args.root_id):
                raise ConflictError("复核回执不属于这个资料范围")
            return {
                "task_id": str(existing.task_id),
                "run_id": str(existing.id),
                "target": {"type": args.root_type, "id": str(args.root_id)},
                "label": "世界资料复核",
            }
    confirmation_id = preview["context_confirmation_id"]
    if not confirmation_id:
        confirmation = await confirm_context(
            db,
            novel_id=novel_id,
            action="world.validation.semantic",
            **preview["context_parameters"],
            expected_context_fingerprint=preview["context_fingerprint"],
        )
        confirmation_id = confirmation.id
    result = await WorldValidationService().create_run(
        db,
        WorldValidationRunCreate(
            novel_id=novel_id,
            operation_id=uuid.UUID(context.operation_id)
            if context and context.operation_id
            else uuid.uuid4(),
            scope="targeted",
            target_type="semantic_gap",
            target_id=str(args.root_id),
            root_type=args.root_type,
            trigger="assistant",
            context_confirmation_id=confirmation_id,
        ),
        assistant_advisory=True,
        llm_execution_snapshot=context.llm_snapshot if context else None,
    )
    if internal_meta:
        await update_task_projection(
            db,
            task_id=result.task_id,
            task_type="world_validation",
            novel_id=novel_id,
            meta_patch=internal_meta,
        )
    return {
        "task_id": result.task_id,
        "run_id": result.id,
        "target": {"type": args.root_type, "id": str(args.root_id)},
        "label": "世界资料复核",
    }


async def _apply(db, novel_id, args, preview, *, context=None):
    if await _prepare(db, novel_id, args, context=context) != preview:
        raise ConflictError("世界资料已变化", code="assistant_source_stale")
    result = await _submit(
        db, novel_id, args, context.internal_meta if context else None, context=context
    )
    return {
        "type": "world_validation",
        "id": result["run_id"],
        "task_id": result["task_id"],
        "task_type": "world_validation",
        "target": result["target"],
        "label": "已开始复核，可查看覆盖范围与结果",
    }


async def schedule_proactive_review(db, novel_id, change, internal_meta):
    types = {
        "world_entity": "core_entity",
        "core_entity": "core_entity",
        "world_bible_page": "world_bible_page",
        "world_bible_draft": "world_bible_page_draft",
        "world_bible_page_draft": "world_bible_page_draft",
    }
    root_type = types.get(change["asset_type"])
    if not root_type:
        return None
    policy = (internal_meta or {}).get("_assistant_policy") or {}
    context = AssistantOperationContext(
        str(policy.get("run_id") or ""),
        str(policy.get("owner_id") or ""),
        WorkContext(
            scope="project", excluded_targets=policy.get("excluded_targets") or []
        ),
    )
    return await _submit(
        db,
        novel_id,
        ReviewWorld(root_type=root_type, root_id=change["asset_id"]),
        internal_meta,
        context=context,
    )


async def review_findings(db, novel_id, result):
    run_id = result.get("id") or result.get("run_id")
    if not run_id:
        return []
    run = await WorldValidationService()._get_model(db, novel_id, str(run_id))
    sources = {
        item["source_key"]: item for item in (run.manifest_json or {}).get("items", [])
    }
    projected = []
    for finding in run.findings_json or []:
        source = sources.get(finding.get("source_key"), {})
        location = {
            "type": source.get("target_type", "world_validation"),
            "id": source.get("target_id", str(run.id)),
            "review_id": str(run.id),
            "finding_id": finding["finding_id"],
            "source_hash": source.get("content_hash"),
            "section": finding.get("location"),
            "excerpt": finding.get("excerpt"),
        }
        projected.append({**finding, "location": location})
    return projected


async def _review_result(db, novel_id, reference):
    run_id = reference.get("id")
    if not run_id and reference.get("task_id"):
        run_id = await db.scalar(
            select(WorldValidationRun.id).where(
                WorldValidationRun.novel_id == uuid.UUID(novel_id),
                WorldValidationRun.task_id == uuid.UUID(reference["task_id"]),
            )
        )
    if not run_id:
        return {"status": "missing", "omissions": ["原世界复核结果已不可访问"]}
    result = (await WorldValidationService().get(db, novel_id, str(run_id))).model_dump(
        mode="json"
    )
    return {
        key: value
        for key, value in result.items()
        if key
        in {
            "status",
            "verdict",
            "gate",
            "findings",
            "coverage",
            "coverage_ledger",
            "progress",
            "omissions",
            "error_summary",
        }
    }


OPERATIONS = {
    "world.review": AssistantOperation(
        "复核世界资料",
        ReviewWorld,
        _prepare,
        _apply,
        permission="suggest",
        read_result=_review_result,
    )
}
