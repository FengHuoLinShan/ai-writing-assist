"""Confirmed manuscript organization through the existing import workflow."""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from core.errors import ConflictError, ValidationError
from modules.assistant.contracts import AssistantOperation
from modules.imports.facade import start_deep_import, start_deep_import_stage
from modules.imports.models import ImportWorkflowRun
from modules.imports.schemas import TargetedCompletionTarget
from modules.writing.facade import get_manuscript_source_manifest


class OrganizeManuscript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_chapter: int = Field(ge=1)
    end_chapter: int = Field(ge=1)
    stage: Literal["all", "scenes", "world_objects", "plot_structure"] = "scenes"

    @model_validator(mode="after")
    def ordered_range(self):
        if self.end_chapter < self.start_chapter:
            raise ValueError("结束章节不能早于开始章节")
        return self


class ResumeOrganization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID


class CompleteSelectedTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: list[TargetedCompletionTarget] = Field(min_length=1, max_length=100)
    start_chapter: int = Field(ge=1)
    end_chapter: int = Field(ge=1)


async def _completion_preview(db, novel_id, args, *, context=None):
    source = await _prepare(
        db,
        novel_id,
        OrganizeManuscript(
            start_chapter=args.start_chapter, end_chapter=args.end_chapter, stage="all"
        ),
        context=context,
    )
    from modules.evidence.contracts import VisibilityContextContract
    from modules.evidence.facade import inspect_novel_target

    targets = []
    for target in args.targets:
        item = target.model_dump(mode="json", exclude_none=True)
        if target.entity_id:
            inspected = await inspect_novel_target(
                db,
                novel_id=novel_id,
                target_ref={"target_type": "core_entity", "target_id": target.entity_id},
                content_mode="working",
                visibility=VisibilityContextContract(
                    mode="author",
                    cutoff_chapter=context.work.chapter_index
                    if context and context.work.scope == "current"
                    else None,
                ),
            )
            if not inspected.get("visible"):
                raise ConflictError("待补全对象不属于当前作品")
            item["name"] = inspected["item"]["name"]
        targets.append(item)
    return {
        **source,
        "title": "为指定对象专项查漏",
        "targets": targets,
        "after": {
            "范围": f"第 {args.start_chapter}～{args.end_chapter} 章",
            "对象": targets,
        },
        "effect": "对指定对象查漏，依原授权新增或填空；保留冲突和撤销回执",
    }


async def _complete_targets(db, novel_id, args, preview, *, context=None):
    from modules.imports.facade import start_targeted_completion

    if await _completion_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("正文来源或待补全对象已变化，请重新确认")
    result = await start_targeted_completion(
        db,
        novel_id=novel_id,
        targets=[
            target.model_dump(mode="json", exclude_none=True) for target in args.targets
        ],
        start_chapter=args.start_chapter,
        end_chapter=args.end_chapter,
        authorization_confirmed=True,
    )
    return {
        "type": "import_workflow",
        "id": result.get("workflow_id") or result["task_id"],
        "task_id": result["task_id"],
        "label": "已开始指定范围的专项查漏",
    }


async def read_organization_status(db, novel_id, task_id=None):
    from infrastructure.tasks.facade import list_task_lifecycle_contracts
    from modules.project.facade import require_active_project

    await require_active_project(db, novel_id)
    query = select(ImportWorkflowRun).where(ImportWorkflowRun.novel_id == UUID(novel_id))
    if task_id:
        query = query.where(ImportWorkflowRun.task_id == UUID(str(task_id)))
    rows = (
        await db.scalars(query.order_by(ImportWorkflowRun.updated_at.desc()).limit(10))
    ).all()
    life = await list_task_lifecycle_contracts(
        db,
        novel_id=novel_id,
        task_ids=[str(row.task_id) for row in rows],
        max_heartbeat_gap=0,
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "task_id": str(row.task_id),
                "status": row.status,
                "start_chapter": row.start_chapter,
                "end_chapter": row.end_chapter,
                "stage": row.stage,
                "generation": row.generation,
                "recovery_required": row.recovery_required,
                "available_actions": list(life[str(row.task_id)].available_actions)
                if str(row.task_id) in life
                else [],
                "summary": {
                    key: (row.progress or {}).get(key)
                    for key in (
                        "message",
                        "quality_status",
                        "diagnostic_counts",
                        "degraded",
                    )
                },
                "target": {
                    "type": "import_workflow",
                    "id": str(row.id),
                    "task_id": str(row.task_id),
                },
            }
            for row in rows
        ],
        "coverage": "最近十次整理回执，不代表作品内容检查",
    }


