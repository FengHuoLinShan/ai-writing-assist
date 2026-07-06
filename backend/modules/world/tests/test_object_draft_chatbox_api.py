from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.schemas import LLMCallResponse
from modules.world.models import CoreEntity
from modules.writing.facade import create_draft_only


class _FakeLLMClient:
    provider = "fake-provider"

    def __init__(self) -> None:
        self.models: list[str] = []
        self.requests = []

    async def generate(self, request):
        self.models.append(request.model)
        self.requests.append(request)
        return LLMCallResponse(
            content="这个反派可以和主角有旧怨，但动机应当自洽。",
            model=request.model,
            provider=self.provider,
        )

    async def generate_structured(self, request, schema, **_kwargs):
        self.models.append(request.model)
        self.requests.append(request)
        return schema(
            name="沈无咎",
            summary="曾经救过主角、后来成为敌人的旧友型反派。",
            public_info="外表温和，掌管一支地下情报组织。",
            hidden_truth="真正目标是逼主角摧毁失控的旧秩序。",
            importance_level="important",
            reveal_level="author_only",
            details={"hook": "旧友反目"},
            character_card={"desire": "重建秩序", "fear": "牺牲失去意义"},
        )


async def _entity_count(db_session: AsyncSession) -> int:
    result = await db_session.execute(select(func.count(CoreEntity.id)))
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_object_draft_chat_does_not_create_entity(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(
        "modules.world.services.object_draft_generation_service."
        "LLMClient.from_project_settings",
        lambda _settings: fake,
    )
    project_resp = await async_client.post("/api/projects", json={"title": "Chatbox"})
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]
    before = await _entity_count(db_session)

    resp = await async_client.post(
        "/api/world/object-draft-chat",
        json={
            "novel_id": novel_id,
            "template": "character",
            "messages": [{"role": "user", "content": "帮我设计一个反派"}],
            "quality_mode": "fast",
        },
    )

    assert resp.status_code == 200, resp.text
    assert "旧怨" in resp.json()["reply"]
    assert fake.models == ["deepseek-v4-flash"]
    assert await _entity_count(db_session) == before


@pytest.mark.asyncio
async def test_generate_object_draft_creates_draft_entity_with_pro_model(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(
        "modules.world.services.object_draft_generation_service."
        "LLMClient.from_project_settings",
        lambda _settings: fake,
    )
    project_resp = await async_client.post("/api/projects", json={"title": "生成草稿"})
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    resp = await async_client.post(
        "/api/world/object-drafts/generate",
        json={
            "novel_id": novel_id,
            "template": "character",
            "messages": [{"role": "user", "content": "他是主角旧友"}],
            "pasted_context": "外部 Chatbox 已确定：反派不是纯恶人。",
            "quality_mode": "pro",
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["quality_mode"] == "pro"
    assert fake.models == ["deepseek-v4-pro"]
    entity = body["entity"]
    assert entity["entity_type"] == "character"
    assert entity["status"] == "draft"
    assert entity["created_by"] == "ai_chatbox"
    assert entity["summary"] == "曾经救过主角、后来成为敌人的旧友型反派。"
    assert entity["content_json"]["character_card"]["desire"] == "重建秩序"
    assert entity["content_json"]["_meta"]["source"] == "chatbox_object_draft"
    assert entity["content_json"]["_meta"]["has_pasted_context"] is True
    structured_prompt = "\n".join(
        message.content for message in fake.requests[0].messages
    )
    assert "summary 字段必填" in structured_prompt
    assert "可直接显示在对象库摘要列" in structured_prompt


@pytest.mark.asyncio
async def test_generate_object_draft_accepts_custom_template_prompt(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(
        "modules.world.services.object_draft_generation_service."
        "LLMClient.from_project_settings",
        lambda _settings: fake,
    )
    project_resp = await async_client.post("/api/projects", json={"title": "自定义模板"})
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    resp = await async_client.post(
        "/api/world/object-drafts/generate",
        json={
            "novel_id": novel_id,
            "template": "custom",
            "template_name": "DND 圣骑士",
            "template_prompt": "必须写清楚誓言、神术、阵营冲突。",
            "messages": [{"role": "user", "content": "设计一个典型圣骑士"}],
            "quality_mode": "fast",
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["entity"]["entity_type"] == "concept"
    meta = body["entity"]["content_json"]["_meta"]
    assert meta["template"] == "custom"
    assert meta["template_name"] == "DND 圣骑士"
    assert meta["has_custom_template_prompt"] is True
    assert "必须写清楚誓言" in fake.requests[0].messages[1].content


@pytest.mark.asyncio
async def test_generate_object_draft_rejects_other_project_chapter(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(
        "modules.world.services.object_draft_generation_service."
        "LLMClient.from_project_settings",
        lambda _settings: fake,
    )
    project_a = await async_client.post("/api/projects", json={"title": "项目 A"})
    project_b = await async_client.post("/api/projects", json={"title": "项目 B"})
    assert project_a.status_code == 201
    assert project_b.status_code == 201
    novel_a = project_a.json()["id"]
    novel_b = project_b.json()["id"]
    await create_draft_only(db_session, novel_b, 1, "他项目章节", "不能被项目 A 使用")
    await db_session.flush()

    resp = await async_client.post(
        "/api/world/object-drafts/generate",
        json={
            "novel_id": novel_a,
            "template": "character",
            "messages": [{"role": "user", "content": "基于章节生成"}],
            "selected_chapter_indices": [1],
            "quality_mode": "fast",
        },
    )

    assert resp.status_code in {400, 422}, resp.text
    assert fake.models == []
