from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.contracts import CompletedTaskPayloadContract
from infrastructure.tasks.models import AsyncTask
from modules.outline.ai_workflow_service import OutlineAIWorkflowService

pytestmark = [pytest.mark.asyncio]


async def test_generate_returns_preview_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = mock.AsyncMock()
    generator = SimpleNamespace(
        generate=mock.AsyncMock(
            return_value={
                "total_threads": 1,
                "total_arcs": 0,
                "total_scenes": 0,
                "threads": [{"name": "主线", "display_state": "review"}],
                "arcs": [],
                "scenes": [],
                "extra_sections": {},
                "warnings": [],
                "draft_structure": {"threads": [{"name": "主线"}]},
                "requires_apply": True,
            }
        )
    )
    compile_confirmation = mock.AsyncMock(return_value=SimpleNamespace())
    attach_preview = mock.AsyncMock()
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.context_facade.compile_from_confirmation",
        compile_confirmation,
    )
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.context_facade.attach_result_ref",
        attach_preview,
    )
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.PlotStructureGenerator",
        lambda **_kwargs: generator,
    )

    result = await OutlineAIWorkflowService(llm_client=mock.MagicMock()).generate(
        db,
        novel_id="11111111-1111-1111-1111-111111111111",
        confirmation_id="confirmation-1",
        task_id="task-1",
        start_chapter=1,
        end_chapter=3,
    )

    assert generator.generate.await_args.kwargs["persist"] is False
    assert result["source_task_id"] == "task-1"
    assert result["context_confirmation_id"] == "confirmation-1"
    attach_preview.assert_awaited_once_with(
        db,
        confirmation_id="confirmation-1",
        result_type="outline_structure_preview",
        result_id="task-1",
        status="done",
    )
    db.flush.assert_awaited_once()


async def test_apply_structure_preview_requires_confirmation_and_rejects_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OutlineAIWorkflowService()
    db = mock.AsyncMock()
    source_task_id = str(uuid.uuid4())
    with pytest.raises(PermissionError, match="confirmed=true"):
        await service.apply_structure_preview(
            db,
            novel_id=str(uuid.uuid4()),
            confirmation_id="confirmation-1",
            source_task_id=source_task_id,
            draft_structure={},
            confirmed=False,
        )

    get_payload = mock.AsyncMock(return_value=None)
    monkeypatch.setattr(
        "infrastructure.tasks.facade.get_completed_task_payload",
        get_payload,
    )
    novel_id = str(uuid.uuid4())
    with pytest.raises(ValueError, match="confirmed outline preview task"):
        await service.apply_structure_preview(
            db,
            novel_id=novel_id,
            confirmation_id="confirmation-1",
            source_task_id=source_task_id,
            draft_structure={},
            confirmed=True,
        )

    get_payload.assert_awaited_once_with(
        db,
        task_id=source_task_id,
        task_type="outline_generate",
        novel_id=novel_id,
        for_update=True,
    )


async def test_extract_chapter_scenes_returns_preview_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = mock.AsyncMock()
    novel_id = str(uuid.uuid4())

    class _FakeLLMClient:
        model_name = "test-model"

        async def generate_structured(self, _request, schema, **_kwargs):
            return schema(
                scenes=[
                    {
                        "title": "伏击" * 200,
                        "goal": "截获密信",
                        "chapter_ids": [],
                        "scene_chunks": [],
                    },
                    {
                        "title": "追索",
                        "chapter_ids": ["9"],
                        "scene_chunks": [
                            {"chapter_index": 9, "start_pos": 10, "end_pos": 30}
                        ],
                    },
                ]
            )

    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.context_facade.compile_from_confirmation",
        mock.AsyncMock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.context_facade.render_compiled_context",
        lambda _compiled: "compiled context",
    )
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.context_facade.attach_result_refs",
        mock.AsyncMock(side_effect=AssertionError("preview must not attach scenes")),
    )
    attach_preview = mock.AsyncMock()
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.context_facade.attach_result_ref",
        attach_preview,
    )
    result = await OutlineAIWorkflowService(
        llm_client=_FakeLLMClient(),
    ).extract_chapter_scenes(
        db,
        novel_id=novel_id,
        confirmation_id="confirmation-1",
        task_id="task-1",
        chapter_index=7,
    )

    assert result["scene_ids"] == []
    assert result["total_scenes"] == 2
    assert result["requires_apply"] is True
    payloads = result["draft_scenes"]
    assert len(payloads[0]["title"]) == 255
    assert payloads[0]["chapter_ids"] == ["7"]
    assert payloads[1]["chapter_ids"] == ["9"]
    assert all(payload["display_state"] == "review" for payload in payloads)
    assert all(payload["structure_meta"]["preview_only"] is True for payload in payloads)
    attach_preview.assert_awaited_once_with(
        db,
        confirmation_id="confirmation-1",
        result_type="outline_scene_preview",
        result_id="task-1",
        status="done",
    )
    db.flush.assert_awaited_once()