async def _resume_preview(db, novel_id, args, *, context=None):
    if context and (
        context.work.excluded_targets or context.work.context_confirmation_id
    ):
        raise ConflictError("整理恢复沿用原授权，请从原整理回执核对范围")
    items = (await read_organization_status(db, novel_id, args.task_id))["items"]
    if not items or "resume" not in items[0]["available_actions"]:
        raise ConflictError("这次整理没有可继续的中断状态，请查看原回执")
    item = items[0]
    return {
        "target_key": f"imports:{args.task_id}",
        "title": "继续原整理流程",
        "generation": item["generation"],
        "status": item["status"],
        "after": f"继续第 {item['start_chapter']}～{item['end_chapter']} 章的原流程",
        "effect": "复用原任务、资料范围、模型快照和已保存进度，不重新开始或扩大授权",
    }


async def _resume(db, novel_id, args, preview, *, context=None):
    from modules.imports.facade import resume_deep_import

    if await _resume_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("整理任务状态已变化，请重新查看")
    result = await resume_deep_import(db, str(args.task_id))
    return {
        "type": "import_workflow",
        "id": result.get("workflow_id") or str(args.task_id),
        "task_id": result["task_id"],
        "label": "已继续原整理任务",
    }


async def _prepare(db, novel_id, args, *, context=None):
    if context and (
        context.work.excluded_targets or context.work.context_confirmation_id
    ):
        raise ConflictError(
            "整理流水线需要独立的章节范围授权，请在整理入口核对；当前查证范围保持不变"
        )
    sources = await get_manuscript_source_manifest(
        db,
        novel_id,
        content_mode="working",
        chapter_from=args.start_chapter,
        chapter_to=args.end_chapter,
    )
    if not sources:
        raise ValidationError("所选范围没有可整理正文")
    return {
        "target_key": f"imports:{args.start_chapter}:{args.end_chapter}",
        "title": "整理已有正文",
        "sources": sources,
        "after": (
            f"第 {args.start_chapter}～{args.end_chapter} 章，"
            f"共 {len(sources)} 个来源版本"
        ),
        "stage": args.stage,
        "effect": (
            "启动独立整理任务并使用模型；按已有授权流水线规则采用可靠结果，"
            "冲突留待处理，可查看进度和回滚。不会强制覆盖已有整理。"
        ),
    }


async def _apply(db, novel_id, args, preview, *, context=None):
    if await _prepare(db, novel_id, args, context=context) != preview:
        raise ConflictError("正文来源已变化", code="assistant_source_stale")
    kwargs = {"high_quality": True, "authorization_confirmed": True}
    if args.stage == "all":
        result = await start_deep_import(
            db, novel_id, args.start_chapter, args.end_chapter, **kwargs
        )
    else:
        result = await start_deep_import_stage(
            db, novel_id, args.start_chapter, args.end_chapter, stage=args.stage, **kwargs
        )
    return {
        "type": "import_workflow",
        "id": str(result.get("task_id") or result.get("workflow_id")),
        "task_id": result.get("task_id"),
        "label": "已开始整理，可离开后继续查看",
        "workflow": result,
    }


class ResolveImportReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_chapter: int = Field(ge=1)
    end_chapter: int = Field(ge=1)
    asset_keys: list[str] = Field(default_factory=list, max_length=10000)
    repair_scenes: bool = True


