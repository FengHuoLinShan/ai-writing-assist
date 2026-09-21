"""A short same-database UoW for supported, precisely reviewed resources."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select

from core.container import get
from core.errors import ConflictError, ValidationError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.facade import enqueue_operation_task
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.schemas import WorkContext
from modules.collaboration.cases import require_case
from modules.collaboration.contracts import Grant, InputManifest, ResourcePatch
from modules.collaboration.models import CreativeMergeReceipt, DomainOutbox
from modules.collaboration.workspaces import (
    checked_revision,
    require_revision,
    require_workspace,
)
from modules.evidence.facade import revalidate_creative_manifest
from modules.project.facade import require_active_project_exclusive


def operation_context(case, *, run_id, operation_id=None):
    grant = Grant.model_validate(case.grant_json)
    return AssistantOperationContext(
        run_id=str(run_id),
        owner_id=str(case.owner_id),
        operation_id=str(operation_id) if operation_id else None,
        work=WorkContext(
            scope="current" if grant.cutoff_chapter else "project",
            chapter_index=grant.cutoff_chapter,
            excluded_targets=[ref.key for ref in grant.excluded],
            context_confirmation_id=grant.context_confirmation_id,
            context_confirmation_action=grant.context_confirmation_action,
        ),
    )


def whitespace_only(manifest, patches):
    originals = {source.key: source.content for source in manifest.resources}
    for patch in patches:
        before = originals.get(patch.key)
        if (
            patch.kind != "writing_draft"
            or patch.operation != "replace"
            or set(patch.value) != set(before or {})
        ):
            return False
        if any(
            not isinstance(value, str)
            or "".join(value.split()) != "".join(before[key].split())
            for key, value in patch.value.items()
        ):
            return False
    return bool(patches)


def receipt_view(receipt, *, replayed=False):
    return {
        "receipt_id": str(receipt.id),
        "revision_id": str(receipt.revision_id),
        "digest": receipt.digest,
        "results": receipt.results_json,
        "replayed": replayed,
        "domain_write_performed": True,
    }


async def merge_workspace(db, novel_id, workspace_id, data):
    # Acquire this first: all existing domain writes hold the shared project gate.
    # Never upgrade a previously held shared lock while another merge does so.
    await require_active_project_exclusive(db, novel_id)
    workspace = await require_workspace(db, novel_id, workspace_id, lock=True)
    case = await require_case(db, novel_id, workspace.case_id, lock=True)
    request_hash = content_hash(
        {"workspace_id": str(workspace.id), **data.model_dump(mode="json")}
    )
    prior = await db.scalar(
        select(CreativeMergeReceipt).where(
            CreativeMergeReceipt.novel_id == UUID(novel_id),
            CreativeMergeReceipt.operation_id == data.operation_id,
        )
    )
    if prior:
        if prior.request_hash != request_hash:
            raise ConflictError("确认标识已用于不同内容", code="OPERATION_MISMATCH")
        return receipt_view(prior, replayed=True)
    await require_case(db, novel_id, case.id, execute=True)
    _, revision = await require_revision(db, novel_id, data.revision_id)
    if (
        revision.workspace_id != workspace.id
        or workspace.current_revision_id != revision.id
        or revision.digest != data.expected_digest
    ):
        raise ConflictError("确认的试改版本已变化", code="WORKSPACE_CHANGED")
    prior = await db.scalar(
        select(CreativeMergeReceipt).where(
            CreativeMergeReceipt.novel_id == UUID(novel_id),
            CreativeMergeReceipt.revision_id == revision.id,
        )
    )
    if prior:
        return receipt_view(prior, replayed=True)
    if workspace.status != "sealed" or case.goal_version != revision.goal_version:
        raise ConflictError("请重新检查并封存当前目标下的试改", code="CHECK_REQUIRED")
    check = await checked_revision(db, novel_id, revision)
    grant = Grant.model_validate(case.grant_json)
    manifest = InputManifest.model_validate(revision.manifest_json)
    patches = [ResourcePatch.model_validate(value) for value in revision.patches_json]
    if not 1 <= len(patches) <= 16:
        raise ValidationError("一次采用需要一至十六项具体修改")
    if not data.confirmed and not (
        grant.merge_policy == "whitespace_only" and whitespace_only(manifest, patches)
    ):
        raise ConflictError("请确认这一版具体修改", code="CONFIRMATION_REQUIRED")
    if {patch.key for patch in patches} - {ref.key for ref in grant.resources}:
        raise ConflictError("试改超出本次授权", code="GRANT_SCOPE_CONFLICT")
    await revalidate_creative_manifest(db, novel_id, grant, manifest)
    originals = {source.key: source for source in manifest.resources}
    context = operation_context(case, run_id=check.run_id, operation_id=data.operation_id)
    ports = get("collaboration.resources")
    prepared = []
    for patch in sorted(patches, key=lambda item: item.key):
        prepared.append(
            (
                patch,
                await ports[patch.kind].validate(
                    db, novel_id, originals[patch.key], patch, context=context
                ),
            )
        )
    async with db.begin_nested():
        results = []
        for patch, preparation in prepared:
            result = await ports[patch.kind].apply(
                db, novel_id, preparation, context=context
            )
            results.append(
                {
                    "before": originals[patch.key].model_dump(mode="json"),
                    "proposed": patch.model_dump(mode="json"),
                    "result": result,
                }
            )
        receipt = CreativeMergeReceipt(
            id=uuid4(),
            novel_id=case.novel_id,
            revision_id=revision.id,
            operation_id=data.operation_id,
            request_hash=request_hash,
            digest=revision.digest,
            authorizer_id=case.owner_id,
            authorization="explicit" if data.confirmed else "whitespace_only",
            results_json=results,
        )
        db.add(receipt)
        await db.flush()
        db.add(
            DomainOutbox(
                novel_id=case.novel_id, receipt_id=receipt.id, payload_json=results
            )
        )
        await enqueue_operation_task(
            db,
            operation_id=str(receipt.id),
            task_type="collaboration_projection",
            novel_id=novel_id,
            request_payload={"receipt_id": str(receipt.id)},
            meta={"receipt_id": str(receipt.id)},
        )
        workspace.status = "merged"
        await db.flush()
    return receipt_view(receipt)
