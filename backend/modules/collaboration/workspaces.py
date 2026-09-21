"""Frozen baselines with cumulative immutable overlays, diffs and exact seals."""

from __future__ import annotations

import difflib
import json
from uuid import UUID, uuid4

from sqlalchemy import select

from core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.collaboration.cases import require_case
from modules.collaboration.contracts import (
    Grant,
    InputManifest,
    ResourcePatch,
)
from modules.collaboration.models import (
    CollaborationArtifact,
    CollaborationWorkItem,
    CreativeWorkspace,
    CreativeWorkspaceRevision,
)
from modules.evidence.facade import collect_creative_manifest


def revision_digest(manifest, patches, goal_version):
    return content_hash(
        {
            "manifest": manifest,
            "patches": sorted(patches, key=lambda value: (value["kind"], value["id"])),
            "goal_version": goal_version,
        }
    )


def overlay(manifest: InputManifest, patches):
    """Never consult current domain data when reading a frozen workspace."""
    resources = {source.key: source for source in manifest.resources}
    for value in patches:
        patch = ResourcePatch.model_validate(value)
        if patch.key not in resources:
            raise ValidationError("覆盖资源不在冻结基线内", code="RESOURCE_UNSUPPORTED")
        source = resources[patch.key]
        if patch.operation == "delete":
            resources[patch.key] = None
        else:
            if source is None:
                source = next(
                    source for source in manifest.resources if source.key == patch.key
                )
            resources[patch.key] = source.model_copy(
                update={
                    "content": patch.value,
                    "source_hash": content_hash(patch.value),
                    "revision": content_hash(patch.model_dump(mode="json")),
                }
            )
    return [source for source in resources.values() if source is not None]


async def require_workspace(db, novel_id, workspace_id, *, lock=False, execute=False):
    query = select(CreativeWorkspace).where(
        CreativeWorkspace.novel_id == UUID(str(novel_id)),
        CreativeWorkspace.id == UUID(str(workspace_id)),
    )
    if lock:
        existing = await db.scalar(query)
        if existing is None:
            raise NotFoundError("试改版本不可访问")
        await require_case(db, novel_id, existing.case_id, lock=True, execute=execute)
        query = query.with_for_update()
    workspace = await db.scalar(query.execution_options(populate_existing=True))
    if workspace is None:
        raise NotFoundError("试改版本不可访问")
    await require_case(db, novel_id, workspace.case_id, execute=execute)
    return workspace


async def require_revision(db, novel_id, revision_id):
    row = await db.scalar(
        select(CreativeWorkspaceRevision).where(
            CreativeWorkspaceRevision.novel_id == UUID(str(novel_id)),
            CreativeWorkspaceRevision.id == UUID(str(revision_id)),
        )
    )
    if row is None:
        raise NotFoundError("试改修订不可访问")
    workspace = await require_workspace(db, novel_id, row.workspace_id)
    if row.digest != revision_digest(
        row.manifest_json, row.patches_json, row.goal_version
    ):
        raise ConflictError("试改修订校验失败", code="REVISION_CORRUPT")
    return workspace, row


async def create_workspace(
    db, novel_id, case_id, data, *, manifest=None, lineage_revision_id=None
):
    case = await require_case(db, novel_id, case_id, lock=True, execute=True)
    prior = await db.scalar(
        select(CreativeWorkspace).where(
            CreativeWorkspace.novel_id == UUID(novel_id),
            CreativeWorkspace.operation_id == data.operation_id,
        )
    )
    if prior:
        if prior.request_hash and prior.request_hash != content_hash(
            data.model_dump(mode="json")
        ):
            raise ConflictError("请求标识已用于其他试改", code="OPERATION_MISMATCH")
        parent = None
        if data.parent_revision_id:
            parent, _ = await require_revision(db, novel_id, data.parent_revision_id)
        if (
            prior.case_id != case.id
            or prior.label != data.label
            or prior.parent_id != (parent.id if parent else None)
        ):
            raise ConflictError("请求标识已用于其他试改", code="OPERATION_MISMATCH")
        return await workspace_view(db, novel_id, prior.id)
    patches, parent_id, parent_revision_id = [], None, None
    if data.parent_revision_id:
        parent, revision = await require_revision(db, novel_id, data.parent_revision_id)
        if parent.case_id != case.id:
            raise ConflictError("不能混合不同目标的试改版本")
        manifest = InputManifest.model_validate(revision.manifest_json)
        patches, parent_id, parent_revision_id = (
            revision.patches_json,
            parent.id,
            revision.id,
        )
    manifest = manifest or await collect_creative_manifest(
        db, novel_id, Grant.model_validate(case.grant_json), case.goal_version
    )
    frozen = manifest.model_dump(mode="json")
    workspace = CreativeWorkspace(
        id=uuid4(),
        novel_id=case.novel_id,
        case_id=case.id,
        operation_id=data.operation_id,
        request_hash=content_hash(data.model_dump(mode="json")),
        parent_id=parent_id,
        label=data.label,
        baseline_json=frozen,
    )
    db.add(workspace)
    await db.flush()
    revision = CreativeWorkspaceRevision(
        id=uuid4(),
        novel_id=case.novel_id,
        workspace_id=workspace.id,
        parent_revision_id=parent_revision_id or lineage_revision_id,
        sequence=1,
        goal_version=case.goal_version,
        patches_json=patches,
        manifest_json=frozen,
        digest=revision_digest(frozen, patches, case.goal_version),
    )
    db.add(revision)
    await db.flush()
    workspace.current_revision_id = revision.id
    await db.flush()
    return await workspace_view(db, novel_id, workspace.id)