async def _resolution_preview(db, novel_id, args, *, context=None):
    from modules.imports.review_resolution import freeze_resolution

    source = await _prepare(
        db,
        novel_id,
        OrganizeManuscript(
            start_chapter=args.start_chapter, end_chapter=args.end_chapter, stage="all"
        ),
        context=context,
    )
    scope = await freeze_resolution(
        db,
        novel_id=novel_id,
        start_chapter=args.start_chapter,
        end_chapter=args.end_chapter,
        asset_keys=args.asset_keys,
        repair_scenes=args.repair_scenes,
    )
    return {
        **source,
        "title": "智能整理导入资料",
        "scope_hash": scope["scope_hash"],
        "candidate_fingerprints": {
            item["key"]: item["fingerprint"] for item in scope["items"]
        },
        "after": {
            "范围": f"第{args.start_chapter}～{args.end_chapter}章",
            "待整理资料": len(scope["items"]),
        },
        "effect": (
            "一次授权后查证并整理可靠资料；关键问题成组决定，可选建议保留，可停止和撤销。"
        ),
    }


async def _resolve_review(db, novel_id, args, preview, *, context=None):
    from modules.imports.facade import start_review_resolution
    from modules.imports.review_resolution_schemas import ReviewResolutionRequest

    if await _resolution_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("资料或正文已变化，请重新核对整理范围")
    result = await start_review_resolution(
        db,
        ReviewResolutionRequest(
            novel_id=novel_id, authorization_confirmed=True, **args.model_dump()
        ),
    )
    return {
        "type": "import_workflow",
        "id": result["task_id"],
        "task_id": result["task_id"],
        "label": "已开始智能整理导入资料",
    }


class AcceptReviewGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    candidate_keys: list[str] = Field(min_length=1, max_length=32)
    expected_fingerprints: dict[str, str]


async def _review_decision_preview(db, novel_id, args, *, context=None):
    from modules.imports.facade import inspect_review_resolution

    result = await inspect_review_resolution(
        db, novel_id=novel_id, task_id=str(args.task_id)
    )
    source = await _prepare(
        db,
        novel_id,
        OrganizeManuscript(
            start_chapter=result["chapter_from"],
            end_chapter=result["chapter_to"],
            stage="all",
        ),
        context=context,
    )
    by_key = {item["key"]: item for item in result["summary"].get("groups", [])}
    if set(args.candidate_keys) != set(args.expected_fingerprints) or any(
        key not in by_key
        or by_key[key].get("fingerprint") != args.expected_fingerprints[key]
        for key in args.candidate_keys
    ):
        raise ConflictError("所选决定已变化，请重新查证")
    return {
        **source,
        "title": "采用本组选中资料",
        "after": [
            {
                "资料": by_key[key].get("label"),
                "说明": by_key[key].get("explanation"),
                "概要": (by_key[key].get("proposed_fields") or {}).get("summary"),
                "关系说明": (by_key[key].get("proposed_fields") or {}).get("description"),
                "别名": (by_key[key].get("proposed_fields") or {}).get("alias"),
            }
            for key in args.candidate_keys
        ],
        "effect": "采用所列具体候选，保留来源和撤销记录；世界规则校验仍生效。",
    }


async def _apply_review_decision(db, novel_id, args, preview, *, context=None):
    from modules.imports.review_resolution import accept_decision
    from modules.imports.review_resolution_schemas import ReviewResolutionDecisionRequest

    if await _review_decision_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("候选或来源已变化，请重新确认")
    result = await accept_decision(
        db,
        novel_id=novel_id,
        task_id=str(args.task_id),
        data=ReviewResolutionDecisionRequest(
            candidate_keys=args.candidate_keys,
            expected_fingerprints=args.expected_fingerprints,
            confirmed=True,
        ),
    )
    return {
        "type": "world_adoption_package",
        "id": result["suggestion_id"],
        "label": "所选资料已采用"
        if result["status"] == "accepted"
        else "本组资料仍需校验或审阅",
        "status": result["status"],
    }


