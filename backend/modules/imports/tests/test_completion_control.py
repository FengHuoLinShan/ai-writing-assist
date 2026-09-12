"""Real checkpoint deferral, fenced continuation, and scoped history."""

import uuid

import pytest

from modules.imports.completion_control import (
    list_recent_workflows,
    request_completion_defer,
)
from modules.imports.tests.test_targeted_completion_integration import (  # noqa: F401
    execute,
    prepare,
)
from modules.imports.tests.test_targeted_completion_integration import (
    provider as provider_fixture,
)
from modules.imports.workflow_runs import ImportWorkflowRunService
from tests.utils import _create_entity

provider = provider_fixture


async def test_defer_retains_roots_and_resume_writes_once(
    db_session, test_project_id, account_llm_connection, provider
):
    city = await _create_entity(db_session, test_project_id, "location", "青港")
    orchestrator, task, attempt = await prepare(
        db_session, test_project_id, [{"entity_id": str(city.id)}], ["青港坐落在北岸。"]
    )
    receipt = await request_completion_defer(db_session, task_id=str(task.id))
    assert receipt["status"] == "defer_requested"
    await db_session.commit()
    result = await execute(db_session, orchestrator, task, attempt)
    assert result["targeted_completion"]["status"] == "deferred"
    assert result["targeted_completion"]["completed_roots"] == 0
    assert provider[0] == []
    task.mark_done(result)
    await db_session.commit()
    response = await orchestrator.resume_interrupted(
        db_session, str(task.id), stage="targeted_completion"
    )
    assert response["task_id"] == str(task.id)
    assert response["status"] == "pending"
    with pytest.raises(ValueError, match="只有已暂缓"):
        await orchestrator.resume_interrupted(
            db_session, str(task.id), stage="targeted_completion"
        )
    task.mark_running()
    await db_session.flush()
    resumed = await ImportWorkflowRunService().claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type=task.task_type,
        attempt=task.attempt,
        lease_id=task.lease_id,
    )
    output = await execute(db_session, orchestrator, task, resumed)
    assert output["targeted_completion"]["status"] == "done"
    assert output["targeted_completion"]["filled"] == 1
    await db_session.refresh(city)
    assert city.summary == "坐落在北岸。"
    history = await list_recent_workflows(
        db_session, novel_id=test_project_id, skip=0, limit=20
    )
    assert history["total"] == 1
    assert "authorization_snapshot" not in history["items"][0]
    assert history["items"][0]["cleanup_eligible"] is False
    assert history["items"][0]["cleanup_status"] == "pending"
    assert history["items"][0]["cleanup_summary"] == {}
    assert await list_recent_workflows(
        db_session, novel_id=str(uuid.uuid4()), skip=0, limit=20
    ) == {"items": [], "total": 0}


async def test_deferred_resume_rejects_changed_manuscript(
    db_session, test_project_id, account_llm_connection, provider
):
    from modules.writing.facade import create_published_draft_only

    city = await _create_entity(db_session, test_project_id, "location", "青港")
    orchestrator, task, attempt = await prepare(
        db_session, test_project_id, [{"entity_id": str(city.id)}], ["青港坐落在北岸。"]
    )
    await request_completion_defer(db_session, task_id=str(task.id))
    result = await execute(db_session, orchestrator, task, attempt)
    task.mark_done(result)
    await db_session.commit()
    await create_published_draft_only(
        db_session, test_project_id, 1, content="青港的资料已由作者修改。"
    )
    await db_session.commit()
    with pytest.raises(ValueError, match="章节来源已变化"):
        await orchestrator.resume_interrupted(
            db_session, str(task.id), stage="targeted_completion"
        )
    assert task.status == "done"
    assert provider[0] == []


async def test_deferred_resume_does_not_compete_with_another_stage(
    db_session, test_project_id, account_llm_connection, provider
):
    city = await _create_entity(db_session, test_project_id, "location", "青港")
    orchestrator, task, attempt = await prepare(
        db_session, test_project_id, [{"entity_id": str(city.id)}], ["青港坐落在北岸。"]
    )
    await request_completion_defer(db_session, task_id=str(task.id))
    result = await execute(db_session, orchestrator, task, attempt)
    task.mark_done(result)
    await db_session.commit()
    await orchestrator.start_stage(
        db_session,
        test_project_id,
        1,
        1,
        stage="plot_structure",
        force=True,
        authorization_confirmed=True,
    )
    with pytest.raises(ValueError, match="已有整理任务"):
        await orchestrator.resume_interrupted(
            db_session, str(task.id), stage="targeted_completion"
        )
    assert task.status == "done"


async def test_defer_unknown_task_fails_closed(async_client):
    response = await async_client.post(
        f"/api/imports/targeted-completions/{uuid.uuid4()}/defer", json={}
    )
    assert response.status_code == 404
    invalid = await async_client.post(
        "/api/imports/targeted-completions/not-a-task/defer", json={}
    )
    assert invalid.status_code == 422


async def test_running_impact_uses_only_included_assets(
    db_session, test_project_id, monkeypatch
):
    from types import SimpleNamespace

    from modules.imports.completion_control import active_asset_impact
    from modules.imports.tests.test_workflow_runs import _create_pending_run

    _, run = await _create_pending_run(db_session, test_project_id)
    asset_id = str(uuid.uuid4())

    async def snapshots(_db, **scope):
        assert scope["novel_id"] == test_project_id
        return [
            SimpleNamespace(
                status="running",
                included_asset_ids={"entities": [asset_id]},
                chapter_index=2,
            ),
            SimpleNamespace(
                status="running",
                included_asset_ids={},
                excluded_asset_ids={"entities": [asset_id]},
                chapter_index=3,
            ),
            SimpleNamespace(
                status="succeeded",
                included_asset_ids={"entities": [asset_id]},
                chapter_index=4,
            ),
        ]

    monkeypatch.setattr("modules.evidence.facade.list_context_snapshots", snapshots)
    impact = await active_asset_impact(
        db_session, novel_id=test_project_id, asset_id=asset_id
    )
    assert len(impact["items"]) == 1
    assert impact["items"][0]["chapters"] == [2]
    assert impact["items"][0]["whole_unit"] is False
    run.status = "done"
    await db_session.flush()
    assert await active_asset_impact(
        db_session, novel_id=test_project_id, asset_id=asset_id
    ) == {"items": []}
