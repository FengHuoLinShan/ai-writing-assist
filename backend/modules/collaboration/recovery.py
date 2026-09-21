"""Three-way rebase and compensating revisions; never overwrite adopted history."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.collaboration.cases import require_case
from modules.collaboration.contracts import (
    Grant,
    InputManifest,
    ResourcePatch,
    ResourceRef,
    WorkspaceCreate,
    WorkspaceEdit,
)
from modules.collaboration.models import CreativeMergeReceipt, CreativeWorkspace
from modules.collaboration.workspaces import (
    create_workspace,
    edit_workspace,
    require_revision,
    require_workspace,
    workspace_view,
)
from modules.evidence.facade import collect_creative_manifest


def merge_fields(before, current, proposed):
    """Different fields merge automatically. Overlapping edits need author choices."""
    if current == before or current == proposed:
        return proposed, []
    if proposed == before:
        return current, []
    if proposed is None or set(before) != set(current) or set(before) != set(proposed):
        return None, ["content"]
    merged, conflicts = {}, []
    for key in before:
        if current[key] == before[key] or current[key] == proposed[key]:
            merged[key] = proposed[key]
        elif proposed[key] == before[key]:
            merged[key] = current[key]
        else:
            conflicts.append(key)
    return merged, conflicts


async def rebase(db, novel_id, workspace_id, data, *, revert=False):
    workspace = await require_workspace(
        db, novel_id, workspace_id, lock=True, execute=True
    )
    case = await require_case(db, novel_id, workspace.case_id, lock=True, execute=True)
    request_hash = content_hash(
        {"workspace": str(workspace.id), "revert": revert, **data.model_dump(mode="json")}
    )
    prior = await db.scalar(
        select(CreativeWorkspace).where(
            CreativeWorkspace.novel_id == UUID(novel_id),
            CreativeWorkspace.operation_id == data.operation_id,
        )
    )
    if prior:
        if prior.request_hash != request_hash:
            raise ConflictError("请求标识已用于其他修订", code="OPERATION_MISMATCH")
        return {
            "status": "ready",
            "workspace": await workspace_view(db, novel_id, prior.id),
            "replayed": True,
        }
    _, revision = await require_revision(db, novel_id, data.expected_revision_id)
    if (
        revision.workspace_id != workspace.id
        or workspace.current_revision_id != revision.id
    ):
        raise ConflictError("试改已变化，请重新读取", code="WORKSPACE_CHANGED")
    baseline = InputManifest.model_validate(revision.manifest_json)
    original_grant = Grant.model_validate(case.grant_json)
    old_sources = {source.key: source for source in baseline.resources}
    ports = get("collaboration.resources")
    inventory = {
        kind: await ports[kind].inventory(db, novel_id)
        for kind in original_grant.read_kinds
    }
    mapped = {}
    for ref in original_grant.resources:
        old = old_sources.get(ref.key)
        matches = [
            value
            for value in inventory[ref.kind]
            if value.id == ref.id
            or (
                old
                and ref.kind == "writing_draft"
                and value.chapter_index == old.chapter_index
            )
        ]
        if len(matches) != 1:
            raise ConflictError(
                "原资源已删除或无法唯一重定位，请重新选择授权资料",
                code="RESOURCE_UNAVAILABLE",
            )
        mapped[ref.key] = matches[0]
    grant = original_grant.model_copy(
        update={
            "resources": [
                ResourceRef(kind=value.kind, id=value.id) for value in mapped.values()
            ]
        }
    )
    for old in baseline.resources:
        if old.key in mapped:
            continue
        for value in list(mapped.values()):
            if (
                old.kind == value.kind == "writing_draft"
                and old.chapter_index == value.chapter_index
            ):
                mapped[old.key] = value
                break
    current = await collect_creative_manifest(db, novel_id, grant, case.goal_version)
    if data.expected_current_hash and data.expected_current_hash != current.fingerprint:
        raise ConflictError("当前稿再次变化，请重新核对冲突", code="SOURCE_STALE")
    if data.resolutions and not data.expected_current_hash:
        raise ValidationError("手动解决冲突需要绑定当前资料版本")
    patches = [ResourcePatch.model_validate(value) for value in revision.patches_json]
    if revert:
        receipt = await db.scalar(
            select(CreativeMergeReceipt).where(
                CreativeMergeReceipt.novel_id == UUID(novel_id),
                CreativeMergeReceipt.revision_id == revision.id,
            )
        )
        if receipt is None:
            raise NotFoundError("这一版尚未采用，没有可撤回的回执")
    choices = {patch.key: patch for patch in data.resolutions}
    if len(choices) != len(data.resolutions) or choices.keys() - {
        mapped[patch.key].key for patch in patches
    }:
        raise ValidationError("冲突解决超出了本次修改范围")
    rebased, conflicts = [], []
    for patch in patches:
        if patch.key not in mapped:
            raise ConflictError("此修改已不在当前授权中", code="GRANT_SCOPE_CONFLICT")
        source = mapped[patch.key]
        before, proposed = old_sources[patch.key].content, patch.value
        if revert:
            if proposed is None:
                raise ValidationError("删除覆盖没有可直接撤回的采用")
            before, proposed = proposed, before
        merged, fields = merge_fields(before, source.content, proposed)
        if source.key in choices:
            merged, fields = choices[source.key].value, []
        if fields:
            conflicts.append(
                {
                    "resource": {"kind": source.kind, "id": str(source.id)},
                    "label": source.label,
                    "fields": fields,
                    "base": before,
                    "current": source.content,
                    "trial": proposed,
                }
            )
        elif merged != source.content:
            rebased.append(
                ResourcePatch(
                    kind=source.kind,
                    id=source.id,
                    operation="delete" if merged is None else "replace",
                    value=merged,
                )
            )
    if conflicts:
        return {
            "status": "conflict",
            "current_hash": current.fingerprint,
            "conflicts": conflicts,
        }
    if grant != original_grant:
        case.grant_history_json = [
            *(case.grant_history_json or []),
            {
                "grant": case.grant_json,
                "ended_at": datetime.now(UTC).isoformat(),
                "reason": "author_rebase_same_logical_resources",
                "requests_used": case.requests_used,
            },
        ]
        case.grant_json = grant.model_dump(mode="json")
    created = await create_workspace(
        db,
        novel_id,
        case.id,
        WorkspaceCreate(
            operation_id=data.operation_id,
            label=("撤回试改：" if revert else "重建试改：") + workspace.label[:180],
        ),
        manifest=current,
        lineage_revision_id=revision.id,
    )
    child = await require_workspace(db, novel_id, created["id"])
    child.parent_id, child.request_hash = workspace.id, request_hash
    if rebased:
        created = await edit_workspace(
            db,
            novel_id,
            child.id,
            WorkspaceEdit(
                expected_revision_id=created["revision_id"],
                patches=rebased,
            ),
        )
    await db.flush()
    return {"status": "ready", "workspace": created, "replayed": False}
