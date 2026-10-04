"""问世界观与确认资料、项目 owner 的 API 边界回归。

生成中心套件为聚焦生成行为跳过确认预检；此处不跳过，覆盖确认缺失/错配/串项目/
排除来源，以及非 owner 看不到他人项目的问答、引用回开与保存入口。
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.world.models.worldbuilding import CreationSuggestion, WorldBiblePage
from modules.world.tests.helpers import publish_bible_draft
from modules.world.tests.test_world_generation_center_api import (
    _create_llm_project,
    _create_published_page,
    _empty_ask_world_rag,
    _install_fake_llm,
)

pytestmark = pytest.mark.usefixtures("account_llm_connection")

_QUESTION = "世界背景航路"


def _page_ref(page_id: str) -> dict:
    return {
        "kind": "target",
        "target_ref": {"target_type": "world_bible_page", "target_id": page_id},
    }


async def _confirm(
    async_client: AsyncClient,
    novel_id: str,
    action: str = "world.ask",
    *,
    pinned_pages: tuple[str, ...] = (),
    excluded_pages: tuple[str, ...] = (),
) -> str:
    payload = {
        "novel_id": novel_id,
        "action": action,
        "task": _QUESTION,
        "scope": "full",
        "user_note": _QUESTION,
        "include_pending_objects": False,
        "budget_tokens": 12000,
        "pinned_refs": [_page_ref(page_id) for page_id in pinned_pages],
        "excluded_refs": [_page_ref(page_id) for page_id in excluded_pages],
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


async def _publish_page(
    async_client: AsyncClient,
    novel_id: str,
    *,
    title: str,
    text: str,
) -> dict:
    created = await async_client.post(
        "/api/world/bible/drafts",
        json={
            "novel_id": novel_id,
            "title": title,
            "page_type": "background",
            "free_text": text,
            "sections_json": [],
        },
    )
    assert created.status_code == 201, created.text
    published = await publish_bible_draft(async_client, novel_id, created.json()["id"])
    assert published.status_code == 200, published.text
    return published.json()


def _ask_payload(novel_id: str, confirmation_id: str | None = None) -> dict:
    payload = {"novel_id": novel_id, "question": _QUESTION}
    if confirmation_id:
        payload["context_confirmation_id"] = confirmation_id
    return payload


def _model_evidence(request) -> list[dict]:
    content = "\n".join(message.content for message in request.messages)
    start = content.index("<SOURCE_EVIDENCE>\n") + len("<SOURCE_EVIDENCE>\n")
    end = content.index("\n</SOURCE_EVIDENCE>", start)
    return json.loads(content[start:end])


@pytest.mark.asyncio
async def test_ask_world_requires_a_matching_confirmation_before_the_model(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    monkeypatch.setattr(
        "modules.evidence.facade.retrieve_planned_context_evidence",
        _empty_ask_world_rag,
    )
    novel_id = await _create_llm_project(async_client, "问世界确认门")
    await _create_published_page(async_client, novel_id)

    missing = await async_client.post("/api/world/ask-world", json=_ask_payload(novel_id))
    assert missing.status_code == 400
    assert "context_confirmation_id" in missing.text

    other_action = await _confirm(async_client, novel_id, "world.generation.chat")
    mismatched = await async_client.post(
        "/api/world/ask-world",
        json=_ask_payload(novel_id, other_action),
    )
    assert mismatched.status_code == 400
    assert "action mismatch" in mismatched.text

    other_novel_id = await _create_llm_project(async_client, "另一个项目")
    foreign = await _confirm(async_client, other_novel_id)
    crossed = await async_client.post(
        "/api/world/ask-world",
        json=_ask_payload(novel_id, foreign),
    )
    assert crossed.status_code == 400, crossed.text

    assert fake.requests == []
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0


@pytest.mark.asyncio
async def test_ask_world_rejects_a_confirmation_when_the_page_changed_after_review(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    monkeypatch.setattr(
        "modules.evidence.facade.retrieve_planned_context_evidence",
        _empty_ask_world_rag,
    )
    novel_id = await _create_llm_project(async_client, "确认后来源变化")
    page = await _create_published_page(async_client, novel_id)
    confirmation_id = await _confirm(async_client, novel_id, pinned_pages=(page["id"],))

    page_model = await db_session.get(WorldBiblePage, uuid.UUID(page["id"]))
    assert page_model is not None
    page_model.free_text = "作者在确认之后改写了这一页。"
    page_model.version_number += 1
    await db_session.flush()

    response = await async_client.post(
        "/api/world/ask-world",
        json=_ask_payload(novel_id, confirmation_id),
    )

    assert response.status_code == 409, response.text
    assert "AI 参考资料已变化" in response.json()["detail"]
    assert fake.requests == []


@pytest.mark.asyncio
async def test_ask_world_excludes_unconfirmed_pages_from_model_input_and_citations(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    monkeypatch.setattr(
        "modules.evidence.facade.retrieve_planned_context_evidence",
        _empty_ask_world_rag,
    )
    novel_id = await _create_llm_project(async_client, "排除来源不回流")
    kept = await _publish_page(
        async_client,
        novel_id,
        title="航路总览",
        text="帝国在长夜后重建了航路。",
    )
    excluded = await _publish_page(
        async_client,
        novel_id,
        title="航路密档",
        text="航路密档写明北方另有三条秘密航线。",
    )
    confirmation_id = await _confirm(
        async_client,
        novel_id,
        pinned_pages=(kept["id"],),
        excluded_pages=(excluded["id"],),
    )

    response = await async_client.post(
        "/api/world/ask-world",
        json=_ask_payload(novel_id, confirmation_id),
    )

    assert response.status_code == 200, response.text
    result = response.json()
    evidence = _model_evidence(fake.requests[0])
    assert [item["title"] for item in evidence] == ["航路总览"]
    assert "秘密航线" not in json.dumps(evidence, ensure_ascii=False)
    assert {item["page_id"] for item in result["citations"]} == {kept["id"]}
    assert any(
        "未出现在本次确认资料中" in warning
        for warning in result["evidence_trace"].get("warnings", [])
    )


def _principal(account: Account) -> AccountPrincipal:
    return AccountPrincipal(
        account_id=account.id,
        status="active",
        identity_type="email",
        support_code=account.support_code,
    )


@pytest.mark.asyncio
async def test_ask_world_entries_hide_another_owners_project(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    monkeypatch.setattr(
        "modules.evidence.facade.retrieve_planned_context_evidence",
        _empty_ask_world_rag,
    )
    novel_id = await _create_llm_project(async_client, "私有问世界项目")
    page = await _create_published_page(async_client, novel_id)
    confirmation_id = await _confirm(async_client, novel_id, pinned_pages=(page["id"],))
    answered = await async_client.post(
        "/api/world/ask-world",
        json=_ask_payload(novel_id, confirmation_id),
    )
    assert answered.status_code == 200, answered.text
    result = answered.json()
    request_count = len(fake.requests)

    stranger = Account(status="active", support_code="U-ASKOTHER")
    db_session.add(stranger)
    await db_session.flush()
    token = bind_principal(_principal(stranger))
    try:
        asked = await async_client.post(
            "/api/world/ask-world",
            json=_ask_payload(novel_id, confirmation_id),
        )
        opened = await async_client.post(
            "/api/world/ask-world/citations/open",
            json={"novel_id": novel_id, "citation": result["citations"][0]},
        )
        saved = await async_client.post(
            "/api/world/ask-world/suggestions",
            json={
                "novel_id": novel_id,
                **{
                    key: result[key]
                    for key in (
                        "question",
                        "answer",
                        "claims",
                        "uncertainty",
                        "citations",
                        "response_hash",
                    )
                },
            },
        )
    finally:
        reset_principal(token)

    assert (asked.status_code, opened.status_code, saved.status_code) == (404, 404, 404)
    assert len(fake.requests) == request_count
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0
