from __future__ import annotations

from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock

import pytest

from modules.world.schemas import (
    WorldGenerationChatResponse,
    WorldGenerationSourceSnapshot,
)


async def _create_project(async_client) -> str:
    response = await async_client.post(
        "/api/projects",
        json={"title": "Context gate"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _confirm(async_client, novel_id: str, action: str) -> str:
    payload = {
        "novel_id": novel_id,
        "action": action,
        "task": "核对本次资料",
        "scope": "generation_center",
        "budget_tokens": 0,
    }
    preview = await async_client.post(
        "/api/evidence/compilation/compile",
        json=payload,
    )
    assert preview.status_code == 200, preview.text
    confirmed = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            **payload,
            "expected_context_fingerprint": preview.json()["context_fingerprint"],
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    return confirmed.json()["id"]


def _chat_payload(novel_id: str, confirmation_id: str | None = None) -> dict:
    payload = {
        "novel_id": novel_id,
        "source_context": {"kind": "project"},
        "target": {"kind": "core_entity", "template": "none"},
        "messages": [{"role": "user", "content": "检查港口设定"}],
    }
    if confirmation_id:
        payload["context_confirmation_id"] = confirmation_id
    return payload


@pytest.mark.asyncio
async def test_manual_world_action_requires_matching_confirmation(
    async_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world import api as world_api

    novel_id = await _create_project(async_client)
    missing = await async_client.post(
        "/api/world/generation-center/chat",
        json=_chat_payload(novel_id),
    )
    assert missing.status_code == 400
    assert "context_confirmation_id" in missing.text

    wrong_action_id = await _confirm(async_client, novel_id, "world.ask")
    mismatched = await async_client.post(
        "/api/world/generation-center/chat",
        json=_chat_payload(novel_id, wrong_action_id),
    )
    assert mismatched.status_code == 400
    assert "action mismatch" in mismatched.text

    confirmation_id = await _confirm(
        async_client,
        novel_id,
        "world.generation.chat",
    )
    chat = AsyncMock(
        return_value=WorldGenerationChatResponse(
            reply="已核对",
            source_snapshot=WorldGenerationSourceSnapshot(kind="project"),
        )
    )
    monkeypatch.setattr(world_api._world_generation_service, "chat", chat)
    accepted = await async_client.post(
        "/api/world/generation-center/chat",
        json=_chat_payload(novel_id, confirmation_id),
    )
    assert accepted.status_code == 200, accepted.text
    chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_world_validation_worker_passes_confirmed_allowlist() -> None:
    from modules.world import tasks as world_tasks

    prepared = SimpleNamespace(confirmation=SimpleNamespace(selected_asset_ids={}))
    task = SimpleNamespace(
        id="22222222-2222-2222-2222-222222222222",
        task_type="world_validation",
        status="running",
        lease_id="lease-1",
        attempt=1,
        meta={
            "novel_id": "11111111-1111-1111-1111-111111111111",
            "run_id": "33333333-3333-3333-3333-333333333333",
            "context_confirmation_id": "confirmation-1",
        },
        update_progress=mock.MagicMock(),
    )
    db = SimpleNamespace(task_checkpoint_enabled=True)

    with (
        mock.patch(
            "modules.project.facade.require_active_project",
            autospec=True,
        ),
        mock.patch.object(
            world_tasks.context_facade,
            "prepare_confirmed_ai_action",
            autospec=True,
            return_value=prepared,
        ),
        mock.patch(
            "modules.world.services.worldbuilding.world_validation_service.WorldValidationService",
            autospec=True,
        ) as service_cls,
    ):
        service_cls.return_value.execute_run.return_value = {"status": "completed"}
        result = await world_tasks.handle_world_validation(db, task)

    assert result == {"status": "completed"}
    assert (
        service_cls.return_value.execute_run.await_args.kwargs["confirmed_context"]
        is prepared
    )


@pytest.mark.asyncio
async def test_manual_synopsis_worker_passes_confirmed_manifest() -> None:
    from modules.world import tasks as world_tasks

    prepared = SimpleNamespace(confirmation=SimpleNamespace(selected_asset_ids={}))
    task = SimpleNamespace(
        id="22222222-2222-2222-2222-222222222222",
        meta={
            "novel_id": "11111111-1111-1111-1111-111111111111",
            "source_hash": "a" * 64,
            "context_confirmation_id": "confirmation-1",
        },
        result=None,
        update_progress=mock.MagicMock(),
    )
    db = SimpleNamespace()

    async def refresh_for_task(*_args, **kwargs):
        assert kwargs["confirmed_context"] is prepared
        kwargs["checkpoint_callback"]({"promoted": True}, 0.9)

    with (
        mock.patch(
            "modules.evidence.facade.prepare_confirmed_ai_action",
            autospec=True,
            return_value=prepared,
        ),
        mock.patch(
            "modules.world.services.worldbuilding.world_bible_synopsis_service.WorldBibleSynopsisService",
            autospec=True,
        ) as service_cls,
    ):
        service_cls.return_value.refresh_for_task.side_effect = refresh_for_task
        result = await world_tasks.handle_world_bible_synopsis_refresh(db, task)

    assert result == {"promoted": True}
