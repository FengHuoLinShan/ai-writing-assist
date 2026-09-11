import copy
from dataclasses import replace

from modules.world.facade import (
    apply_focused_world_package,
    authorize_review_resolution,
    list_review_resolution_candidates,
    rollback_focused_world_package,
    submit_focused_world_package,
)
from modules.world.tests.test_focused_completion import apply_request, setup_run


async def setup_import_run(db, novel_id):
    result = await setup_run(db, novel_id)
    result[0].created_by = "ai_import"
    await db.flush()
    return result


async def test_resolution_promotes_only_frozen_candidate_and_restores_status(
    db_session, project_novel_id
):
    entity, task, draft, request = await setup_import_run(db_session, project_novel_id)
    entity.status = "candidate"
    entity.summary = "坐落在北岸。"
    await db_session.flush()
    rows = await list_review_resolution_candidates(db_session, project_novel_id)
    row = next(row for row in rows if row["entity_id"] == str(entity.id))
    grant = await authorize_review_resolution(
        db_session,
        novel_id=project_novel_id,
        task_id=str(task.id),
        source_manifest={str(draft.id): draft.content_hash},
        chapter_from=1,
        chapter_to=1,
        items=[row],
    )
    item = copy.deepcopy(request.items[0])
    item.update(
        item_key=row["key"],
        root_key=f"entity:{entity.id}",
        payload={"operation": "promote", "entity_id": str(entity.id)},
        baseline={"expected_status": "candidate"},
        review_evidence={
            key: [item["source_refs"][0]["quote"]] for key in row["required_fields"]
        },
    )
    updated = replace(
        request, authorization_id=grant["authorization_id"], roots=[], items=[item]
    )
    submitted = await submit_focused_world_package(db_session, updated)
    assert submitted["included_count"] == 1
    receipt = await apply_focused_world_package(
        db_session, apply_request(updated, submitted)
    )
    assert entity.status == "canonical"
    assert receipt["applied_changes"][0]["before"]["status"] == "candidate"
    await rollback_focused_world_package(
        db_session, novel_id=project_novel_id, suggestion_id=submitted["suggestion_id"]
    )
    assert entity.status == "candidate"


async def test_old_completion_authorization_cannot_promote_candidate(
    db_session, project_novel_id
):
    entity, task, draft, request = await setup_import_run(db_session, project_novel_id)
    entity.status = "candidate"
    await db_session.flush()
    item = copy.deepcopy(request.items[0])
    item.update(
        payload={"operation": "promote", "entity_id": str(entity.id)},
        baseline={"expected_status": "candidate"},
    )
    result = await submit_focused_world_package(
        db_session, replace(request, items=[item])
    )
    assert result["included_count"] == 0
    assert entity.status == "candidate"


async def test_resolution_source_and_candidate_drift_fail_closed(
    db_session, project_novel_id
):
    entity, task, draft, request = await setup_import_run(db_session, project_novel_id)
    entity.content_json = {
        "aliases": [
            {"alias": "北港", "type": "name", "kind": "name", "status": "candidate"}
        ]
    }
    await db_session.flush()
    row = (await list_review_resolution_candidates(db_session, project_novel_id))[0]
    grant = await authorize_review_resolution(
        db_session,
        novel_id=project_novel_id,
        task_id=str(task.id),
        source_manifest={str(draft.id): draft.content_hash},
        chapter_from=1,
        chapter_to=1,
        items=[row],
    )
    item = copy.deepcopy(request.items[0])
    item.update(
        item_key=row["key"],
        kind="entity_alias",
        root_key=f"entity:{entity.id}",
        payload={
            "entity_ref": str(entity.id),
            "alias": "北港",
            "alias_type": "name",
            "alias_kind": "name",
        },
        review_evidence={
            key: [item["source_refs"][0]["quote"]] for key in row["required_fields"]
        },
    )
    updated = replace(
        request, authorization_id=grant["authorization_id"], roots=[], items=[item]
    )
    entity.name = "作者修改的名字"
    await db_session.flush()
    submitted = await submit_focused_world_package(db_session, updated)
    assert submitted["included_count"] == 0
    assert entity.content_json["aliases"][0]["status"] == "candidate"


async def test_explicit_group_alias_adoption_is_undoable(db_session, project_novel_id):
    from modules.world.services.core.review_resolution import (
        apply_manual_decision,
        prepare_manual_decision,
    )

    entity, task, draft, request = await setup_import_run(db_session, project_novel_id)
    original = {
        "alias": "北港",
        "type": "name",
        "kind": "name",
        "status": "candidate",
        "source": "deep_import",
        "needs_review": True,
    }
    entity.content_json = {"aliases": [original]}
    await db_session.flush()
    rows = await list_review_resolution_candidates(db_session, project_novel_id)
    package = await prepare_manual_decision(
        db_session, novel_id=project_novel_id, task_id=str(task.id), rows=rows
    )
    receipt = await apply_manual_decision(
        db_session, novel_id=project_novel_id, package=package
    )
    assert entity.content_json["aliases"][0]["status"] == "confirmed"
    assert entity.content_json["aliases"][0]["source"] == "deep_import"
    assert receipt["applied_changes"]
    await rollback_focused_world_package(
        db_session, novel_id=project_novel_id, suggestion_id=package["suggestion_id"]
    )
    assert entity.content_json["aliases"] == [original]


def test_legacy_package_hash_payload_does_not_gain_resolution_defaults():
    from modules.world.schemas import WorldAdoptionPackagePayload

    package = WorldAdoptionPackagePayload(
        schema_version="world_adoption_package.v1",
        source_manifest_hash="a" * 64,
        items=[
            {
                "item_key": "old",
                "kind": "core_entity",
                "disposition": "open",
                "authority_kind": "author_seed",
                "payload": {
                    "operation": "create",
                    "entity": {"name": "港口", "entity_type": "location"},
                },
            }
        ],
    )
    dumped = package.model_dump(mode="json")
    assert "review_resolution_run" not in dumped
    assert "review_evidence" not in dumped["items"][0]


async def test_manual_or_other_ai_candidates_are_not_silently_import_adoptable(
    db_session, project_novel_id
):
    entity, _, _, _ = await setup_run(db_session, project_novel_id)
    entity.status = "candidate"
    entity.created_by = "manual"
    entity.content_json = {"_meta": {"source": "world_generation_center"}}
    await db_session.flush()
    assert await list_review_resolution_candidates(db_session, project_novel_id) == []
