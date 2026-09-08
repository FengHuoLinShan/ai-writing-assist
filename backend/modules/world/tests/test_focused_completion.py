from __future__ import annotations

import asyncio
import copy
import hashlib
import uuid
from dataclasses import asdict, replace

import pytest

from core.errors import ConflictError, ValidationError
from infrastructure.tasks.models import AsyncTask
from modules.world.contracts import (
    FocusedWorldPackageApplyRequest,
    FocusedWorldPackageRequest,
)
from modules.world.facade import (
    apply_focused_world_package,
    authorize_focused_world_completion,
    get_focused_world_neighbors,
    get_focused_world_terms,
    rollback_focused_world_package,
    submit_focused_world_package,
)
from modules.world.models import CoreEntity, CreationSuggestion, EntityRelation
from modules.world.schemas import WorldAdoptionPackagePayload
from modules.world.services.worldbuilding.focused_adoption import is_empty, stable_hash
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionAlreadyProcessedError,
    SuggestionQueueService,
)
from modules.world.services.worldbuilding.world_validation_service import (
    WorldValidationService,
)
from modules.writing.facade import build_manuscript_range_ref
from modules.writing.models import WritingDraft
from tests.utils import _create_entity


async def setup_run(db, novel_id):
    entity = await _create_entity(db, novel_id, "location", "青港")
    text = "青港坐落在北岸。青港又名北港，青港的东边是长桥。"
    draft = WritingDraft(
        novel_id=uuid.UUID(novel_id),
        chapter_index=1,
        content=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        status="published",
    )
    task = AsyncTask(
        novel_id=uuid.UUID(novel_id), task_type="deep_import", meta={"novel_id": novel_id}
    )
    db.add_all([draft, task])
    await db.flush()
    task.mark_running()
    await db.flush()
    source = await build_manuscript_range_ref(
        db,
        novel_id,
        draft_id=str(draft.id),
        start_offset=0,
        end_offset=len(text),
        content_mode="canonical",
    )
    roots = [{"key": "root", "entity_id": str(entity.id)}]
    manifest = {str(draft.id): draft.content_hash}
    auth = await authorize_focused_world_completion(
        db,
        novel_id=novel_id,
        roots=roots,
        source_manifest=manifest,
        chapter_from=1,
        chapter_to=1,
        task_id=str(task.id),
    )
    item = {
        "item_key": "fill",
        "kind": "core_entity",
        "disposition": "include",
        "root_key": "root",
        "depth": 0,
        "authority_kind": "manuscript_observation",
        "source_refs": [
            {
                "source_type": "manuscript",
                "source_id": str(draft.id),
                "source_hash": draft.content_hash,
                "source_range": asdict(source),
                "quote": "青港坐落在北岸。",
            }
        ],
        "payload": {
            "operation": "fill_empty",
            "entity_id": str(entity.id),
            "fields": {"summary": "坐落在北岸。"},
        },
    }
    request = FocusedWorldPackageRequest(
        novel_id=novel_id,
        authorization_id=auth["authorization_id"],
        task_id=str(task.id),
        task_type=task.task_type,
        attempt=task.attempt,
        lease_id=task.lease_id,
        items=[item],
        source_manifest_hash=stable_hash(manifest),
        context_fingerprint="a" * 64,
    )
    return entity, task, draft, request


def apply_request(request, submitted):
    return FocusedWorldPackageApplyRequest(
        novel_id=request.novel_id,
        authorization_id=request.authorization_id,
        task_id=request.task_id,
        task_type=request.task_type,
        attempt=request.attempt,
        lease_id=request.lease_id,
        suggestion_id=submitted["suggestion_id"],
        expected_preview_hash=submitted["expected_preview_hash"],
    )


