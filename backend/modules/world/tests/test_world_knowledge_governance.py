"""M5 World 知识治理接线行为测试（ADR-0025）。

覆盖：建议类 blocked 仍存 candidate 但不可采用、返修通过可采用、chat blocked
不返回不安全正文、生成中心旧提案（无回执）采用 fail closed。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models.worldbuilding import CreationSuggestion
from modules.world.schemas import CreationSuggestionCreate
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionQueueService,
)
from modules.world.tests.test_world_generation_center_api import (
    _create_llm_project,
    _create_published_page,
    _empty_ask_world_rag,
    _install_fake_llm,
    _project_source_payload,
)

pytestmark = pytest.mark.usefixtures("account_llm_connection")


@pytest.fixture(autouse=True)
def _skip_generation_confirmation_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """治理行为测试聚焦审查链路；确认预检已在生成中心套件覆盖。"""

    async def skip_preflight(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "modules.world.api._require_generation_confirmation",
        skip_preflight,
    )


@pytest.mark.asyncio
async def test_blocked_suggestion_saved_but_not_adoptable(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.core_entity_names = ["初稿敌手", "返修敌手"]
    fake.audit_verdicts = ["blocked", "blocked"]
    novel_id = await _create_llm_project(async_client, "阻断对象建议")

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=_project_source_payload(novel_id),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    review = body["knowledge_review"]
    assert review["status"] == "blocked"
    assert review["repaired"] is True
    suggestion_id = body["result"]["suggestion"]["id"]
    stored = await db_session.get(CreationSuggestion, uuid.UUID(suggestion_id))
    assert stored is not None
    assert stored.status == "pending"
    assert stored.payload_json["knowledge_review"]["status"] == "blocked"

    accepted = await async_client.post(
        f"/api/world/suggestions/{suggestion_id}/edit-confirm",
        params={"novel_id": novel_id},
        json={"name": "改名采用", "summary": "尝试采用被阻断的建议。"},
    )
    assert accepted.status_code == 400
    assert "知识审查" in str(accepted.json()["detail"])


@pytest.mark.asyncio
async def test_repaired_suggestion_passes_and_adopts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.core_entity_names = ["初稿敌手", "返修敌手"]
    fake.audit_verdicts = ["blocked", "pass"]
    novel_id = await _create_llm_project(async_client, "返修对象建议")

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=_project_source_payload(novel_id),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["knowledge_review"]["status"] == "passed"
    assert body["knowledge_review"]["repaired"] is True
    assert body["result"]["proposal"]["name"] == "返修敌手"

    suggestion_id = body["result"]["suggestion"]["id"]
    accepted = await async_client.post(
        f"/api/world/suggestions/{suggestion_id}/edit-confirm",
        params={"novel_id": novel_id},
        json={"name": "定稿敌手", "summary": "作者修改后采用。"},
    )
    assert accepted.status_code == 200, accepted.text


@pytest.mark.asyncio
async def test_blocked_chat_withholds_unsafe_reply(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.chat_contents = ["主角其实早已死亡，这段是凶手视角的剧透正文。"]
    fake.audit_verdicts = ["blocked"]
    novel_id = await _create_llm_project(async_client, "阻断聊天")

    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=_project_source_payload(novel_id),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["knowledge_review"]["status"] == "blocked"
    assert "剧透" not in body["reply"]
    assert "知识审查未通过" in body["reply"]


@pytest.mark.asyncio
async def test_legacy_generation_center_suggestion_fails_closed(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    queue = SuggestionQueueService()
    suggestion = await queue.create(
        db_session,
        CreationSuggestionCreate(
            novel_id=project_novel_id,
            source_module="world",
            review_group="generation_center",
            target_type="core_entity_draft",
            action_schema="world_generation.core_entity.v1",
            payload_json={
                "entity_type": "concept",
                "name": "旧版本建议",
                "source_refs": [],
            },
        ),
    )
    with pytest.raises(Exception, match="未经知识治理审查"):
        await queue.confirm(db_session, project_novel_id, suggestion.id)


@pytest.mark.asyncio
async def test_blocked_ask_world_returns_no_answer(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.audit_verdicts = ["blocked"]
    monkeypatch.setattr(
        "modules.evidence.facade.retrieve_planned_context_evidence",
        _empty_ask_world_rag,
    )
    novel_id = await _create_llm_project(async_client, "阻断问世界")
    await _create_published_page(async_client, novel_id)

    response = await async_client.post(
        "/api/world/ask-world",
        json={"novel_id": novel_id, "question": "世界背景航路"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["knowledge_review"]["status"] == "blocked"
    assert body["no_answer"] is True
    assert body["claims"] == []
    assert "重建了航路" not in body["uncertainty"]