OPERATIONS = {
    "imports.accept_review": AssistantOperation(
        "采用明确选中的整理结果",
        AcceptReviewGroup,
        _review_decision_preview,
        _apply_review_decision,
    ),
    "imports.resolve_review": AssistantOperation(
        "查证并整理已有导入候选，只保留关键决定",
        ResolveImportReview,
        _resolution_preview,
        _resolve_review,
    ),
    "imports.complete_targets": AssistantOperation(
        "按原范围对指定对象专项查漏",
        CompleteSelectedTargets,
        _completion_preview,
        _complete_targets,
    ),
    "imports.resume": AssistantOperation(
        "继续原授权的整理流程", ResumeOrganization, _resume_preview, _resume
    ),
    "imports.organize": AssistantOperation(
        "整理已有正文", OrganizeManuscript, _prepare, _apply
    ),
}


def _completion_hash(run):
    return hashlib.sha256(
        json.dumps(
            [run.generation, run.status, run.progress], sort_keys=True, default=str
        ).encode()
    ).hexdigest()


async def schedule_proactive_review(db, novel_id, change, internal_meta):
    from infrastructure.tasks.facade import enqueue_task

    run = await db.scalar(
        select(ImportWorkflowRun).where(
            ImportWorkflowRun.novel_id == UUID(novel_id),
            ImportWorkflowRun.id == UUID(change["asset_id"]),
        )
    )
    if run is None or run.status != "done":
        return None
    task_id = enqueue_task(
        db,
        "imports_completion_review",
        novel_id=novel_id,
        meta={
            **internal_meta,
            "workflow_id": str(run.id),
            "source_hash": _completion_hash(run),
        },
    )
    await db.flush()
    return {
        "task_id": task_id,
        "target": {"type": "import_workflow", "id": str(run.id)},
        "label": "导入完成后的待处理事项",
    }


async def review_completed_import(db, task):
    from modules.imports.workflow_progress import DeepImportProgressTracker
    from modules.imports.workflow_schemas import DeepImportProgress

    run = await db.scalar(
        select(ImportWorkflowRun).where(
            ImportWorkflowRun.novel_id == task.novel_id,
            ImportWorkflowRun.id == UUID(task.meta["workflow_id"]),
        )
    )
    if run is None or _completion_hash(run) != task.meta["source_hash"]:
        raise ConflictError("整理回执已变化，未发布旧提醒")
    progress = DeepImportProgress.model_validate(
        {
            "novel_id": str(run.novel_id),
            "start_chapter": run.start_chapter,
            "end_chapter": run.end_chapter,
            **run.progress,
        }
    )
    DeepImportProgressTracker.refresh_diagnostic_counts(progress)
    counts = progress.diagnostic_counts
    gaps = (
        int(counts.get("phase_error_count") or 0)
        + int(counts.get("alias_relation_failed_scene_count") or 0)
        + int(counts.get("evidence_gate_review_count") or 0)
    )
    findings = []
    if gaps or progress.degraded:
        findings.append(
            {
                "kind": "reminder",
                "code": "import_follow_up",
                "title": "整理完成，还有事项需要你核对",
                "description": (
                    f"第 {run.start_chapter}～{run.end_chapter} 章已完成整理；"
                    "有部分结果待确认或曾降级处理。可在整理回执中继续处理。"
                ),
                "evidence": {
                    "phase_errors": counts.get("phase_error_count", 0),
                    "alias_relation_failures": counts.get(
                        "alias_relation_failed_scene_count", 0
                    ),
                    "evidence_review": counts.get("evidence_gate_review_count", 0),
                    "degraded": progress.degraded,
                },
                "location": {
                    "workflow_id": str(run.id),
                    "source_task_id": str(run.task_id),
                    "chapter_index": run.start_chapter,
                },
            }
        )
    return {
        "findings": findings,
        "not_checked": ["这里只汇总本次整理的覆盖与待处理回执，不是对作品逻辑的语义审稿"],
        "source_hash": task.meta["source_hash"],
    }
