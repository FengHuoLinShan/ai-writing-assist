import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select

from core.config import get_settings
from infrastructure.tasks.facade import enqueue_task
from infrastructure.tasks.models import AsyncTask
from modules.account.facade import current_account_id
from modules.assistant import proactive
from modules.assistant.models import AssistantWatch
from modules.assistant.schemas import ProactivePolicy


@pytest.mark.asyncio
async def test_scene_change_reports_stale_adopted_script_without_rewriting(
    db_session, test_project_id, monkeypatch
):
    from modules.story.outline_state.schemas import SceneUpdate
    from modules.story.outline_state.services import SceneService
    from modules.story.proactive import review_references, schedule_proactive_review
    from modules.story.service import StoryService
    from modules.story.tests.test_story_service import _scene

    nid = test_project_id
    scene = await _scene(db_session, nid)
    story = StoryService()
    script = await story.create_script_revision(
        db_session,
        novel_id=nid,
        scene_id=str(scene.id),
        file_key="opening",
        content="在窗前观察。",
        content_json=None,
        expected_revision_id=None,
        adopt=True,
    )
    expected_revision = script.current_revision_id
    monkeypatch.setattr(
        proactive, "get_settings", lambda: replace(get_settings(), assistant_enabled=True)
    )
    await proactive.save_policy(db_session, nid, ProactivePolicy(enabled=True))
    await SceneService().update(
        db_session, str(scene.id), SceneUpdate(goal="改为先调查失踪事件"), novel_id=nid
    )
    watch = await db_session.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == uuid.UUID(nid))
    )
    change = watch.dirty_json[f"outline_scene:{scene.id}"]
    submitted = await schedule_proactive_review(
        db_session,
        nid,
        change,
        {
            "_assistant_policy": {
                "owner_id": str(current_account_id()),
                "excluded_targets": [],
            }
        },
    )
    task = await db_session.get(AsyncTask, uuid.UUID(submitted["task_id"]))
    result = await review_references(db_session, task)
    assert len(result["findings"]) == 1
    assert result["findings"][0]["code"] == "story_reference_stale"
    assert (
        await story.get_script_file(db_session, nid, str(script.id))
    ).current_revision_id == expected_revision


@pytest.mark.asyncio
async def test_import_completion_marks_same_transaction_and_summarizes_only_its_receipt(
    db_session, test_project_id, monkeypatch
):
    from modules.imports.assistant_tools import (
        review_completed_import,
        schedule_proactive_review,
    )
    from modules.imports.models import ImportWorkflowRun
    from modules.imports.workflow_runs import (
        ImportWorkflowOwnerToken,
        ImportWorkflowRunService,
    )
    from modules.imports.workflow_schemas import DeepImportProgress

    nid = test_project_id
    monkeypatch.setattr(
        proactive, "get_settings", lambda: replace(get_settings(), assistant_enabled=True)
    )
    await proactive.save_policy(
        db_session, nid, ProactivePolicy(enabled=True, categories=["imports"])
    )
    task_id = uuid.UUID(enqueue_task(db_session, "deep_import", novel_id=nid, meta={}))
    await db_session.flush()
    lease = str(uuid.uuid4())
    run = ImportWorkflowRun(
        novel_id=uuid.UUID(nid),
        task_id=task_id,
        workflow_type="deep_import",
        start_chapter=1,
        end_chapter=2,
        status="running",
        generation=1,
        owner_task_id=task_id,
        owner_attempt=1,
        owner_lease_id=lease,
    )
    db_session.add(run)
    await db_session.flush()
    progress = DeepImportProgress(
        novel_id=nid, start_chapter=1, end_chapter=2, degraded=True
    ).model_dump(mode="json")
    await ImportWorkflowRunService().complete(
        db_session,
        owner=ImportWorkflowOwnerToken(str(run.id), str(task_id), 1, 1, lease),
        progress=progress,
    )
    watch = await db_session.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == uuid.UUID(nid))
    )
    change = watch.dirty_json[f"import_workflow:{run.id}"]
    submitted = await schedule_proactive_review(
        db_session,
        nid,
        change,
        {"_assistant_policy": {"owner_id": str(current_account_id())}},
    )
    task = await db_session.get(AsyncTask, uuid.UUID(submitted["task_id"]))
    result = await review_completed_import(db_session, task)
    assert result["findings"][0]["kind"] == "reminder"
    assert result["findings"][0]["location"]["source_task_id"] == str(task_id)
    assert "语义审稿" in result["not_checked"][0]
    assert run.status == "done"