async def test_apply_chapter_scene_preview_requires_confirmation_and_clears_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = mock.AsyncMock()
    novel_id = str(uuid.uuid4())
    created_id = uuid.uuid4()
    source_task_id = str(uuid.uuid4())
    scene_service = SimpleNamespace(
        get_next_scene_index=mock.AsyncMock(return_value=8),
        batch_create_models_from_dicts=mock.AsyncMock(
            return_value=[SimpleNamespace(id=created_id)]
        ),
    )
    require_confirmation = mock.AsyncMock()
    attach_refs = mock.AsyncMock()
    validate_mapping = mock.AsyncMock()
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.context_facade.require_fresh_confirmation",
        require_confirmation,
    )
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.context_facade.attach_result_refs",
        attach_refs,
    )
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.SceneService",
        lambda: scene_service,
    )
    monkeypatch.setattr(
        "modules.outline.scene_workbench.SceneWorkbenchService.validate_mapping_chapters",
        validate_mapping,
    )

    service = OutlineAIWorkflowService()
    with pytest.raises(PermissionError, match="confirmed=true"):
        await service.apply_chapter_scene_preview(
            db,
            novel_id=novel_id,
            confirmation_id="confirmation-1",
            source_task_id=source_task_id,
            draft_scenes=[{"title": "预览"}],
            confirmed=False,
        )

    preview_task = CompletedTaskPayloadContract(
        task_id=source_task_id,
        task_type="outline_chapter_scenes_extract",
        novel_id=novel_id,
        context_confirmation_id="confirmation-1",
        revision_token=datetime(2026, 7, 14, tzinfo=UTC),
        result={
            "draft_scenes": [{"title": "预览"}],
            "requires_apply": True,
        },
    )
    applied_task = CompletedTaskPayloadContract(
        task_id=source_task_id,
        task_type="outline_chapter_scenes_extract",
        novel_id=novel_id,
        context_confirmation_id=preview_task.context_confirmation_id,
        revision_token=datetime(2026, 7, 14, 0, 0, 1, tzinfo=UTC),
        result={
            **preview_task.result,
            "apply_status": "applied",
            "applied_scene_ids": [str(created_id)],
        },
    )
    get_payload = mock.AsyncMock(side_effect=[preview_task, applied_task])
    replace_result = mock.AsyncMock(return_value=True)
    monkeypatch.setattr(
        "infrastructure.tasks.facade.get_completed_task_payload",
        get_payload,
    )
    monkeypatch.setattr(
        "infrastructure.tasks.facade.replace_completed_task_result",
        replace_result,
    )

    result = await service.apply_chapter_scene_preview(
        db,
        novel_id=novel_id,
        confirmation_id="confirmation-1",
        source_task_id=source_task_id,
        draft_scenes=[
            {
                "title": "编辑后采用",
                "source": "untrusted",
                "status": "candidate",
                "pov_character_id": str(uuid.uuid4()),
                "chapter_ids": ["7"],
                "scene_chunks": [
                    {
                        "chapter_index": 7,
                        "start_pos": 1,
                        "end_pos": 3,
                        "source_draft_id": str(uuid.uuid4()),
                        "source_content_hash": "spoofed",
                    }
                ],
                "structure_meta": {
                    "needs_review": True,
                    "preview_only": True,
                    "workflow_id": "spoofed-workflow",
                    "auto_ingested": True,
                },
            }
        ],
        confirmed=True,
    )

    assert result == {
        "status": "applied",
        "scene_ids": [str(created_id)],
        "total_scenes": 1,
    }
    require_confirmation.assert_awaited_once_with(
        db,
        novel_id=novel_id,
        action="outline.chapter_scenes.extract",
        confirmation_id="confirmation-1",
    )
    payload = scene_service.batch_create_models_from_dicts.await_args.args[2][0]
    assert payload["scene_index"] == 8
    assert payload["status"] == "draft"
    assert payload["source"] == "ai_generated"
    assert payload["structure_meta"]["needs_review"] is False
    assert payload["structure_meta"]["preview_only"] is False
    assert "workflow_id" not in payload["structure_meta"]
    assert "auto_ingested" not in payload["structure_meta"]
    assert payload["pov_character_id"] is None
    assert payload["scene_chunks"] == [{"chapter_index": 7, "start_pos": 1, "end_pos": 3}]
    validate_mapping.assert_awaited_once_with(
        db,
        novel_id,
        ["7"],
        [{"chapter_index": 7, "start_pos": 1, "end_pos": 3}],
    )
    assert payload["structure_meta"]["adopted_at"]
    assert payload["structure_meta"]["adopted_from_preview_task_id"] == source_task_id
    attach_refs.assert_awaited_once_with(
        db,
        confirmation_id="confirmation-1",
        result_refs=[{"type": "outline_scene", "id": str(created_id)}],
        status="done",
    )
    replace_result.assert_awaited_once_with(
        db,
        task_id=source_task_id,
        task_type="outline_chapter_scenes_extract",
        novel_id=novel_id,
        expected_revision_token=preview_task.revision_token,
        result={
            **preview_task.result,
            "apply_status": "applied",
            "applied_scene_ids": [str(created_id)],
        },
    )

    replay = await service.apply_chapter_scene_preview(
        db,
        novel_id=novel_id,
        confirmation_id="confirmation-1",
        source_task_id=source_task_id,
        draft_scenes=[{"title": "重复提交"}],
        confirmed=True,
    )
    assert replay == result
    scene_service.batch_create_models_from_dicts.assert_awaited_once()
    attach_refs.assert_awaited_once()


