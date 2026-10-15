import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from core.errors import NotFoundError
from modules.account.facade import current_account_id
from modules.assistant.facade import read_map_spatial_evaluation_turn
from modules.assistant.models import AssistantActionBatch, AssistantRun


@pytest.mark.asyncio
async def test_persisted_turn_is_pure_read_and_never_infers_tool_calls(
    db_session, test_project_id
):
    scene = str(uuid4())
    run = AssistantRun(
        novel_id=UUID(test_project_id),
        owner_id=current_account_id(),
        status="completed",
        request_hash="a" * 64,
        request_json={
            "context": {
                "scene_id": scene,
                "scope": "current",
                "excluded_targets": ["map:hidden"],
            },
            "owner_token": "never-export",
            "agent_executor": {"api_key": "never-export"},
        },
        checkpoint_json={"model_history": [{"secret": "never-export"}]},
        result_json={"answer": "没有已确认路线。", "actions": []},
        budget_json={"requests": 2, "output_tokens": 100},
    )
    db_session.add(run)
    await db_session.flush()
    batch = AssistantActionBatch(
        novel_id=run.novel_id,
        run_id=run.id,
        fingerprint="b" * 64,
        status="completed",
        actions_json=[{"capability": "map.prepare_tray_placement"}],
        results_json=[{"status": "completed"}],
        authorization_json={"owner_token": "never-export"},
    )
    db_session.add(batch)
    await db_session.flush()
    statements = []

    def capture(_conn, _cursor, sql, *_args):
        statements.append(sql)

    event.listen(db_session.bind.sync_engine, "before_cursor_execute", capture)
    try:
        result = await read_map_spatial_evaluation_turn(
            db_session, test_project_id, str(run.id)
        )
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", capture)
    assert result["scene_ids"] == [scene]
    assert result["answer_status"] == "known" and result["result"]["answer"]
    assert (
        result["tool_invocations"] is None
        and result["tool_invocations_status"] == "unknown"
    )
    assert result["action_batch"]["results"] == batch.results_json
    assert result["usage"]["requests"] == 2
    assert "never-export" not in json.dumps(result)
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for sql in statements
    )
    assert not db_session.new and not db_session.dirty
    run.owner_id = uuid4()
    with pytest.raises(NotFoundError):
        await read_map_spatial_evaluation_turn(db_session, test_project_id, str(run.id))
