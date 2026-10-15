"""Evaluation exports consume persisted evidence without domain writes."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import event

from core.errors import NotFoundError, ValidationError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.world.facade import read_map_spatial_evaluation_artifacts
from modules.world.map_auto_draft_service import build_map_auto_drafts
from modules.world.tests.test_map_auto_draft_service import (
    _build_request,
    _stage_bound_clue,
)


@pytest.mark.asyncio
async def test_artifacts_exact_run_scene_immutable_documents_and_read_only(
    db_session, test_project_id
):
    scene, _a, _b, clue = await _stage_bound_clue(db_session, test_project_id)
    request = _build_request(scene, clue)
    built = await build_map_auto_drafts(db_session, test_project_id, request)
    statements = []

    def capture(_conn, _cursor, statement, *_rest):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await read_map_spatial_evaluation_artifacts(
            db_session, test_project_id, clue.run_id, [str(scene.id)]
        )
        empty = await read_map_spatial_evaluation_artifacts(
            db_session, test_project_id, "other-run", [str(scene.id)]
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result["clues"][0]["id"] == str(clue.id)
    assert result["clues"][0]["source_binding"] == clue.source_binding
    assert result["clues"][0]["clue_payload"]["review"] == clue.clue_payload["review"]
    assert result["batches"][0]["id"] == str(built.batch_id)
    assert result["revisions"][0]["document_hash"]
    assert result["nodes"][0]["head"] is None
    assert not empty["clues"] and not empty["batches"]
    assert empty["coverage"][0]["status"] == "unknown"
    assert not result["truncated"] and result["omitted_count"] == 0
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for sql in statements
    )
    assert not db_session.new and not db_session.dirty
    assert "api_key" not in json.dumps(result)
    with pytest.raises(ValidationError):
        await read_map_spatial_evaluation_artifacts(
            db_session, test_project_id, clue.run_id, []
        )


@pytest.mark.asyncio
async def test_artifacts_owner_gate_precedes_reading_project_evidence(
    db_session, test_project_id
):
    token = bind_principal(
        AccountPrincipal(
            account_id=uuid4(),
            session_id=uuid4(),
            status="active",
            identity_type="registered",
            support_code="test",
        )
    )
    try:
        with pytest.raises(NotFoundError):
            await read_map_spatial_evaluation_artifacts(
                db_session, test_project_id, "run", [str(uuid4())]
            )
    finally:
        reset_principal(token)
