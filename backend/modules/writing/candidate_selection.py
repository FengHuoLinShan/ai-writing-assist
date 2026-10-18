"""Compose selected revision groups, then rerun governance and independent review."""

from __future__ import annotations

import json
import logging
import uuid
from copy import deepcopy

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.stable_hash import stable_hash
from infrastructure.tasks.facade import (
    checkpoint_handler_session,
    enqueue_task_with_optional_operation,
    get_operation_task,
)
from modules.evidence.contracts import (
    GovernedWorkflowHooks,
    KnowledgeDimensionCoverage,
    KnowledgeScopeBuild,
    KnowledgeScopeReceipt,
    KnowledgeSourceEntry,
    KnowledgeSubject,
    knowledge_review_payload,
    require_capability_policy,
    run_governed_generation,
)
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    open_project_snapshot_llm_client,
    require_active_project,
)
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate, WritingWorldReviewScope
from modules.writing.semantic_review import (
    WritingSemanticWorkflowService,
    _requires_confirmed_context,
    validate_candidate_upstream,
)

logger = logging.getLogger(__name__)


def revision_groups(base: str, candidate: str, patches: list[dict]) -> list[dict]:
    """Use exact server patches; historical or ambiguous revisions stay one group."""
    fallback = [
        {
            "id": "whole",
            "changes": [{"before": base, "after": candidate}],
            "whole_only": True,
        }
    ]
    if not patches or any(not isinstance(item, dict) for item in patches):
        return fallback
    groups: dict[str, dict] = {}
    reconstructed, cursor = "", 0
    for patch in patches:
        start, end = patch.get("start"), patch.get("end")
        group_id, replacement = patch.get("group_id"), patch.get("replacement")
        if (
            type(start) is not int
            or type(end) is not int
            or not cursor <= start < end <= len(base)
            or patch.get("source_text") != base[start:end]
            or not isinstance(replacement, str)
            or not isinstance(group_id, str)
            or not group_id
        ):
            return fallback
        reconstructed += base[cursor:start] + replacement
        cursor = end
        group = groups.setdefault(
            group_id, {"id": group_id, "changes": [], "whole_only": False}
        )
        group["changes"].append(
            {"start": start, "end": end, "before": base[start:end], "after": replacement}
        )
    if reconstructed + base[cursor:] != candidate:
        return fallback
    return list(groups.values())


def compose_groups(base: str, groups: list[dict], selected: list[str]) -> str:
    known = {group["id"] for group in groups}
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= known:
        raise ValidationError("请选择有效且不重复的修改组")
    if groups[0].get("whole_only"):
        return groups[0]["changes"][0]["after"]
    changes = sorted(
        (
            change
            for group in groups
            if group["id"] in selected
            for change in group["changes"]
        ),
        key=lambda change: change["start"],
        reverse=True,
    )
    result = base
    for change in changes:
        result = result[: change["start"]] + change["after"] + result[change["end"] :]
    return result


async def _selection(db, novel_id: str, draft_id: str):
    await require_active_project(db, novel_id)
    repo = WritingDraftRepository()
    parent = await repo.get(db, uuid.UUID(draft_id))
    if parent is None or str(parent.novel_id) != novel_id:
        raise NotFoundError("正文建议不存在")
    if parent.status != "candidate":
        raise ConflictError("请打开尚未采用的建议，再选择修改组")
    await validate_candidate_upstream(db, parent, require_review=False)
    working = await repo.get_latest_by_chapter(db, parent.novel_id, parent.chapter_index)
    if working is None or working.status not in {"draft", "published"}:
        raise ConflictError("请先保存本章工作稿")
    provenance = dict(parent.provenance_json or {})
    base_id = provenance.get("base_draft_id")
    base = await repo.get(db, uuid.UUID(str(base_id))) if base_id else working
    if (
        base is None
        or base.novel_id != parent.novel_id
        or base.chapter_index != parent.chapter_index
    ):
        raise ConflictError("原始修改基线不可用，请重新生成建议")
    if (
        provenance.get("base_content_hash")
        and base.content_hash != provenance["base_content_hash"]
    ):
        raise ConflictError("原始修改基线已变化，请重新生成建议")
    groups = revision_groups(
        base.content or "", parent.content or "", provenance.get("applied_patches") or []
    )
    fingerprint = stable_hash(
        {
            "parent": [str(parent.id), parent.content_hash],
            "base": [str(base.id), base.content_hash],
            "working": [str(working.id), working.content_hash],
            "groups": groups,
            "provenance": provenance,
        }
    )
    return parent, base, working, {"preview_hash": fingerprint, "groups": groups}


