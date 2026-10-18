from __future__ import annotations

import uuid

import pytest

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.stable_hash import stable_hash
from modules.story.outline_state.models import Scene
from modules.world.models import CoreEntity, EntityRelation
from modules.world.relation_changes import (
    RelationChange,
    apply_change,
    change_history,
    preview_change,
)
from modules.world.schemas import EntityRelationCreate, EntityRelationUpdate
from modules.world.services.core.entity_relation_service import EntityRelationService


async def relation(db, novel_id):
    nid = uuid.UUID(novel_id)
    first = CoreEntity(
        novel_id=nid, name="沈砚", entity_type="character", status="canonical"
    )
    second = CoreEntity(
        novel_id=nid, name="船医", entity_type="character", status="canonical"
    )
    db.add_all([first, second])
    await db.flush()
    return await EntityRelationService().create(
        db,
        novel_id,
        EntityRelationCreate(
            source_id=str(first.id),
            target_id=str(second.id),
            relation_type="ally_of",
            relation_kind="social",
            description="原约定",
        ),
    )


async def execute(db, novel_id, args, operation_id=None):
    preview = await preview_change(db, novel_id, args)
    key = operation_id or str(uuid.uuid4())
    receipt = await apply_change(
        db,
        novel_id,
        args,
        operation_id=key,
        expected_preview_hash=stable_hash(preview),
        actor="author",
    )
    return receipt, preview, key


@pytest.mark.asyncio
async def test_relation_end_remove_restore_have_distinct_receipts_and_replay(
    db_session, test_project_id
):
    row = await relation(db_session, test_project_id)
    scene = Scene(
        novel_id=uuid.UUID(test_project_id),
        scene_index=1,
        title="约定结束",
        status="draft",
    )
    db_session.add(scene)
    await db_session.flush()
    end_args = RelationChange(
        relation_id=row.id, action="end", end={"kind": "scene", "id": scene.id}
    )
    end_receipt, _, _ = await execute(db_session, test_project_id, end_args)
    current = await EntityRelationService().get(
        db_session, str(row.id), novel_id=test_project_id
    )
    assert current.status == "canonical"
    assert str(current.validity.end.id) == str(scene.id)
    remove_args = RelationChange(relation_id=row.id, action="remove")
    removed, preview, key = await execute(db_session, test_project_id, remove_args)
    assert removed["history_id"] != end_receipt["history_id"]
    assert (
        await EntityRelationService().get(
            db_session, str(row.id), novel_id=test_project_id
        )
    ).status == "deprecated"
    assert (
        await apply_change(
            db_session,
            test_project_id,
            remove_args,
            operation_id=key,
            expected_preview_hash=stable_hash(preview),
            actor="author",
        )
        == removed
    )
    restored, _, _ = await execute(
        db_session,
        test_project_id,
        RelationChange(
            relation_id=row.id, action="restore", history_id=removed["history_id"]
        ),
    )
    current = await EntityRelationService().get(
        db_session, str(row.id), novel_id=test_project_id
    )
    assert current.status == "canonical"
    assert str(current.validity.end.id) == str(scene.id)
    assert current.source_id == row.source_id and current.target_id == row.target_id
    history = (await change_history(db_session, test_project_id, row.id))["items"]
    assert [item["action"] for item in history] == ["restore", "remove", "end"]
    assert history[0]["receipt"] == restored


@pytest.mark.asyncio
async def test_stale_relation_preview_preserves_concurrent_manual_edit(
    db_session, test_project_id
):
    row = await relation(db_session, test_project_id)
    args = RelationChange(
        relation_id=row.id, action="edit", changes={"description": "拟改", "strength": 0}
    )
    preview = await preview_change(db_session, test_project_id, args)
    await EntityRelationService().update(
        db_session,
        str(row.id),
        EntityRelationUpdate(description="作者另存"),
        novel_id=test_project_id,
    )
    with pytest.raises(ConflictError, match="重新预览"):
        await apply_change(
            db_session,
            test_project_id,
            args,
            operation_id=str(uuid.uuid4()),
            expected_preview_hash=stable_hash(preview),
            actor="author",
        )
    assert (
        await EntityRelationService().get(
            db_session, str(row.id), novel_id=test_project_id
        )
    ).description == "作者另存"
    receipt, _, _ = await execute(db_session, test_project_id, args)
    await execute(
        db_session,
        test_project_id,
        RelationChange(
            relation_id=row.id, action="restore", history_id=receipt["history_id"]
        ),
    )
    assert (
        await EntityRelationService().get(
            db_session, str(row.id), novel_id=test_project_id
        )
    ).description == "作者另存"


@pytest.mark.asyncio
async def test_relation_null_description_clear_and_restore_match_real_receipts(
    db_session, test_project_id
):
    row = await relation(db_session, test_project_id)
    cleared, clear_preview, _ = await execute(
        db_session,
        test_project_id,
        RelationChange(relation_id=row.id, action="edit", changes={"description": None}),
    )
    current = await EntityRelationService().get(
        db_session, str(row.id), novel_id=test_project_id
    )
    assert cleared["changed"] and clear_preview["after"]["description"] is None
    assert current.description is None
    edited, _, _ = await execute(
        db_session,
        test_project_id,
        RelationChange(
            relation_id=row.id, action="edit", changes={"description": "后加说明"}
        ),
    )
    restored, _, _ = await execute(
        db_session,
        test_project_id,
        RelationChange(
            relation_id=row.id, action="restore", history_id=edited["history_id"]
        ),
    )
    current = await EntityRelationService().get(
        db_session, str(row.id), novel_id=test_project_id
    )
    history = await change_history(db_session, test_project_id, row.id)
    assert restored["status"] == "completed" and current.description is None
    assert history["items"][0]["after"]["description"] == current.description