async def test_apply_chapter_scene_preview_api_persists_explicit_adoption(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    from modules.context.facade import confirm_context
    from modules.outline.models import Scene
    from modules.writing.models import WritingDraft

    db_session.add(
        WritingDraft(
            novel_id=uuid.UUID(test_project_id),
            chapter_index=1,
            title="第一章",
            content="正文",
            content_hash="chapter-1",
            version_number=1,
            status="draft",
        )
    )
    await db_session.flush()

    confirmation = await confirm_context(
        db_session,
        novel_id=test_project_id,
        action="outline.chapter_scenes.extract",
        task="提取第一章 Scene preview",
        scope="chapter",
        chapter_index=1,
    )
    task = AsyncTask(
        task_type="outline_chapter_scenes_extract",
        status="done",
        meta={
            "novel_id": test_project_id,
            "context_confirmation_id": confirmation.id,
            "chapter_index": 1,
        },
        result={
            "scene_ids": [],
            "draft_scenes": [{"title": "预览 Scene", "chapter_ids": ["1"]}],
            "total_scenes": 1,
            "requires_apply": True,
        },
    )
    db_session.add(task)
    await db_session.flush()

    invalid_mapping = await async_client.post(
        "/api/outline/chapter-scenes/apply",
        json={
            "novel_id": test_project_id,
            "context_confirmation_id": confirmation.id,
            "source_task_id": str(task.id),
            "draft_scenes": [{"title": "越界映射", "chapter_ids": ["999"]}],
            "confirmed": True,
        },
    )
    assert invalid_mapping.status_code == 400
    assert "not in this novel" in invalid_mapping.text

    response = await async_client.post(
        "/api/outline/chapter-scenes/apply",
        json={
            "novel_id": test_project_id,
            "context_confirmation_id": confirmation.id,
            "source_task_id": str(task.id),
            "draft_scenes": [
                {
                    "title": "作者编辑后的 Scene",
                    "chapter_ids": ["1"],
                    "status": "candidate",
                    "pov_character_id": str(uuid.uuid4()),
                    "structure_meta": {
                        "needs_review": True,
                        "workflow_id": "spoofed-workflow",
                        "auto_ingested": True,
                    },
                }
            ],
            "confirmed": True,
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "applied"
    assert data["total_scenes"] == 1
    scene = await db_session.get(Scene, uuid.UUID(data["scene_ids"][0]))
    assert scene is not None
    assert scene.title == "作者编辑后的 Scene"
    assert scene.status == "draft"
    assert scene.source == "ai_generated"
    assert scene.structure_meta["needs_review"] is False
    assert scene.structure_meta["adopted_at"]
    assert scene.structure_meta["adopted_from_preview_task_id"] == str(task.id)
    assert "workflow_id" not in scene.structure_meta
    assert "auto_ingested" not in scene.structure_meta
    assert scene.pov_character_id is None
    await db_session.refresh(task)
    assert task.result["applied_scene_ids"] == data["scene_ids"]


async def test_apply_structure_preview_api_persists_explicit_adoption_once(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    from sqlalchemy import select

    from modules.context.facade import confirm_context
    from modules.outline.models import PlotThread

    confirmation = await confirm_context(
        db_session,
        novel_id=test_project_id,
        action="outline.generate",
        task="生成大纲 preview",
        scope="chapter",
        chapter_index=1,
    )
    draft_structure = {
        "threads": [
            {
                "name": "预览主线",
                "thread_type": "main",
                "summary": "原始摘要",
                "display_state": "review",
                "needs_review": True,
            }
        ],
        "arcs": [],
        "scenes": [],
        "foreshadowing_plans": [],
        "reveal_plans": [],
        "offscreen_progress": [],
        "risks": [],
        "questions_for_user": [],
        "turning_points": [],
        "uncertain_items": [],
        "diagnostics": {},
    }
    task = AsyncTask(
        task_type="outline_generate",
        status="done",
        meta={
            "novel_id": test_project_id,
            "context_confirmation_id": confirmation.id,
            "start_chapter": 1,
            "end_chapter": 3,
        },
        result={
            "draft_structure": draft_structure,
            "requires_apply": True,
        },
    )
    db_session.add(task)
    await db_session.flush()
    payload = {
        "novel_id": test_project_id,
        "context_confirmation_id": confirmation.id,
        "source_task_id": str(task.id),
        "draft_structure": {
            **draft_structure,
            "threads": [
                {
                    **draft_structure["threads"][0],
                    "name": "作者采用的主线",
                    "summary": "作者修改后的摘要",
                }
            ],
        },
        "confirmed": True,
    }

    response = await async_client.post("/api/outline/generate/apply", json=payload)

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "applied"
    assert data["total_threads"] == 1
    thread_id = data["threads"][0]["id"]
    thread = (
        await db_session.execute(
            select(PlotThread).where(PlotThread.id == uuid.UUID(thread_id))
        )
    ).scalar_one()
    assert thread.name == "作者采用的主线"
    assert thread.status == "draft"
    assert thread.provenance_meta["source"] == "ai_generated"
    assert thread.provenance_meta["needs_review"] is False
    assert thread.provenance_meta["adopted_at"]
    assert thread.provenance_meta["adopted_from_preview_task_id"] == str(task.id)

    replay = await async_client.post("/api/outline/generate/apply", json=payload)
    assert replay.status_code == 201, replay.text
    assert replay.json()["threads"][0]["id"] == thread_id
    all_threads = (
        (
            await db_session.execute(
                select(PlotThread).where(
                    PlotThread.novel_id == uuid.UUID(test_project_id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(all_threads) == 1
    await db_session.refresh(task)
    assert task.result["apply_status"] == "applied"
    assert task.result["requires_apply"] is False


async def test_apply_structure_preview_rolls_back_partial_failure_and_can_retry(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import func, select

    from modules.context.facade import confirm_context
    from modules.outline.generation.persister import PlotStructurePersister
    from modules.outline.models import PlotThread

    confirmation = await confirm_context(
        db_session,
        novel_id=test_project_id,
        action="outline.generate",
        task="验证结构采用原子性",
        scope="chapter",
        chapter_index=1,
    )
    draft_structure = {
        "threads": [
            {"name": "原子主线一", "thread_type": "main"},
            {"name": "原子主线二", "thread_type": "subplot"},
        ],
        "arcs": [],
        "scenes": [],
        "foreshadowing_plans": [],
        "reveal_plans": [],
        "offscreen_progress": [],
        "risks": [],
        "questions_for_user": [],
        "turning_points": [],
        "uncertain_items": [],
        "diagnostics": {},
    }
    task = AsyncTask(
        task_type="outline_generate",
        status="done",
        meta={
            "novel_id": test_project_id,
            "context_confirmation_id": confirmation.id,
            "start_chapter": 1,
            "end_chapter": 3,
        },
        result={"draft_structure": draft_structure, "requires_apply": True},
    )
    db_session.add(task)
    await db_session.flush()

    original_persist = PlotStructurePersister.persist

    async def persist_one_then_fail(self, db, novel_id, *_args, **_kwargs):
        db.add(
            PlotThread(
                novel_id=novel_id,
                name="不应留下的部分写入",
                thread_type="main",
                status="draft",
            )
        )
        await db.flush()
        raise RuntimeError("second structure item failed")

    monkeypatch.setattr(
        PlotStructurePersister,
        "persist",
        persist_one_then_fail,
    )
    service = OutlineAIWorkflowService()
    with pytest.raises(RuntimeError, match="second structure item failed"):
        await service.apply_structure_preview(
            db_session,
            novel_id=test_project_id,
            confirmation_id=confirmation.id,
            source_task_id=str(task.id),
            draft_structure=draft_structure,
            confirmed=True,
        )

    count_after_failure = await db_session.scalar(
        select(func.count(PlotThread.id)).where(
            PlotThread.novel_id == uuid.UUID(test_project_id)
        )
    )
    assert count_after_failure == 0
    assert task.result.get("apply_status") is None
    assert task.result["requires_apply"] is True

    monkeypatch.setattr(PlotStructurePersister, "persist", original_persist)
    result = await service.apply_structure_preview(
        db_session,
        novel_id=test_project_id,
        confirmation_id=confirmation.id,
        source_task_id=str(task.id),
        draft_structure=draft_structure,
        confirmed=True,
    )

    assert result["status"] == "applied"
    assert result["total_threads"] == 2
    count_after_retry = await db_session.scalar(
        select(func.count(PlotThread.id)).where(
            PlotThread.novel_id == uuid.UUID(test_project_id)
        )
    )
    assert count_after_retry == 2
