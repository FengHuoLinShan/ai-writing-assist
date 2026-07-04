from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import mock

import pytest

from modules.outline.ai_workflow_service import OutlineAIWorkflowService

pytestmark = [pytest.mark.asyncio]


async def test_extract_chapter_scenes_uses_batch_scene_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = mock.AsyncMock()
    novel_id = str(uuid.uuid4())
    created_ids = [uuid.uuid4(), uuid.uuid4()]
    scene_service = SimpleNamespace(
        get_ordered=mock.AsyncMock(
            side_effect=AssertionError("should not load every scene for next index"),
        ),
        get_next_scene_index=mock.AsyncMock(return_value=5),
        create=mock.AsyncMock(side_effect=AssertionError("should use batch create")),
        batch_create_models_from_dicts=mock.AsyncMock(
            return_value=[
                SimpleNamespace(id=created_ids[0]),
                SimpleNamespace(id=created_ids[1]),
            ],
        ),
    )
    attached_refs: list[dict] = []

    class _FakeLLMClient:
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

    async def attach_result_refs(_db, *, result_refs, **_kwargs):
        attached_refs.extend(result_refs)

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
        attach_result_refs,
    )
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.context_facade.attach_result_ref",
        mock.AsyncMock(side_effect=AssertionError("should attach concrete scenes")),
    )
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.get_settings",
        lambda: SimpleNamespace(llm_model="test-model"),
    )
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.LLMClient",
        lambda: _FakeLLMClient(),
    )
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.SceneService",
        lambda: scene_service,
    )

    result = await OutlineAIWorkflowService().extract_chapter_scenes(
        db,
        novel_id=novel_id,
        confirmation_id="confirmation-1",
        task_id="task-1",
        chapter_index=7,
    )

    assert result == {
        "scene_ids": [str(created_id) for created_id in created_ids],
        "total_scenes": 2,
    }
    scene_service.get_ordered.assert_not_awaited()
    scene_service.get_next_scene_index.assert_awaited_once()
    scene_service.create.assert_not_awaited()
    scene_service.batch_create_models_from_dicts.assert_awaited_once()
    payloads = scene_service.batch_create_models_from_dicts.await_args.args[2]
    assert [payload["scene_index"] for payload in payloads] == [5, 6]
    assert len(payloads[0]["title"]) == 255
    assert payloads[0]["chapter_ids"] == ["7"]
    assert payloads[1]["chapter_ids"] == ["9"]
    assert attached_refs == [
        {"type": "outline_scene", "id": str(created_ids[0])},
        {"type": "outline_scene", "id": str(created_ids[1])},
    ]
    db.flush.assert_awaited_once()
