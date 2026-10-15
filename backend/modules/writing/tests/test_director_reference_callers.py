from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from modules.evidence.compilation.contracts import ConfirmedAIActionContext
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)
from modules.writing.generation_service import WritingGenerationService
from modules.writing.schemas import (
    WritingGenerateRequest,
    WritingTargetedRevisionRequest,
)
from modules.writing.semantic_review import WritingSemanticWorkflowService


class _Db:
    async def flush(self):
        return None


def _confirmed_context(novel_id, scene_id, reference_id, *, reveal_mode="author_safe"):
    section = ContextSection(
        key="director_reference",
        tier=Tier.P3,
        content="作者保存的参考副本",
        token_count=5,
        sources=[
            {
                "type": "director_reference",
                "id": reference_id,
                "label": "本场表演",
                "status": "saved_copy",
                "source_basis_hash": "a" * 64,
            }
        ],
        retrieval_metadata={"reference_ids": [reference_id]},
    )
    return ConfirmedAIActionContext(
        confirmation=None,
        compiled=CompiledContext(sections=[section], total_tokens=5),
        rendered_markdown="参考资料",
        compile_options={
            "scene_id": scene_id,
            "reveal_mode": reveal_mode,
            "viewpoint_character_id": "pov-1" if reveal_mode == "character" else None,
            "director_reference_ids": [reference_id],
        },
        result_refs=[],
    )


def test_generation_references_are_explicit_unique_and_default_off():
    request = WritingGenerateRequest(
        novel_id=str(uuid4()),
        chapter_index=1,
        context_confirmation_id=str(uuid4()),
    )
    assert request.director_reference_ids == []

    reference_id = str(uuid4())
    selected = WritingGenerateRequest(
        novel_id=request.novel_id,
        chapter_index=1,
        context_confirmation_id=str(uuid4()),
        director_reference_ids=[reference_id],
    )
    assert selected.director_reference_ids == [reference_id]
    with pytest.raises(ValidationError, match="unique"):
        WritingGenerateRequest(
            novel_id=request.novel_id,
            chapter_index=1,
            context_confirmation_id=str(uuid4()),
            director_reference_ids=[reference_id, reference_id],
        )


def test_targeted_revision_requires_its_own_evidence_confirmation_for_references():
    base = {
        "novel_id": str(uuid4()),
        "draft_id": str(uuid4()),
        "review_task_id": str(uuid4()),
        "finding_ids": ["finding-1"],
        "director_reference_ids": [str(uuid4())],
    }
    with pytest.raises(ValidationError, match="单独确认"):
        WritingTargetedRevisionRequest(**base)

    request = WritingTargetedRevisionRequest(
        **base,
        context_confirmation_id=str(uuid4()),
    )
    assert request.context_confirmation_id
    assert len(request.director_reference_ids) == 1


@pytest.mark.asyncio
async def test_generate_freezes_only_matching_author_confirmed_reference(monkeypatch):
    import infrastructure.tasks.facade as task_facade
    import modules.evidence.facade as evidence_facade
    import modules.project.facade as project_facade
    import modules.story.facade as story_facade

    novel_id, scene_id, reference_id = str(uuid4()), str(uuid4()), str(uuid4())
    confirmed = _confirmed_context(novel_id, scene_id, reference_id)
    calls = {}
    monkeypatch.setattr(task_facade, "get_operation_task", AsyncMock(return_value=None))

    async def enqueue(_db, **kwargs):
        calls.update(kwargs)
        return SimpleNamespace(reused=False, task_id=str(uuid4()), status="pending")

    monkeypatch.setattr(task_facade, "enqueue_task_with_optional_operation", enqueue)
    monkeypatch.setattr(project_facade, "require_active_project", AsyncMock())
    monkeypatch.setattr(
        project_facade,
        "build_project_llm_execution_snapshot",
        AsyncMock(return_value={"novel_id": novel_id, "profile": {"model": "frozen"}}),
    )
    monkeypatch.setattr(
        evidence_facade, "prepare_confirmed_ai_action", AsyncMock(return_value=confirmed)
    )
    monkeypatch.setattr(
        evidence_facade, "confirmed_knowledge_source_count", lambda _context: 2
    )
    monkeypatch.setattr(evidence_facade, "bind_confirmed_action_result", AsyncMock())
    monkeypatch.setattr(
        story_facade,
        "get_scene_story_assets",
        AsyncMock(return_value={"adopted_scripts": []}),
    )

    request = WritingGenerateRequest(
        novel_id=novel_id,
        chapter_index=1,
        context_confirmation_id=str(uuid4()),
        director_reference_ids=[reference_id],
        operation_id=uuid4(),
    )
    result = await WritingGenerationService().submit_generation(_Db(), request)

    assert result["status"] == "pending"
    assert calls["request_payload"]["director_reference_ids"] == [reference_id]
    frozen = calls["meta"]["director_reference_context_snapshot"]
    assert frozen["selected_ids"] == [reference_id]
    assert frozen["section"]["content"] == "作者保存的参考副本"


@pytest.mark.asyncio
async def test_targeted_revision_binds_references_to_its_confirmed_scene_and_pov(
    monkeypatch,
):
    import infrastructure.tasks.facade as task_facade
    import modules.evidence.facade as evidence_facade
    import modules.project.facade as project_facade

    novel_id, scene_id, reference_id = str(uuid4()), str(uuid4()), str(uuid4())
    confirmation_id = str(uuid4())
    confirmed = _confirmed_context(
        novel_id, scene_id, reference_id, reveal_mode="character"
    )
    calls = {}
    monkeypatch.setattr(task_facade, "get_operation_task", AsyncMock(return_value=None))

    async def enqueue(_db, **kwargs):
        calls.update(kwargs)
        return SimpleNamespace(reused=False, task_id=str(uuid4()), status="pending")

    monkeypatch.setattr(task_facade, "enqueue_task_with_optional_operation", enqueue)
    monkeypatch.setattr(project_facade, "require_active_project", AsyncMock())
    monkeypatch.setattr(
        project_facade,
        "build_project_llm_execution_snapshot",
        AsyncMock(return_value={"novel_id": novel_id, "profile": {"model": "frozen"}}),
    )
    monkeypatch.setattr(
        evidence_facade, "prepare_confirmed_ai_action", AsyncMock(return_value=confirmed)
    )
    monkeypatch.setattr(evidence_facade, "attach_result_ref", AsyncMock())
    base = SimpleNamespace(
        provenance_json={
            "scene_id": scene_id,
            "generation_profile": "pov_character",
            "viewpoint_character_id": "pov-1",
        }
    )
    service = WritingSemanticWorkflowService()
    monkeypatch.setattr(
        service,
        "prepare_targeted_revision",
        AsyncMock(return_value={"base": base}),
    )

    request = WritingTargetedRevisionRequest(
        novel_id=novel_id,
        draft_id=str(uuid4()),
        review_task_id=str(uuid4()),
        finding_ids=["finding-1"],
        context_confirmation_id=confirmation_id,
        director_reference_ids=[reference_id],
        operation_id=uuid4(),
    )
    result = await service.submit_targeted_revision(_Db(), request)

    assert result["status"] == "pending"
    assert calls["meta"]["context_confirmation_id"] == confirmation_id
    assert calls["meta"]["director_reference_context_snapshot"]["selected_ids"] == [
        reference_id
    ]
