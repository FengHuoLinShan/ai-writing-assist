import uuid

import pytest

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world import review_scope as scope
from modules.world.models import CoreEntity


@pytest.mark.asyncio
async def test_frozen_matching_scope_pages_replays_and_reports_changes(
    db_session, test_project_id
):
    db = db_session
    entities = [
        CoreEntity(
            novel_id=uuid.UUID(test_project_id),
            name=f"巡港人{i:02}",
            entity_type="character",
            status="canonical",
        )
        for i in range(23)
    ]
    db.add_all(entities)
    await db.flush()
    data = scope.ScopeCreate(
        operation_id=uuid.uuid4(), filters={"q": "巡港人", "display_state": "active"}
    )
    frozen = await scope.freeze(db, test_project_id, data)
    assert frozen["total"] == 23 and len(frozen["items"]) == 20 and frozen["has_more"]
    ids = [item["entity_id"] for item in frozen["items"]]
    marked = await scope.decide(
        db,
        test_project_id,
        frozen["id"],
        scope.ScopeDecision(expected_revision=1, entity_ids=ids, disposition="checked"),
    )
    assert marked["count"] == 20 and marked["revision"] == 2
    entities[0].summary = "作者后续修改"
    db.add(
        CoreEntity(
            novel_id=uuid.UUID(test_project_id),
            name="巡港人后来新增",
            entity_type="character",
            status="canonical",
        )
    )
    await db.flush()
    replay = await scope.freeze(db, test_project_id, data)
    assert replay["id"] == frozen["id"] and replay["fingerprint"] == frozen["fingerprint"]
    assert (replay["total"], replay["checked"], replay["stale"], replay["remaining"]) == (
        23,
        19,
        1,
        4,
    )
    last = await scope.read_scope(db, test_project_id, frozen["id"], skip=20)
    assert len(last["items"]) == 3 and not last["has_more"]
    with pytest.raises(ConflictError, match="变化"):
        await scope.decide(
            db,
            test_project_id,
            frozen["id"],
            scope.ScopeDecision(
                expected_revision=1, entity_ids=ids, disposition="checked"
            ),
        )
    with pytest.raises(ConflictError, match="对象已变化"):
        await scope.decide(
            db,
            test_project_id,
            frozen["id"],
            scope.ScopeDecision(
                expected_revision=2, entity_ids=ids, disposition="checked"
            ),
        )
    with pytest.raises(ValidationError, match="范围之外"):
        await scope.decide(
            db,
            test_project_id,
            frozen["id"],
            scope.ScopeDecision(
                expected_revision=2, entity_ids=[uuid.uuid4()], disposition="deferred"
            ),
        )
    assert (await scope.recent(db, test_project_id))[0]["id"] == frozen["id"]
    with pytest.raises(NotFoundError):
        await scope.read_scope(db, str(uuid.uuid4()), frozen["id"])
    with pytest.raises(ConflictError, match="条件已变化"):
        await scope.freeze(
            db,
            test_project_id,
            data.model_copy(update={"filters": scope.ScopeFilters(q="另一组")}),
        )


@pytest.mark.asyncio
async def test_scope_http_bounds_explicit_marks_and_no_silent_truncation(
    async_client, db_session, test_project_id, monkeypatch
):
    db_session.add_all(
        [
            CoreEntity(
                novel_id=uuid.UUID(test_project_id),
                name=f"同名{i}",
                entity_type="character",
                status="canonical",
            )
            for i in range(2)
        ]
    )
    await db_session.flush()
    path = "/api/world/entity-review-scopes"
    params = {"novel_id": test_project_id}
    payload = {"operation_id": str(uuid.uuid4()), "filters": {"display_state": "active"}}
    result = await async_client.post(path, params=params, json=payload)
    assert result.status_code == 201, result.text
    frozen = result.json()
    assert frozen["checked"] == 0 and frozen["total"] == 2
    page = await async_client.get(
        path + "/" + frozen["id"], params={**params, "skip": -1}
    )
    assert page.status_code == 422
    missing_confirmation = await async_client.post(
        path + "/" + frozen["id"] + "/decisions",
        params=params,
        json={"entity_ids": [], "disposition": "checked"},
    )
    assert missing_confirmation.status_code == 422
    monkeypatch.setattr(scope, "MAX_MEMBERS", 1)
    blocked = await async_client.post(
        path, params=params, json={**payload, "operation_id": str(uuid.uuid4())}
    )
    assert blocked.status_code == 400 and "缩小筛选" in blocked.text
