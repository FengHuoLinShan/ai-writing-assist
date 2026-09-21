"""Real domain writes with isolated trials, exact approval and rollback protection."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from core.config import get_settings
from core.container import container_scope, get
from core.errors import ConflictError
from infrastructure.llm.collaboration import content_hash
from modules.collaboration import cases, workspaces
from modules.collaboration.contracts import (
    CaseCreate,
    Grant,
    InputManifest,
    MergeRequest,
    ResourcePatch,
    WorkspaceCreate,
    WorkspaceEdit,
)
from modules.collaboration.merge import merge_workspace
from modules.collaboration.models import (
    CollaborationArtifact,
    CollaborationRun,
    CreativeMergeReceipt,
)
from modules.evidence.facade import revalidate_creative_manifest
from modules.writing.facade import create_draft_only, get_latest_draft_for_chapter


async def setup_trial(db, nid, monkeypatch, *, two=False, read_scope="selected"):
    settings = replace(
        get_settings(), assistant_enabled=True, collaboration_v2_enabled=True
    )
    monkeypatch.setattr(cases, "get_settings", lambda: settings)
    drafts = [await create_draft_only(db, nid, 1, "开场", "她接受了旧敌的帮助。")]
    if two:
        drafts.append(await create_draft_only(db, nid, 2, "后续", "旧敌收起了信。"))
    refs = [{"kind": "writing_draft", "id": draft.id} for draft in drafts]
    case = await cases.create_case(
        db,
        nid,
        CaseCreate(
            operation_id=uuid4(),
            goal="保留结局，补足有限合作的动机",
            constraints=["不提前揭露身份"],
            grant=Grant(
                resources=refs,
                read_scope=read_scope,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        ),
    )
    view = await workspaces.create_workspace(
        db, nid, case["id"], WorkspaceCreate(operation_id=uuid4(), label="有限合作")
    )
    _, revision = await workspaces.require_revision(db, nid, view["revision_id"])
    patches = [
        ResourcePatch(
            kind="writing_draft",
            id=draft.id,
            value={"title": draft.title, "content": draft.content + "她仍保留了退路。"},
        )
        for draft in drafts
    ]
    view = await workspaces.edit_workspace(
        db,
        nid,
        view["id"],
        WorkspaceEdit(expected_revision_id=view["revision_id"], patches=patches),
    )
    return case, view, drafts, revision


async def approve_trial(db, nid, case, view):
    run = CollaborationRun(
        id=uuid4(),
        novel_id=UUID(nid),
        case_id=UUID(case["id"]),
        operation_id=uuid4(),
        request_hash="a" * 64,
        request_json={},
        manifest_json={},
        llm_snapshot_json={},
        status="completed",
    )
    db.add(run)
    await db.flush()
    payload = {
        "digest": view["digest"],
        "verdict": "passed",
        "knowledge_review": {"status": "passed"},
    }
    db.add(
        CollaborationArtifact(
            novel_id=UUID(nid),
            run_id=run.id,
            workspace_revision_id=UUID(view["revision_id"]),
            kind="workspace_check",
            manifest_json={},
            payload_json=payload,
            output_hash=content_hash(payload),
        )
    )
    await db.flush()
    from modules.collaboration.contracts import RevisionRequest

    await workspaces.seal_workspace(
        db,
        nid,
        view["id"],
        RevisionRequest(revision_id=view["revision_id"], expected_digest=view["digest"]),
    )
    return MergeRequest(
        operation_id=uuid4(),
        revision_id=view["revision_id"],
        expected_digest=view["digest"],
        confirmed=True,
        editor_state="saved",
    )


async def test_trial_does_not_write_and_merge_is_exact_and_idempotent(
    db_session, test_project_id, monkeypatch
):
    db, nid = db_session, test_project_id
    case, view, drafts, _ = await setup_trial(db, nid, monkeypatch)
    assert (await get_latest_draft_for_chapter(db, nid, 1)).content == drafts[0].content
    request = await approve_trial(db, nid, case, view)
    result = await merge_workspace(db, nid, view["id"], request)
    assert result["domain_write_performed"]
    assert (await get_latest_draft_for_chapter(db, nid, 1)).content.endswith(
        "她仍保留了退路。"
    )
    repeated = await merge_workspace(db, nid, view["id"], request)
    assert repeated["receipt_id"] == result["receipt_id"] and repeated["replayed"]
    assert await db.scalar(select(func.count()).select_from(CreativeMergeReceipt)) == 1


async def test_failed_second_write_rolls_back_every_domain_write(
    db_session, test_project_id, monkeypatch
):
    db, nid = db_session, test_project_id
    case, view, drafts, _ = await setup_trial(db, nid, monkeypatch, two=True)
    request = await approve_trial(db, nid, case, view)
    ports = get("collaboration.resources")
    original = ports["writing_draft"]
    calls = 0

    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = await original.apply(*args, **kwargs)
        if calls == 2:
            raise RuntimeError("injected second-write failure")
        return result

    with container_scope(
        {
            "collaboration.resources": {
                **ports,
                "writing_draft": replace(original, apply=fail_second),
            }
        }
    ):
        with pytest.raises(RuntimeError, match="second-write"):
            await merge_workspace(db, nid, view["id"], request)
    assert calls == 2
    for draft in drafts:
        assert (
            await get_latest_draft_for_chapter(db, nid, draft.chapter_index)
        ).id == draft.id
    assert await db.scalar(select(func.count()).select_from(CreativeMergeReceipt)) == 0


async def test_new_source_invalidates_negative_query_and_old_trial(
    db_session, test_project_id, monkeypatch
):
    db, nid = db_session, test_project_id
    case, view, _, baseline = await setup_trial(
        db, nid, monkeypatch, read_scope="project"
    )
    await create_draft_only(db, nid, 2, "新证据", "她早已见过那封信。")
    with pytest.raises(ConflictError, match="查询范围"):
        await revalidate_creative_manifest(
            db,
            nid,
            Grant.model_validate(case["grant"]),
            InputManifest.model_validate(baseline.manifest_json),
        )
    request = await approve_trial(db, nid, case, view)
    with pytest.raises(ConflictError, match="查询范围"):
        await merge_workspace(db, nid, view["id"], request)


async def test_deleted_overlay_stays_deleted_when_forked(
    db_session, test_project_id, monkeypatch
):
    db, nid = db_session, test_project_id
    case, view, drafts, _ = await setup_trial(db, nid, monkeypatch)
    view = await workspaces.edit_workspace(
        db,
        nid,
        view["id"],
        WorkspaceEdit(
            expected_revision_id=view["revision_id"],
            patches=[
                ResourcePatch(kind="writing_draft", id=drafts[0].id, operation="delete")
            ],
        ),
    )
    fork = await workspaces.create_workspace(
        db,
        nid,
        case["id"],
        WorkspaceCreate(
            operation_id=uuid4(),
            label="另一个试验",
            parent_revision_id=view["revision_id"],
        ),
    )
    _, revision = await workspaces.require_revision(db, nid, fork["revision_id"])
    assert (
        workspaces.overlay(
            InputManifest.model_validate(revision.manifest_json), revision.patches_json
        )
        == []
    )
    assert (await get_latest_draft_for_chapter(db, nid, 1)).id == drafts[0].id


def test_dirty_editor_cannot_approve_trial():
    with pytest.raises(ValueError, match="保存"):
        MergeRequest(
            operation_id=uuid4(),
            revision_id=uuid4(),
            expected_digest="a" * 64,
            confirmed=True,
            editor_state="dirty",
        )


async def test_rebase_preserves_author_edits_requires_exact_conflict_resolution(
    db_session, test_project_id, monkeypatch
):
    from modules.collaboration.contracts import RebaseRequest
    from modules.collaboration.recovery import rebase

    db, nid = db_session, test_project_id
    case, trial, drafts, _ = await setup_trial(db, nid, monkeypatch)
    current = await create_draft_only(
        db, nid, 1, drafts[0].title, "她拒绝了帮助，但暂未离开。"
    )
    data = RebaseRequest(operation_id=uuid4(), expected_revision_id=trial["revision_id"])
    conflict = await rebase(db, nid, trial["id"], data)
    assert conflict["status"] == "conflict"
    assert conflict["conflicts"][0]["current"]["content"] == current.content
    assert (await get_latest_draft_for_chapter(db, nid, 1)).content == current.content
    resolution = ResourcePatch(
        kind="writing_draft",
        id=current.id,
        value={"title": current.title, "content": current.content + "她仍保留了退路。"},
    )
    data = data.model_copy(
        update={
            "expected_current_hash": conflict["current_hash"],
            "resolutions": [resolution],
        }
    )
    result = await rebase(db, nid, trial["id"], data)
    assert result["status"] == "ready" and not result["workspace"]["stale"]
    assert result["workspace"]["changes"][0]["after"] == resolution.value
    replay = await rebase(db, nid, trial["id"], data)
    assert replay["replayed"] and replay["workspace"]["id"] == result["workspace"]["id"]
    assert (await get_latest_draft_for_chapter(db, nid, 1)).id == current.id
    _, revision = await workspaces.require_revision(
        db, nid, result["workspace"]["revision_id"]
    )
    assert revision.parent_revision_id is not None
    assert not result["workspace"]["can_seal"]


async def test_revert_creates_checked_compensation_without_erasing_merge(
    db_session, test_project_id, monkeypatch
):
    from modules.collaboration.contracts import RebaseRequest
    from modules.collaboration.recovery import rebase

    db, nid = db_session, test_project_id
    case, trial, drafts, _ = await setup_trial(db, nid, monkeypatch)
    await merge_workspace(db, nid, trial["id"], await approve_trial(db, nid, case, trial))
    adopted = await get_latest_draft_for_chapter(db, nid, 1)
    undo = await rebase(
        db,
        nid,
        trial["id"],
        RebaseRequest(operation_id=uuid4(), expected_revision_id=trial["revision_id"]),
        revert=True,
    )
    assert undo["status"] == "ready"
    assert undo["workspace"]["changes"][0]["after"]["content"] == drafts[0].content
    assert (await get_latest_draft_for_chapter(db, nid, 1)).id == adopted.id
    assert await db.scalar(select(func.count()).select_from(CreativeMergeReceipt)) == 1
    assert not undo["workspace"]["can_seal"]


async def test_grant_renewal_keeps_spend(db_session, test_project_id, monkeypatch):
    from modules.collaboration.contracts import GrantUpdate
    from modules.collaboration.models import CollaborationCase

    db, nid = db_session, test_project_id
    case, _, _, _ = await setup_trial(db, nid, monkeypatch)
    row = await db.get(CollaborationCase, UUID(case["id"]))
    row.requests_used = 12
    updated = await cases.update_grant(
        db,
        nid,
        case["id"],
        GrantUpdate(
            expected_grant_hash=case["grant_hash"],
            grant=Grant.model_validate(
                {**case["grant"], "expires_at": datetime.now(UTC) + timedelta(hours=2)}
            ),
        ),
    )
    assert updated["requests_used"] == 12 and len(row.grant_history_json) == 1
    with pytest.raises(ConflictError, match="授权已经更新"):
        await cases.update_grant(
            db,
            nid,
            case["id"],
            GrantUpdate(
                expected_grant_hash=case["grant_hash"],
                grant=Grant.model_validate(case["grant"]),
            ),
        )


async def test_project_query_adds_exact_read_excerpt_but_never_edit_authority(
    db_session, test_project_id, monkeypatch
):
    from modules.collaboration.contracts import ResourceRef
    from modules.evidence.facade import collect_creative_manifest

    db, nid = db_session, test_project_id
    case, _, _, _ = await setup_trial(db, nid, monkeypatch, read_scope="project")
    other = await create_draft_only(db, nid, 2, "前文", "白纸上写着锁定证据四个字。")
    grant = Grant.model_validate(case["grant"])
    original = await collect_creative_manifest(db, nid, grant, 1)
    assert str(other.id) not in {str(source.id) for source in original.resources}
    found = await collect_creative_manifest(db, nid, grant, 1, query="锁定证据")
    source = next(source for source in found.resources if str(source.id) == str(other.id))
    assert source.read_range and source.range_hash
    assert "锁定证据" in source.content["excerpt"]
    assert source.key not in {ref.key for ref in grant.resources}
    assert found.query_scope_hash == original.query_scope_hash
    excluded = grant.model_copy(
        update={"excluded": [ResourceRef(kind="writing_draft", id=other.id)]}
    )
    denied = await collect_creative_manifest(db, nid, excluded, 1, query="锁定证据")
    assert denied.query_receipt["matching_resources"] == 0
    assert source.key not in {source.key for source in denied.resources}


async def test_unverified_model_connection_cannot_start_a_run(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    from infrastructure.tasks.models import AsyncTask
    from modules.collaboration.contracts import RunCreate
    from modules.collaboration.models import CollaborationCase
    from modules.project.contracts import ProjectLLMConfigurationError

    db, nid = db_session, test_project_id
    case, _, _, _ = await setup_trial(db, nid, monkeypatch)
    row = await db.get(CollaborationCase, UUID(case["id"]))
    row.grant_json = {**row.grant_json, "model_connections": {"check": "unconfigured"}}
    before = await db.scalar(select(func.count()).select_from(AsyncTask))
    with pytest.raises(ProjectLLMConfigurationError):
        await cases.submit_run(
            db, nid, case["id"], RunCreate(operation_id=uuid4(), expected_goal_version=1)
        )
    assert await db.scalar(select(func.count()).select_from(AsyncTask)) == before
    assert row.requests_used == 0


async def test_superseded_check_cannot_seal_an_unchanged_workspace(
    db_session, test_project_id, monkeypatch
):
    from modules.collaboration.models import CollaborationWorkItem

    db, nid = db_session, test_project_id
    case, view, _, _ = await setup_trial(db, nid, monkeypatch)
    await approve_trial(db, nid, case, view)
    check = await db.scalar(
        select(CollaborationArtifact).where(
            CollaborationArtifact.workspace_revision_id == UUID(view["revision_id"])
        )
    )
    item = CollaborationWorkItem(
        novel_id=UUID(nid),
        run_id=check.run_id,
        logical_key="old_check",
        generation=1,
        status="superseded",
        proposal_json={},
        input_hash="a" * 64,
        output_id=check.id,
    )
    db.add(item)
    await db.flush()
    _, revision = await workspaces.require_revision(db, nid, view["revision_id"])
    with pytest.raises(ConflictError, match="替代"):
        await workspaces.checked_revision(db, nid, revision)
    assert not (await workspaces.workspace_view(db, nid, view["id"]))["can_seal"]