@pytest.mark.asyncio
async def test_focused_fill_replay_and_safe_undo(db_session, project_novel_id):
    entity, task, draft, request = await setup_run(db_session, project_novel_id)
    submitted = await submit_focused_world_package(db_session, request)
    row = await db_session.get(CreationSuggestion, uuid.UUID(submitted["suggestion_id"]))
    assert submitted["included_count"] == 1, row.payload_json["items"][0][
        "review_reasons"
    ]
    receipt = await apply_focused_world_package(
        db_session, apply_request(request, submitted)
    )
    assert entity.summary == "坐落在北岸。"
    assert receipt["applied_changes"][0]["before"] == {"summary": None}
    again = await submit_focused_world_package(db_session, request)
    assert again["suggestion_id"] == submitted["suggestion_id"]
    assert again["status"] == "accepted"
    entity.public_info = "作者后补的无关字段"
    await db_session.flush()
    result = await rollback_focused_world_package(
        db_session, novel_id=project_novel_id, suggestion_id=submitted["suggestion_id"]
    )
    assert result["results"][0]["status"] == "rolled_back"
    assert entity.summary is None
    assert entity.public_info == "作者后补的无关字段"
    assert (
        await rollback_focused_world_package(
            db_session,
            novel_id=project_novel_id,
            suggestion_id=submitted["suggestion_id"],
        )
    )["results"][0]["status"] == "already_rolled_back"


@pytest.mark.asyncio
async def test_focused_concurrent_edits_and_lease_are_fenced(
    db_session, project_novel_id
):
    entity, task, draft, request = await setup_run(db_session, project_novel_id)
    with pytest.raises(asyncio.CancelledError):
        await submit_focused_world_package(
            db_session, replace(request, lease_id=str(uuid.uuid4()))
        )
    submitted = await submit_focused_world_package(db_session, request)
    entity.summary = "作者手动填写"
    await db_session.flush()
    with pytest.raises(ConflictError):
        await apply_focused_world_package(db_session, apply_request(request, submitted))
    assert entity.summary == "作者手动填写"


@pytest.mark.asyncio
async def test_focused_undo_preserves_changed_field(db_session, project_novel_id):
    entity, task, draft, request = await setup_run(db_session, project_novel_id)
    submitted = await submit_focused_world_package(db_session, request)
    await apply_focused_world_package(db_session, apply_request(request, submitted))
    entity.summary = "作者新版本"
    await db_session.flush()
    result = await rollback_focused_world_package(
        db_session, novel_id=project_novel_id, suggestion_id=submitted["suggestion_id"]
    )
    assert result["results"][0]["status"] == "conflict"
    assert entity.summary == "作者新版本"


@pytest.mark.asyncio
async def test_focused_invalid_quote_and_nonempty_values_stay_pending(
    db_session, project_novel_id
):
    entity, task, draft, request = await setup_run(db_session, project_novel_id)
    request.items[0]["source_refs"][0]["quote"] = "原文没有这句话"
    submitted = await submit_focused_world_package(db_session, request)
    assert submitted["included_count"] == 0 and submitted["review_count"] == 1
    assert entity.summary is None
    row = await db_session.get(CreationSuggestion, uuid.UUID(submitted["suggestion_id"]))
    assert row.payload_json["items"][0]["review_reasons"]
    with pytest.raises(ValidationError):
        await apply_focused_world_package(db_session, apply_request(request, submitted))


@pytest.mark.asyncio
async def test_focused_source_and_legacy_authorization_rejected(
    db_session, project_novel_id
):
    entity, task, draft, request = await setup_run(db_session, project_novel_id)
    with pytest.raises(ValidationError, match="manifest"):
        await submit_focused_world_package(
            db_session, replace(request, source_manifest_hash="b" * 64)
        )
    auth = await db_session.get(CreationSuggestion, uuid.UUID(request.authorization_id))
    auth.payload_json = {**auth.payload_json, "policy": "user_authorized_pipeline"}
    await db_session.flush()
    with pytest.raises(ValidationError, match="authorization"):
        await submit_focused_world_package(db_session, request)


@pytest.mark.asyncio
async def test_focused_policy_and_superseded_manuscript_fail_closed(
    db_session, project_novel_id
):
    entity, task, draft, request = await setup_run(db_session, project_novel_id)
    submitted = await submit_focused_world_package(db_session, request)
    await WorldValidationService().activate_builtin_policy(db_session, project_novel_id)
    with pytest.raises(ConflictError) as error:
        await apply_focused_world_package(db_session, apply_request(request, submitted))
    assert error.value.code == "required_validation"
    assert entity.summary is None
    db_session.add(
        WritingDraft(
            novel_id=uuid.UUID(project_novel_id),
            chapter_index=1,
            version_number=2,
            content="作者的新正文",
            content_hash=hashlib.sha256("作者的新正文".encode()).hexdigest(),
            status="published",
        )
    )
    await db_session.flush()
    with pytest.raises(ConflictError, match="evidence"):
        await apply_focused_world_package(db_session, apply_request(request, submitted))
    assert entity.summary is None