@pytest.mark.asyncio
async def test_relation_history_and_validity_reject_other_projects(
    db_session, two_projects
):
    novel_id, other = two_projects
    row = await relation(db_session, novel_id)
    with pytest.raises(NotFoundError):
        await change_history(db_session, other, row.id)
    foreign = Scene(novel_id=uuid.UUID(other), scene_index=1, status="draft")
    db_session.add(foreign)
    await db_session.flush()
    with pytest.raises((ValidationError, NotFoundError)):
        await preview_change(
            db_session,
            novel_id,
            RelationChange(
                relation_id=row.id, action="end", end={"kind": "scene", "id": foreign.id}
            ),
        )
    assert (await change_history(db_session, novel_id, row.id))["items"] == []


@pytest.mark.asyncio
async def test_relation_http_confirm_roundtrip_preserves_only_supplied_fields(
    async_client, db_session, test_project_id
):
    row = await relation(db_session, test_project_id)
    path = f"/api/world/relations/{row.id}"
    params = {"novel_id": test_project_id}
    args = {
        "relation_id": str(row.id),
        "action": "edit",
        "changes": {"description": "新约定", "strength": 0},
    }
    normalized = RelationChange.model_validate(args).model_dump(mode="json")
    assert normalized["changes"] == args["changes"]
    assert RelationChange.model_validate(normalized).model_dump(mode="json") == normalized
    prepared = await async_client.post(path + "/change-preview", params=params, json=args)
    assert prepared.status_code == 200, prepared.text
    payload = {
        **args,
        "operation_id": str(uuid.uuid4()),
        "expected_preview_hash": prepared.json()["preview_hash"],
        "confirmed": True,
    }
    result = await async_client.post(path + "/changes", params=params, json=payload)
    assert result.status_code == 200, result.text
    assert (
        await async_client.post(path + "/changes", params=params, json=payload)
    ).json() == result.json()
    history = (await async_client.get(path + "/change-history", params=params)).json()
    assert len(history["items"]) == 1
    assert history["current"]["description"] == "新约定"
    assert history["current"]["strength"] == 0
    assert history["current"]["relation_type"] == "ally_of"
    missing_confirmation = await async_client.post(
        path + "/changes", params=params, json={**payload, "confirmed": False}
    )
    assert missing_confirmation.status_code == 422
    wrong_path = f"/api/world/relations/{uuid.uuid4()}/change-preview"
    assert (
        await async_client.post(wrong_path, params=params, json=args)
    ).status_code == 400


async def test_relation_responses_omit_history_but_keep_paginated_restore(
    async_client, db_session, test_project_id
):
    from modules.account.facade import current_account_id
    from modules.assistant.contracts import AssistantOperationContext
    from modules.assistant.schemas import WorkContext
    from modules.world.assistant_validity_tools import ReadRelations, _read

    row = await relation(db_session, test_project_id)
    stored = await db_session.get(EntityRelation, uuid.UUID(row.id))
    stored.review_meta = {"needs_review": True, "source": "manual"}
    await db_session.flush()
    context = AssistantOperationContext(
        str(uuid.uuid4()), str(current_account_id()), WorkContext()
    )
    sizes = []
    first_receipt = None
    for index in range(6):
        receipt, _, _ = await execute(
            db_session,
            test_project_id,
            RelationChange(
                relation_id=row.id, action="edit", changes={"description": f"修改{index}"}
            ),
        )
        first_receipt = first_receipt or receipt
        response = await async_client.get(
            "/api/world/relations", params={"novel_id": test_project_id}
        )
        assert response.status_code == 200, response.text
        public = response.json()["items"][0]
        assistant = (
            await _read(db_session, test_project_id, ReadRelations(), context=context)
        )["items"][0]
        for item in (public, assistant):
            assert "author_change_history" not in item["review_meta"]
            assert item["review_meta"]["needs_review"] is True
            assert item["review_meta"]["source"] == "manual"
        sizes.append(len(response.content))
    assert max(sizes) - min(sizes) < 20
    first_page = await change_history(db_session, test_project_id, row.id, limit=2)
    rest = await change_history(db_session, test_project_id, row.id, skip=2)
    assert first_page["total"] == 6 and first_page["has_more"]
    assert len(first_page["items"] + rest["items"]) == 6
    assert rest["items"][-1]["id"] == first_receipt["history_id"]
    await execute(
        db_session,
        test_project_id,
        RelationChange(
            relation_id=row.id, action="restore", history_id=first_receipt["history_id"]
        ),
    )
    current = await EntityRelationService().get(
        db_session, str(row.id), novel_id=test_project_id
    )
    assert current.description == "原约定"
    assert (await change_history(db_session, test_project_id, row.id))["total"] == 7
