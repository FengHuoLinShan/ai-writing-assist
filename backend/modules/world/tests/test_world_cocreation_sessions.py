"""Persistent co-creation session and message API tests (ADR-0021)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.schemas import LLMCallResponse
from modules.world.models.cocreation import WorldCocreationMessage
from modules.world.models.worldbuilding import CreationSuggestion


async def _create_project(client: AsyncClient, title: str) -> str:
    response = await client.post("/api/projects", json={"title": title})
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def _create_session(
    client: AsyncClient,
    novel_id: str,
    *,
    title: str = "北境贸易体系",
    source: dict | None = None,
) -> dict:
    response = await client.post(
        "/api/world/cocreation-sessions",
        json={
            "novel_id": novel_id,
            "title": title,
            "source": source or {"kind": "project"},
            "workflow_preset": "world_core",
            "target_kind": "core_entity",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_page(client: AsyncClient, novel_id: str, title: str) -> str:
    draft = await client.post(
        "/api/world/bible/drafts",
        json={"novel_id": novel_id, "title": title, "page_type": "background"},
    )
    assert draft.status_code == 201, draft.text
    return draft.json()["id"]


async def _append_message(
    client: AsyncClient,
    novel_id: str,
    session_id: str,
    content: str,
    *,
    kind: str = "message",
    action: str | None = None,
) -> dict:
    payload = {"novel_id": novel_id, "content": content, "kind": kind}
    if action is not None:
        payload["action"] = action
    response = await client.post(
        f"/api/world/cocreation-sessions/{session_id}/messages",
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _list_messages(
    client: AsyncClient,
    novel_id: str,
    session_id: str,
    **params,
) -> dict:
    response = await client.get(
        f"/api/world/cocreation-sessions/{session_id}/messages",
        params={"novel_id": novel_id, **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _insert_checkpoint_suggestion(
    db_session: AsyncSession,
    novel_id: str,
    *,
    target_type: str = "world_design_checkpoint",
    status: str = "pending",
    result_ref: dict | None = None,
) -> CreationSuggestion:
    suggestion = CreationSuggestion(
        novel_id=uuid.UUID(novel_id),
        source_module="world",
        review_group="world_adoption",
        target_type=target_type,
        payload_json={"schema_version": "world_design_checkpoint.v1"},
        evidence_refs_json=[],
        risk_level="low",
        status=status,
        result_ref_json=result_ref or {},
    )
    db_session.add(suggestion)
    await db_session.flush()
    return suggestion


class _FakeChatClient:
    provider = "fake-provider"
    model_name = "fake-default-model"

    def __init__(self) -> None:
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return LLMCallResponse(
            content="潮门规则需要一条维护代价。",
            model=request.model,
            provider=self.provider,
        )

    async def close(self) -> None:
        return None


def _install_fake_llm(monkeypatch: pytest.MonkeyPatch) -> _FakeChatClient:
    fake = _FakeChatClient()

    def create_fake(profile):
        fake.model_name = profile.model
        return fake

    monkeypatch.setattr(
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        create_fake,
    )
    return fake


async def _confirm_chat_context(client: AsyncClient, novel_id: str) -> str:
    payload = {
        "novel_id": novel_id,
        "action": "world.generation.chat",
        "task": "共创会话回合",
        "scope": "generation_center",
        "budget_tokens": 0,
    }
    preview = await client.post("/api/evidence/compilation/compile", json=payload)
    assert preview.status_code == 200, preview.text
    confirmed = await client.post(
        "/api/evidence/compilation/confirm",
        json={
            **payload,
            "expected_context_fingerprint": preview.json()["context_fingerprint"],
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    return confirmed.json()["id"]


@pytest.mark.asyncio
async def test_session_crud_source_validation_and_archive(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "会话 CRUD")
    other_novel_id = await _create_project(async_client, "会话 CRUD 邻居")
    page_id = await _create_page(async_client, novel_id, "潮门港")

    session = await _create_session(
        async_client,
        novel_id,
        source={"kind": "world_bible_page", "id": page_id},
    )
    assert session["source_kind"] == "world_bible_page"
    assert session["source_id"] == page_id
    assert session["status"] == "active"
    assert session["checkpoint_round"] == 0

    response = await async_client.post(
        "/api/world/cocreation-sessions",
        json={
            "novel_id": novel_id,
            "source": {"kind": "core_entity", "id": str(uuid.uuid4())},
        },
    )
    assert response.status_code == 404, response.text

    cross_project = await async_client.post(
        "/api/world/cocreation-sessions",
        json={
            "novel_id": other_novel_id,
            "source": {"kind": "world_bible_page", "id": page_id},
        },
    )
    assert cross_project.status_code == 404, cross_project.text

    listed = await async_client.get(
        "/api/world/cocreation-sessions",
        params={"novel_id": novel_id},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == session["id"]

    renamed = await async_client.patch(
        f"/api/world/cocreation-sessions/{session['id']}",
        json={"novel_id": novel_id, "title": "北境第二版"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "北境第二版"

    archived = await async_client.patch(
        f"/api/world/cocreation-sessions/{session['id']}",
        json={"novel_id": novel_id, "archived": True},
    )
    assert archived.status_code == 200, archived.text
    default_list = await async_client.get(
        "/api/world/cocreation-sessions",
        params={"novel_id": novel_id},
    )
    assert default_list.json()["total"] == 0
    with_archived = await async_client.get(
        "/api/world/cocreation-sessions",
        params={"novel_id": novel_id, "include_archived": True},
    )
    assert with_archived.json()["total"] == 1

    other_view = await async_client.get(
        f"/api/world/cocreation-sessions/{session['id']}",
        params={"novel_id": other_novel_id},
    )
    assert other_view.status_code == 404, other_view.text


@pytest.mark.asyncio
async def test_message_pagination_search_and_decision_kind(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "会话消息分页")
    session = await _create_session(async_client, novel_id)

    await _append_message(
        async_client,
        novel_id,
        session["id"],
        "第一条：潮门每天开两次。",
    )
    await _append_message(
        async_client,
        novel_id,
        session["id"],
        "决定：税率保持开放。",
        kind="decision",
    )
    await _append_message(
        async_client,
        novel_id,
        session["id"],
        "补一条成立规则：银币在冬季升值。",
        action="expand",
    )

    invalid = await async_client.post(
        f"/api/world/cocreation-sessions/{session['id']}/messages",
        json={"novel_id": novel_id, "content": "坏动作", "action": "teleport"},
    )
    assert invalid.status_code == 422, invalid.text

    page_one = await _list_messages(
        async_client,
        novel_id,
        session["id"],
        limit=2,
        skip=0,
    )
    assert page_one["total"] == 3
    assert [item["content"][:3] for item in page_one["items"]] == [
        "第一条",
        "决定：",
    ]
    page_two = await _list_messages(
        async_client,
        novel_id,
        session["id"],
        limit=2,
        skip=2,
    )
    assert [item["content"][:3] for item in page_two["items"]] == ["补一条"]
    assert page_two["items"][0]["action"] == "expand"
    assert page_one["items"][1]["kind"] == "decision"

    searched = await _list_messages(
        async_client,
        novel_id,
        session["id"],
        search="银币",
    )
    assert searched["total"] == 1
    assert "银币" in searched["items"][0]["content"]

    detail = await async_client.get(
        f"/api/world/cocreation-sessions/{session['id']}",
        params={"novel_id": novel_id},
    )
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["message_total"] == 3
    assert len(detail_body["messages"]) == 3


@pytest.mark.asyncio
async def test_session_chat_persists_completed_turn_with_confirmation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    account_llm_connection: dict,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_project(async_client, "会话聊天")
    session = await _create_session(async_client, novel_id)
    confirmation_id = await _confirm_chat_context(async_client, novel_id)

    chat = await async_client.post(
        f"/api/world/cocreation-sessions/{session['id']}/chat",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
            "source_context": {"kind": "project"},
            "target": {"kind": "core_entity", "template": "character"},
            "messages": [
                {"role": "user", "content": "帮我补一条潮门维护规则"},
            ],
            "quality_mode": "fast",
            "session_action": "expand",
        },
    )
    assert chat.status_code == 200, chat.text
    assert "潮门" in chat.json()["reply"]
    assert fake.requests, "expected the LLM to be invoked"

    messages = await _list_messages(async_client, novel_id, session["id"])
    assert messages["total"] == 2
    author, assistant = messages["items"]
    assert author["role"] == "author"
    assert author["action"] == "expand"
    assert "维护规则" in author["content"]
    assert author["context_confirmation_id"] == confirmation_id
    assert assistant["role"] == "assistant"
    assert assistant["context_confirmation_id"] == confirmation_id
    assert "潮门" in assistant["content"]
    assert assistant["outcome_suggestion_id"] is None

    pending_suggestions = await async_client.get(
        "/api/world/suggestions",
        params={"novel_id": novel_id, "review_group": "generation_center"},
    )
    assert pending_suggestions.json()["total"] == 0

    unconfirmed = await async_client.post(
        f"/api/world/cocreation-sessions/{session['id']}/chat",
        json={
            "novel_id": novel_id,
            "source_context": {"kind": "project"},
            "target": {"kind": "core_entity", "template": "character"},
            "messages": [
                {"role": "user", "content": "没有确认资料的回合"},
            ],
            "quality_mode": "fast",
        },
    )
    assert unconfirmed.status_code == 400, unconfirmed.text
    after_reject = await _list_messages(async_client, novel_id, session["id"])
    assert after_reject["total"] == 2, "failed turns must not persist half-written rows"


@pytest.mark.asyncio
async def test_checkpoint_pointer_advance_and_drift_keeps_proposal(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = await _create_project(async_client, "checkpoint 指针")
    session = await _create_session(async_client, novel_id)
    first = await _insert_checkpoint_suggestion(db_session, novel_id)
    second = await _insert_checkpoint_suggestion(db_session, novel_id)
    not_checkpoint = await _insert_checkpoint_suggestion(
        db_session,
        novel_id,
        target_type="core_entity_draft",
    )

    advance = await async_client.post(
        f"/api/world/cocreation-sessions/{session['id']}/checkpoint",
        json={
            "novel_id": novel_id,
            "checkpoint_suggestion_id": str(first.id),
            "expected_checkpoint_id": None,
            "round_no": 3,
            "depth": "candidate",
        },
    )
    assert advance.status_code == 200, advance.text
    advanced = advance.json()
    assert advanced["current_checkpoint_id"] == str(first.id)
    assert advanced["checkpoint_round"] == 3
    assert advanced["checkpoint_depth"] == "candidate"

    stale = await async_client.post(
        f"/api/world/cocreation-sessions/{session['id']}/checkpoint",
        json={
            "novel_id": novel_id,
            "checkpoint_suggestion_id": str(second.id),
            "expected_checkpoint_id": None,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "checkpoint_pointer_drift"

    mismatch = await async_client.post(
        f"/api/world/cocreation-sessions/{session['id']}/checkpoint",
        json={
            "novel_id": novel_id,
            "checkpoint_suggestion_id": str(not_checkpoint.id),
            "expected_checkpoint_id": str(first.id),
        },
    )
    assert mismatch.status_code == 409, mismatch.text
    assert mismatch.json()["error"] == "checkpoint_target_mismatch"

    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.status == "pending"
    assert second.status == "pending", "drift must keep the proposal untouched"

    retried = await async_client.post(
        f"/api/world/cocreation-sessions/{session['id']}/checkpoint",
        json={
            "novel_id": novel_id,
            "checkpoint_suggestion_id": str(second.id),
            "expected_checkpoint_id": str(first.id),
        },
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["current_checkpoint_id"] == str(second.id)

    other_novel = await _create_project(async_client, "checkpoint 指针邻居")
    foreign = await async_client.post(
        f"/api/world/cocreation-sessions/{session['id']}/checkpoint",
        json={
            "novel_id": other_novel,
            "checkpoint_suggestion_id": str(second.id),
            "expected_checkpoint_id": str(second.id),
        },
    )
    assert foreign.status_code == 404, foreign.text


@pytest.mark.asyncio
async def test_outcome_state_derivation_from_suggestion_lifecycle(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = await _create_project(async_client, "成果状态推导")
    session = await _create_session(async_client, novel_id)
    pending = await _insert_checkpoint_suggestion(db_session, novel_id)
    adopted = await _insert_checkpoint_suggestion(
        db_session,
        novel_id,
        target_type="core_entity_draft",
        status="accepted",
        result_ref={"type": "core_entity", "id": str(uuid.uuid4())},
    )
    saved_draft = await _insert_checkpoint_suggestion(
        db_session,
        novel_id,
        target_type="world_bible_page_draft",
        status="accepted",
        result_ref={"type": "world_bible_page_draft", "id": str(uuid.uuid4())},
    )
    rejected = await _insert_checkpoint_suggestion(
        db_session,
        novel_id,
        status="rejected",
    )

    for suggestion, content in (
        (pending, "候选一"),
        (adopted, "候选二"),
        (saved_draft, "候选三"),
        (rejected, "候选四"),
    ):
        await _append_message(
            async_client,
            novel_id,
            session["id"],
            content,
        )
        db_session.add(
            WorldCocreationMessage(
                novel_id=uuid.UUID(novel_id),
                session_id=uuid.UUID(session["id"]),
                role="assistant",
                kind="message",
                content=f"{content}的成果",
                outcome_suggestion_id=suggestion.id,
                outcome_kind="candidate",
            )
        )
    await db_session.flush()

    items = (
        await _list_messages(async_client, novel_id, session["id"], limit=100)
    )["items"]
    states = {
        item["content"].removesuffix("的成果"): item["outcome_state"]
        for item in items
        if item["outcome_suggestion_id"]
    }
    assert states["候选一"] == "pending_review"
    assert states["候选二"] == "adopted"
    assert states["候选三"] == "saved_draft"
    assert states["候选四"] == "rejected"

    plain = [
        item
        for item in items
        if item["outcome_suggestion_id"] is None and item["role"] == "assistant"
    ]
    assert plain == []

    author_items = [item for item in items if item["role"] == "author"]
    assert all(item["outcome_state"] is None for item in author_items)


@pytest.mark.asyncio
async def test_record_generation_outcome_binds_task_and_skips_missing_session(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = await _create_project(async_client, "任务成果落库")
    session = await _create_session(async_client, novel_id)
    suggestion = await _insert_checkpoint_suggestion(
        db_session,
        novel_id,
        target_type="world_bible_page_draft",
    )
    task_id = str(uuid.uuid4())
    confirmation_id = str(uuid.uuid4())

    from modules.world.services.worldbuilding.cocreation_session_service import (
        WorldCocreationSessionService,
    )

    await WorldCocreationSessionService().record_generation_outcome(
        db_session,
        novel_id=novel_id,
        session_id=session["id"],
        action="pressure",
        author_content="固定一处日常运转，检查维护中断。",
        task_id=task_id,
        context_confirmation_id=confirmation_id,
        outcome_suggestion_id=str(suggestion.id),
        outcome_label="潮门故障纵切",
    )
    await WorldCocreationSessionService().record_generation_outcome(
        db_session,
        novel_id=novel_id,
        session_id=str(uuid.uuid4()),
        action=None,
        author_content=None,
        task_id=None,
        context_confirmation_id=None,
        outcome_suggestion_id=str(suggestion.id),
        outcome_label="悬空会话",
    )

    items = (
        await _list_messages(async_client, novel_id, session["id"], limit=100)
    )["items"]
    assert len(items) == 2
    author, assistant = items
    assert author["action"] == "pressure"
    assert assistant["task_id"] == task_id
    assert assistant["context_confirmation_id"] == confirmation_id
    assert assistant["outcome_suggestion_id"] == str(suggestion.id)
    assert assistant["outcome_state"] == "pending_review"
    assert "潮门故障纵切" in assistant["content"]
