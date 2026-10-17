import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from core.errors import ConflictError, NotFoundError
from modules.evolution.facade import read_map_spatial_evaluation_receipts
from modules.evolution.models import (
    EvolutionFrozenAttempt,
    EvolutionReceiptRecord,
    EvolutionRun,
)


@pytest.mark.asyncio
async def test_receipts_read_exact_authorized_scenes_without_reconcile_or_secrets(
    db_session, test_project_id
):
    scene, other, operation = str(uuid4()), str(uuid4()), str(uuid4())
    nid = UUID(test_project_id)
    run = EvolutionRun(
        novel_id=nid,
        run_key="evaluation",
        mode="bootstrap",
        status="drained",
        committed_scene_index=0,
        llm_snapshot_json={"api_key": "never-export"},
        reading_plan_json={
            "owner_token": "never-export",
            "segments": [
                {
                    "operation_id": operation,
                    "first_scene_index": 0,
                    "last_scene_index": 0,
                    "request": {
                        "discover_spatial": True,
                        "expected_fingerprint": "f" * 64,
                        "api_key": "never-export",
                    },
                }
            ],
            "steps": [
                {
                    "scene_id": scene,
                    "scene_index": 0,
                    "source_binding": {"content_hash": "a" * 64},
                }
            ],
        },
    )
    attempt = EvolutionFrozenAttempt(
        novel_id=nid,
        run_key=run.run_key,
        attempt_key="attempt",
        owner_epoch=1,
        producer_version="v1",
        source_manifest_hash="b" * 64,
        status="applied",
        payload_json={
            "scene_id": scene,
            "scene_index": 0,
            "source_binding": {"content_hash": "a" * 64},
            "owner_token": "never-export",
            "scene_spatial_review": {"stage": "sampling"},
            "optional_step_coverage": {"spatial": {"status": "unknown"}},
        },
    )
    receipt = EvolutionReceiptRecord(
        novel_id=nid,
        run_key=run.run_key,
        attempt_key="attempt",
        execution_status="committed",
        committed_scene_index=0,
        committed_source_revision=1,
        receipt_json={"source_manifest_hash": "b" * 64},
    )
    db_session.add_all([run, attempt, receipt])
    await db_session.flush()
    statements = []

    def capture(_conn, _cursor, sql, *_args):
        statements.append(sql)

    event.listen(db_session.bind.sync_engine, "before_cursor_execute", capture)
    try:
        result = await read_map_spatial_evaluation_receipts(
            db_session, test_project_id, run.run_key, operation, [scene]
        )
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", capture)
    assert result["request"]["discover_spatial"] is True
    assert (
        result["attempts"][0]["journals"]["scene_spatial_review"]["stage"] == "sampling"
    )
    assert result["receipts"][0]["id"] == str(receipt.id)
    assert "never-export" not in json.dumps(result)
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for sql in statements
    )
    assert not db_session.new and not db_session.dirty
    with pytest.raises(ConflictError, match="范围"):
        await read_map_spatial_evaluation_receipts(
            db_session, test_project_id, run.run_key, operation, [other]
        )
    with pytest.raises(ConflictError, match="不属于"):
        await read_map_spatial_evaluation_receipts(
            db_session, test_project_id, run.run_key, str(uuid4()), [scene]
        )
    with pytest.raises(NotFoundError):
        await read_map_spatial_evaluation_receipts(
            db_session, test_project_id, "foreign-run", operation, [scene]
        )