async def edit_workspace(db, novel_id, workspace_id, data):
    workspace = await require_workspace(
        db, novel_id, workspace_id, lock=True, execute=True
    )
    if (
        workspace.status != "open"
        or workspace.current_revision_id != data.expected_revision_id
    ):
        raise ConflictError(
            "试改版本已变化或已封存，请从该版本另建试改", code="WORKSPACE_CHANGED"
        )
    _, parent = await require_revision(db, novel_id, data.expected_revision_id)
    case = await require_case(db, novel_id, workspace.case_id, execute=True)
    grant = Grant.model_validate(case.grant_json)
    if parent.goal_version != case.goal_version:
        raise ConflictError("作者目标已变化，请重建试改", code="GOAL_CHANGED")
    keys = [patch.key for patch in data.patches]
    if len(keys) != len(set(keys)) or set(keys) - {ref.key for ref in grant.resources}:
        raise ValidationError("试改超出授权资源或重复覆盖", code="GRANT_SCOPE_CONFLICT")
    cumulative = {
        f"{value['kind']}:{value['id']}": value for value in parent.patches_json
    }
    cumulative.update(
        {patch.key: patch.model_dump(mode="json") for patch in data.patches}
    )
    values = list(cumulative.values())
    overlay(InputManifest.model_validate(parent.manifest_json), values)
    if len(values) > 16 or len(json.dumps(values, ensure_ascii=False).encode()) > 256000:
        raise ValidationError("本次试改超过小规模原子采用范围，请缩小修改")
    revision = CreativeWorkspaceRevision(
        id=uuid4(),
        novel_id=workspace.novel_id,
        workspace_id=workspace.id,
        parent_revision_id=parent.id,
        sequence=parent.sequence + 1,
        goal_version=case.goal_version,
        patches_json=values,
        manifest_json=parent.manifest_json,
        digest=revision_digest(parent.manifest_json, values, case.goal_version),
    )
    db.add(revision)
    await db.flush()
    workspace.current_revision_id = revision.id
    await db.flush()
    return await workspace_view(db, novel_id, workspace.id)