@pytest.mark.asyncio
async def test_focused_authorization_is_not_a_generic_suggestion(
    db_session, project_novel_id
):
    entity, task, draft, request = await setup_run(db_session, project_novel_id)
    record = await db_session.get(CreationSuggestion, uuid.UUID(request.authorization_id))
    service = SuggestionQueueService()
    with pytest.raises(ValidationError, match="Unsupported"):
        service._validated_payload_json(record.target_type, record.payload_json)
    with pytest.raises(SuggestionAlreadyProcessedError):
        await service.reject(db_session, project_novel_id, request.authorization_id)
    assert record.status == "accepted"


@pytest.mark.asyncio
async def test_database_one_hop_proof_is_revalidated(db_session, project_novel_id):
    root, task, draft, request = await setup_run(db_session, project_novel_id)
    neighbor = await _create_entity(db_session, project_novel_id, "location", "长桥")
    text = "长桥铺着青石。"
    second = WritingDraft(
        novel_id=uuid.UUID(project_novel_id),
        chapter_index=2,
        content=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        status="published",
    )
    db_session.add_all(
        [
            second,
            EntityRelation(
                novel_id=uuid.UUID(project_novel_id),
                source_id=root.id,
                target_id=neighbor.id,
                relation_kind="spatial",
                relation_type="相邻",
                status="canonical",
            ),
        ]
    )
    await db_session.flush()
    manifest = {str(draft.id): draft.content_hash, str(second.id): second.content_hash}
    auth = await authorize_focused_world_completion(
        db_session,
        novel_id=project_novel_id,
        roots=[{"key": "root", "entity_id": str(root.id)}],
        source_manifest=manifest,
        chapter_from=1,
        chapter_to=2,
        task_id=str(task.id),
    )
    edge = (
        await get_focused_world_neighbors(
            db_session, novel_id=project_novel_id, entity_ids=[str(root.id)]
        )
    )["relations"][0]
    ref = await build_manuscript_range_ref(
        db_session,
        project_novel_id,
        draft_id=str(second.id),
        start_offset=0,
        end_offset=len(text),
        content_mode="canonical",
    )
    item = copy.deepcopy(request.items[0])
    item.update(
        depth=1,
        direct_relation_ref={
            "relation_id": edge["id"],
            "source_hash": edge["source_hash"],
        },
    )
    item["source_refs"] = [
        {
            "source_type": "manuscript",
            "source_id": str(second.id),
            "source_hash": second.content_hash,
            "source_range": asdict(ref),
            "quote": text,
        }
    ]
    item["payload"] = {
        "operation": "fill_empty",
        "entity_id": str(neighbor.id),
        "fields": {"summary": "铺着青石。"},
    }
    request = replace(
        request,
        authorization_id=auth["authorization_id"],
        items=[item],
        source_manifest_hash=stable_hash(manifest),
    )
    submitted = await submit_focused_world_package(db_session, request)
    assert submitted["included_count"] == 1
    relation = await db_session.get(EntityRelation, uuid.UUID(edge["id"]))
    relation.description = "后续人工修正关系"
    await db_session.flush()
    with pytest.raises(ConflictError):
        await apply_focused_world_package(db_session, apply_request(request, submitted))
    assert neighbor.summary is None


@pytest.mark.asyncio
async def test_authorization_does_not_cross_novels(db_session, two_projects):
    nid, other = two_projects
    entity, task, draft, request = await setup_run(db_session, nid)
    with pytest.raises(ValidationError, match="authorization"):
        await submit_focused_world_package(db_session, replace(request, novel_id=other))