async def selection_preview(db, novel_id: str, draft_id: str) -> dict:
    _, _, _, preview = await _selection(db, novel_id, draft_id)
    return preview


async def submit_selection(db, draft_id: str, data) -> dict:
    await require_active_project(db, data.novel_id)
    payload = {
        "selection": True,
        "draft_id": draft_id,
        **data.model_dump(mode="json", exclude={"operation_id"}),
    }
    existing = await get_operation_task(
        db,
        operation_id=str(data.operation_id),
        task_type="writing_comment_run",
        novel_id=data.novel_id,
        request_payload=payload,
    )
    if existing:
        return {"task_id": existing.task_id, "status": existing.status}
    _, base, _, preview = await _selection(db, data.novel_id, draft_id)
    if preview["preview_hash"] != data.expected_preview_hash:
        raise ConflictError("正文或修改组已变化，请重新比较")
    compose_groups(base.content or "", preview["groups"], data.group_ids)
    snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)
    task = await enqueue_task_with_optional_operation(
        db,
        operation_id=str(data.operation_id),
        task_type="writing_comment_run",
        novel_id=data.novel_id,
        request_payload=payload,
        meta={**payload, "llm_execution_snapshot": snapshot},
    )
    return {"task_id": task.task_id, "status": task.status}


async def run_selection_task(db, task, snapshot: dict) -> dict:
    meta, task_id = deepcopy(task.meta), str(task.id)
    novel_id, parent_id = str(meta["novel_id"]), str(meta["draft_id"])
    parent, base, working, preview = await _selection(db, novel_id, parent_id)
    if preview["preview_hash"] != meta["expected_preview_hash"]:
        raise ConflictError("修改来源已变化，请重新选择修改组")
    output = compose_groups(base.content or "", preview["groups"], meta["group_ids"])
    if not output.strip() or len(output) > 100000:
        raise ValidationError("组成后的正文为空或超过本章容量")
    chapter, title = parent.chapter_index, parent.title
    provenance = deepcopy(parent.provenance_json or {})
    original_review_scope = deepcopy(
        (provenance.get("independent_review") or {}).get("review_scope")
    )
    origin = (
        provenance.get("context_origin")
        if provenance.get("source")
        in {"writing_comment_revision", "writing_selected_revision", "assistant_revision"}
        else provenance.get("source")
    )
    provenance.update(
        {
            "source": "writing_selected_revision",
            "context_origin": origin or "manual",
            "source_task_id": task_id,
            "selection_source_draft_id": parent_id,
            "selection_source_hash": parent.content_hash,
            "selected_group_ids": list(meta["group_ids"]),
            "selection_preview_hash": preview["preview_hash"],
            "composition_base_draft_id": str(base.id),
            "composition_base_hash": base.content_hash,
            "base_draft_id": str(working.id),
            "base_content_hash": working.content_hash,
            "review_required": True,
            "independent_review": None,
            "knowledge_review": None,
        }
    )
    # Recomposition needs its own review and approval.
    for key in (
        "applied_patches",
        "finding_ids",
        "review_task_id",
        "adoption_idempotency_key",
        "adopted_at",
        "adopted_by",
        "editorial_issue_ids",
    ):
        provenance.pop(key, None)
    policy = require_capability_policy("writing.comment_revision")
    key = f"writing_draft:{base.id}"
    receipt = KnowledgeScopeReceipt(
        policy_version=1,
        capability=policy.capability_id,
        novel_id=novel_id,
        subject=KnowledgeSubject(subject_type="author", cutoff_chapter=chapter),
        included=(
            KnowledgeSourceEntry(
                source_key=key,
                source_type="writing_draft",
                source_id=str(base.id),
                content_hash=base.content_hash,
                label=title or "原始正文",
                dimensions=("prior_prose",),
            ),
        ),
        coverage=(
            KnowledgeDimensionCoverage(dimension="prior_prose", covered_by=(key,)),
        ),
        authority_fingerprint=base.content_hash,
        generator_fingerprint=base.content_hash,
        scope_complete=True,
    )
    base_content = base.content or ""
    selected_changes = [
        group for group in preview["groups"] if group["id"] in meta["group_ids"]
    ]

    async def compose(_plan, _visible):
        return output

    async with open_project_snapshot_llm_client(db, novel_id, snapshot) as client:
        await checkpoint_handler_session(db, error_message="修改组审查前必须释放事务")
        outcome = await run_governed_generation(
            client,
            policy=policy,
            scope_build=KnowledgeScopeBuild(
                receipt=receipt, generator_keys=(key,), audit_only_keys=()
            ),
            hooks=GovernedWorkflowHooks(
                generate=compose,
                task_instruction="仅采用作者选定的完整修改组，范围外逐字保留；重新检查组成后的完整正文。",
                author_requirements=json.dumps(
                    {
                        "groups": selected_changes,
                        "preserve": provenance.get("preserve") or [],
                        "must_not_change": provenance.get("must_not_change") or [],
                    },
                    ensure_ascii=False,
                ),
                generator_context=base_content,
                authority_context=base_content,
            ),
            step_prefix="writing.comment_revision",
        )
    if not outcome.passed:
        return {
            "candidate_draft_id": None,
            "knowledge_review": {"status": "blocked", "audit": outcome.audit.to_dict()},
        }
    if outcome.output != output:
        raise ConflictError("审查结果改变了组成正文，请重新选择")
    await WritingDraftRepository().lock_version_chapters_for_revalidation(
        db, uuid.UUID(novel_id), [chapter]
    )
    _, _, _, current = await _selection(db, novel_id, parent_id)
    if current["preview_hash"] != preview["preview_hash"]:
        raise ConflictError("审查期间正文或来源已变化，旧结果不能采用")
    provenance["knowledge_review"] = knowledge_review_payload(
        audit=outcome.audit, visible_keys=outcome.generator_keys
    )
    candidate = await WritingDraftRepository().create_with_status(
        db,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=chapter,
            title=title,
            content=output,
            provenance_json=provenance,
        ),
        status="candidate",
    )
    candidate_id = str(candidate.id)
    manual_scope = (
        None
        if _requires_confirmed_context(provenance)
        else WritingWorldReviewScope.model_validate(original_review_scope)
        if original_review_scope
        else WritingWorldReviewScope(cutoff_chapter=chapter)
    )
    await checkpoint_handler_session(db, error_message="独立审查前提交修改组候选检查点")
    result = {
        "candidate_draft_id": candidate_id,
        "selected_group_ids": list(meta["group_ids"]),
    }
    try:
        result["post_review"] = await WritingSemanticWorkflowService().review_for_task(
            db,
            task_id=task_id,
            novel_id=novel_id,
            draft_ids=[candidate_id],
            scope="selection",
            llm_execution_snapshot=snapshot,
            manual_world_scope=manual_scope,
        )
    except Exception as exc:
        await db.rollback()
        logger.warning(
            "Selection task %s independent review failed: %s",
            task_id,
            redact_diagnostic(exc, limit=300),
        )
        result.update(
            {
                "degraded": True,
                "post_review_error": "独立审查未完成，候选已保留但暂不可采用",
            }
        )
    return result
