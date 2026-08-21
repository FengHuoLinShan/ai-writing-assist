from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modules.writing import api
from modules.writing.schemas import WritingGenerateRequest
from modules.writing.services import _story_assets_are_stale


def test_story_asset_staleness_only_reads_adopted_script_projection() -> None:
    assert not _story_assets_are_stale(None)
    assert not _story_assets_are_stale({"story_assets": {"adopted_scripts": []}})
    assert not _story_assets_are_stale(
        {"story_assets": {"adopted_scripts": [{"stale": False}]}}
    )
    assert _story_assets_are_stale(
        {"story_assets": {"adopted_scripts": [{"stale": True}]}}
    )


@pytest.mark.asyncio
async def test_generate_preflight_returns_structured_stale_story_assets_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _allow_project(*_args, **_kwargs) -> None:
        return None

    async def _no_existing_task(*_args, **_kwargs):
        return None

    async def _confirmed_context(*_args, **_kwargs):
        return SimpleNamespace(compile_options={"scene_id": "scene-1"})

    async def _stale_assets(*_args, **_kwargs):
        return {
            "adopted_scripts": [
                {
                    "id": "file-1",
                    "adopted_revision_id": "revision-1",
                    "basis_hash": "old",
                    "expected_basis_hash": "new",
                }
            ]
        }

    monkeypatch.setattr(api, "require_active_project", _allow_project)
    monkeypatch.setattr(api, "get_operation_task", _no_existing_task)
    monkeypatch.setattr(api, "prepare_confirmed_ai_action", _confirmed_context)
    monkeypatch.setattr(api, "get_scene_story_assets", _stale_assets)

    request = WritingGenerateRequest(
        novel_id="novel-1",
        chapter_index=1,
        context_confirmation_id="confirmation-1",
    )

    with pytest.raises(HTTPException) as caught:
        await api.generate_writing_candidate(SimpleNamespace(), request)

    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "stale_story_assets",
        "message": "已采用的 Scene 剧本依据已变化；请明确确认后继续写作",
        "assets": [
            {
                "file_id": "file-1",
                "adopted_revision_id": "revision-1",
                "basis_hash": "old",
                "expected_basis_hash": "new",
            }
        ],
    }


def test_writing_request_uses_explicit_stale_confirmation_wire() -> None:
    request = WritingGenerateRequest(
        novel_id="novel-1",
        chapter_index=1,
        context_confirmation_id="confirmation-1",
        confirm_stale_story_assets=True,
    )

    assert request.confirm_stale_story_assets is True
    assert "confirm_stale_story_assets" in request.model_dump()