@pytest.mark.asyncio
async def test_focused_creates_alias_relation_and_preserves_open_review(
    db_session, project_novel_id
):
    entity, task, draft, request = await setup_run(db_session, project_novel_id)
    base = copy.deepcopy(request.items[0])
    base["source_refs"][0]["quote"] = draft.content
    bridge = {
        **copy.deepcopy(base),
        "item_key": "bridge",
        "depth": 1,
        "payload": {
            "operation": "create",
            "entity": {"name": "长桥", "entity_type": "location"},
        },
    }
    edge = {
        **copy.deepcopy(base),
        "item_key": "edge",
        "depth": 1,
        "kind": "entity_relation",
        "payload": {
            "operation": "create",
            "source_ref": str(entity.id),
            "target_ref": "local:bridge",
            "relation_kind": "spatial",
            "relation_type": "东边",
            "description": "青港的东边是长桥",
        },
    }
    alias = {
        **copy.deepcopy(base),
        "item_key": "alias",
        "kind": "entity_alias",
        "payload": {
            "entity_ref": str(entity.id),
            "alias": "北港",
            "alias_kind": "name",
            "alias_type": "别称",
        },
    }
    open_item = {**copy.deepcopy(base), "item_key": "unknown", "disposition": "open"}
    request = replace(request, items=[request.items[0], bridge, edge, alias, open_item])
    submitted = await submit_focused_world_package(db_session, request)
    assert submitted["included_count"] == 4
    receipt = await apply_focused_world_package(
        db_session, apply_request(request, submitted)
    )
    assert len(receipt["applied_changes"]) == 4
    review = await db_session.get(
        CreationSuggestion, uuid.UUID(receipt["review_suggestion_id"])
    )
    assert (
        review.status == "pending"
        and review.payload_json["items"][0]["item_key"] == "unknown"
    )
    assert entity.content_json["aliases"][0]["alias"] == "北港"
    result = await rollback_focused_world_package(
        db_session, novel_id=project_novel_id, suggestion_id=submitted["suggestion_id"]
    )
    assert all(item["status"] == "rolled_back" for item in result["results"])
    assert not (entity.content_json or {}).get("aliases")
    bridge_id = receipt["local_ref_map"]["bridge"]
    assert (await db_session.get(CoreEntity, uuid.UUID(bridge_id))).status == "deprecated"


@pytest.mark.asyncio
async def test_focused_identity_reads_all_matches_and_one_hop_pages(
    db_session, two_projects
):
    nid, other = two_projects
    root = await _create_entity(db_session, nid, "location", "青港")
    same = await _create_entity(db_session, nid, "location", "青港", status="candidate")
    neighbor = await _create_entity(db_session, nid, "location", "长桥")
    far = await _create_entity(db_session, nid, "location", "城楼")
    await _create_entity(db_session, other, "location", "青港")
    root.content_json = {
        "aliases": [
            {"alias": "北港", "status": "confirmed"},
            {"alias": "错港", "status": "candidate"},
        ]
    }
    for source, target in [(root, neighbor), (neighbor, far), (root, far)]:
        db_session.add(
            EntityRelation(
                novel_id=uuid.UUID(nid),
                source_id=source.id,
                target_id=target.id,
                relation_kind="spatial",
                relation_type="相邻",
                status="canonical",
            )
        )
    await db_session.flush()
    rows = await get_focused_world_terms(
        db_session, novel_id=nid, names=["青港"], include_review=True, limit=1
    )
    assert rows["truncated"] is True
    rows2 = await get_focused_world_terms(
        db_session,
        novel_id=nid,
        names=["青港"],
        include_review=True,
        limit=1,
        skip=rows["next_skip"],
    )
    assert {rows["entities"][0]["id"], rows2["entities"][0]["id"]} == {
        str(root.id),
        str(same.id),
    }
    assert not (
        await get_focused_world_terms(
            db_session, novel_id=nid, names=["错港"], include_review=True
        )
    )["entities"]
    page = await get_focused_world_neighbors(
        db_session, novel_id=nid, entity_ids=[str(root.id)], limit=1
    )
    assert page["truncated"] is True
    last = await get_focused_world_neighbors(
        db_session,
        novel_id=nid,
        entity_ids=[str(root.id)],
        limit=1,
        skip=page["next_skip"],
    )
    assert last["next_skip"] is None
    assert all(
        str(root.id) in (edge["source_id"], edge["target_id"])
        for edge in page["relations"] + last["relations"]
    )


def test_focused_fill_contract_rejects_arbitrary_fields_and_zero_is_not_empty():
    assert is_empty(None) and is_empty("  ")
    assert not is_empty(0) and not is_empty(False)
    with pytest.raises(ValueError):
        WorldAdoptionPackagePayload.model_validate(
            {
                "schema_version": "world_adoption_package.v2",
                "source_manifest_hash": "a" * 64,
                "items": [
                    {
                        "item_key": "fill",
                        "kind": "core_entity",
                        "authority_kind": "manuscript_observation",
                        "payload": {
                            "operation": "fill_empty",
                            "entity_id": str(uuid.uuid4()),
                            "fields": {"status": "canonical"},
                        },
                    }
                ],
            }
        )