async def workspace_view(db, novel_id, workspace_id, *, revision_id=None):
    workspace = await require_workspace(db, novel_id, workspace_id)
    _, revision = await require_revision(
        db, novel_id, revision_id or workspace.current_revision_id
    )
    if revision.workspace_id != workspace.id:
        raise NotFoundError("修订不属于此试改")
    baseline = InputManifest.model_validate(revision.manifest_json)
    case = await require_case(db, novel_id, workspace.case_id)
    from modules.evidence.facade import revalidate_creative_manifest

    stale = case.goal_version != revision.goal_version
    try:
        await revalidate_creative_manifest(
            db, novel_id, Grant.model_validate(case.grant_json), baseline
        )
    except DomainError:
        stale = True
    originals = {source.key: source for source in baseline.resources}
    changes = []
    for value in revision.patches_json:
        if stale:
            break
        patch = ResourcePatch.model_validate(value)
        source = originals[patch.key]
        before = json.dumps(source.content, ensure_ascii=False, indent=2, sort_keys=True)
        after = (
            json.dumps(patch.value, ensure_ascii=False, indent=2, sort_keys=True)
            if patch.operation != "delete"
            else ""
        )
        changes.append(
            {
                "resource": {"kind": patch.kind, "id": str(patch.id)},
                "label": source.label,
                "before": source.content,
                "after": patch.value,
                "operation": patch.operation,
                "diff": "\n".join(
                    difflib.unified_diff(
                        before.splitlines(),
                        after.splitlines(),
                        fromfile="原稿",
                        tofile="试改",
                        lineterm="",
                    )
                ),
            }
        )
    check = await db.scalar(
        select(CollaborationArtifact)
        .where(
            CollaborationArtifact.novel_id == UUID(novel_id),
            CollaborationArtifact.workspace_revision_id == revision.id,
            CollaborationArtifact.kind == "workspace_check",
        )
        .order_by(
            CollaborationArtifact.created_at.desc(), CollaborationArtifact.id.desc()
        )
        .limit(1)
    )
    checked = (
        check is not None
        and check.output_hash == content_hash(check.payload_json)
        and check.payload_json.get("digest") == revision.digest
    )
    can_seal = False
    if checked and not stale:
        try:
            await checked_revision(db, novel_id, revision)
            can_seal = True
        except ConflictError:
            pass
    return {
        "id": str(workspace.id),
        "case_id": str(workspace.case_id),
        "label": workspace.label,
        "status": workspace.status,
        "revision_id": str(revision.id),
        "digest": revision.digest,
        "sequence": revision.sequence,
        "goal_version": revision.goal_version,
        "changes": changes,
        "editable_resources": [
            {
                "resource": {"kind": source.kind, "id": str(source.id)},
                "label": source.label,
                "value": source.content,
            }
            for source in overlay(baseline, revision.patches_json)
            if not stale
            and source.key
            in {ref.key for ref in Grant.model_validate(case.grant_json).resources}
        ],
        "stale": stale,
        "check": {
            key: check.payload_json.get(key)
            for key in ("verdict", "findings", "omissions")
        }
        if checked and not stale
        else None,
        "can_seal": can_seal,
    }


async def checked_revision(db, novel_id, revision):
    checks = (
        await db.scalars(
            select(CollaborationArtifact)
            .where(
                CollaborationArtifact.novel_id == UUID(novel_id),
                CollaborationArtifact.workspace_revision_id == revision.id,
                CollaborationArtifact.kind == "workspace_check",
            )
            .order_by(
                CollaborationArtifact.created_at.desc(), CollaborationArtifact.id.desc()
            )
        )
    ).all()
    if not checks:
        raise ConflictError("请先检查这一份精确试改", code="CHECK_REQUIRED")
    check = checks[0]
    if (
        check.output_hash != content_hash(check.payload_json)
        or check.payload_json.get("digest") != revision.digest
        or check.payload_json.get("verdict") != "passed"
        or check.payload_json.get("knowledge_review", {}).get("status") != "passed"
    ):
        raise ConflictError("这一版尚未通过全部检查", code="CHECK_NOT_PASSED")
    dependencies = [
        check.id,
        *(UUID(value) for value in check.payload_json.get("scenario_artifact_ids", [])),
    ]
    for artifact_id in dependencies:
        producer = await db.scalar(
            select(CollaborationWorkItem).where(
                CollaborationWorkItem.novel_id == UUID(novel_id),
                CollaborationWorkItem.output_id == artifact_id,
            )
        )
        if producer and producer.status != "succeeded":
            raise ConflictError(
                "原检查或其情境已被新的调查替代，请重新检查", code="CHECK_SUPERSEDED"
            )
    return check


async def seal_workspace(db, novel_id, workspace_id, data):
    workspace = await require_workspace(
        db, novel_id, workspace_id, lock=True, execute=True
    )
    _, revision = await require_revision(db, novel_id, data.revision_id)
    if workspace.status == "merged":
        return await workspace_view(db, novel_id, workspace.id)
    if (
        revision.workspace_id != workspace.id
        or workspace.current_revision_id != revision.id
        or revision.digest != data.expected_digest
    ):
        raise ConflictError("待封存版本已变化", code="WORKSPACE_CHANGED")
    case = await require_case(db, novel_id, workspace.case_id)
    if revision.goal_version != case.goal_version:
        raise ConflictError("目标已变化", code="GOAL_CHANGED")
    await checked_revision(db, novel_id, revision)
    workspace.status = "sealed"
    await db.flush()
    return await workspace_view(db, novel_id, workspace.id)
