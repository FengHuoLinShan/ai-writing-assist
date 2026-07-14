from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.schemas import LLMCallResponse
from modules.context.models import ContextSnapshot
from modules.world.models import CoreEntity, CreationSuggestion
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

    async def close(self) -> None:
        return None


async def _create_llm_project(async_client: AsyncClient, title: str) -> dict:
    response = await async_client.post(
        "/api/projects",
        json={
            "title": title,
            "settings": {
                "llm": {
                    "provider_id": "openai-compatible",
                    "api_key": "sk-test-only",
                    "base_url": "https://llm.test/v1",
                    "model": "test-model",
                }
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


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
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        lambda _profile: fake,
    )
    novel_id = (await _create_llm_project(async_client, "Chatbox"))["id"]
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
    request = fake.requests[0]
    assert "世界设定共创搭档" in request.messages[0].content
    assert "不要每轮固定提问" in request.messages[0].content
    assert "不强迫每个对象" in request.messages[0].content
    assert "<AUTHOR_TEMPLATE_INSTRUCTION>" in request.messages[1].content


@pytest.mark.asyncio
async def test_object_draft_chat_returns_actual_world_synopsis_usage(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        lambda _profile: fake,
    )
    novel_id = (await _create_llm_project(async_client, "简介上下文"))["id"]
    draft = await async_client.post(
        "/api/world/bible/drafts",
        json={
            "novel_id": novel_id,
            "title": "世界背景",
            "page_type": "background",
            "free_text": "星海帝国建立于长夜之后。",
        },
    )
    assert draft.status_code == 201, draft.text
    published = await async_client.post(
        f"/api/world/bible/drafts/{draft.json()['id']}/publish",
        params={"novel_id": novel_id},
    )
    assert published.status_code == 200, published.text

    response = await async_client.post(
        "/api/world/object-draft-chat",
        json={
            "novel_id": novel_id,
            "template": "character",
            "messages": [{"role": "user", "content": "设计一个反派"}],
            "include_world_synopsis": True,
        },
    )

    assert response.status_code == 200, response.text
    usage = response.json()["context_usage"]
    assert usage["included"] is True
    assert usage["fallback"] is True
    assert usage["revision_id"] is None
    assert usage["source_hash"]
    assert usage["block_hash"]
    assert usage["context_snapshot_id"]
    snapshot = await db_session.get(
        ContextSnapshot,
        uuid.UUID(usage["context_snapshot_id"]),
    )
    assert snapshot is not None
    assert snapshot.status == "succeeded"
    assert snapshot.compile_options["scope"] == "generation_center"
    assert snapshot.compile_options["retrieval_purpose"] == (
        "world_object_generation"
    )
    assert snapshot.compile_options["include_world_synopsis"] is True
    assert snapshot.section_metadata["world_bible_synopsis"]["retrieval_metadata"][
        "source_hash"
    ] == usage["source_hash"]
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "<WORLD_BIBLE_SYNOPSIS_DATA>" in prompt
    assert "<PROJECT_BACKGROUND_DATA>" in prompt
    assert "星海帝国建立于长夜之后" in prompt


@pytest.mark.asyncio
async def test_generate_object_draft_creates_draft_entity_with_pro_model(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        lambda _profile: fake,
    )
    novel_id = (await _create_llm_project(async_client, "生成草稿"))["id"]

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
    suggestion = body["suggestion"]
    assert suggestion["status"] == "pending"
    assert suggestion["display_state"] == "review"
    assert suggestion["target_type"] == "core_entity_draft"
    assert suggestion["result_ref_json"] == {
        "type": "core_entity_compatibility",
        "id": entity["id"],
        "status": "pending",
    }
    stored_suggestion = await db_session.get(
        CreationSuggestion,
        uuid.UUID(suggestion["id"]),
    )
    assert stored_suggestion is not None
    assert stored_suggestion.source_module == "chatbox"

    confirm_resp = await async_client.post(
        f"/api/world/suggestions/{suggestion['id']}/confirm",
        params={"novel_id": novel_id},
    )
    assert confirm_resp.status_code == 200, confirm_resp.text
    adopted = await async_client.get(
        f"/api/world/entities/{entity['id']}",
        params={"novel_id": novel_id},
    )
    assert adopted.json()["status"] == "canonical"
    assert adopted.json()["approved_by"] == "manual"
    assert adopted.json()["content_json"]["_meta"]["needs_review"] is False
    assert await _entity_count(db_session) == 1
    structured_prompt = "\n".join(
        message.content for message in fake.requests[0].messages
    )
    assert "<AUTHOR_CONVERSATION_JSON>" in structured_prompt
    assert "作者较新的明确选择" in structured_prompt
    assert "不要为满足固定长度而填充" in structured_prompt
    assert "80-180" not in structured_prompt
    assert "只有设计确实存在隐藏层时才填写" in structured_prompt


@pytest.mark.asyncio
async def test_object_suggestion_edit_confirm_route_updates_same_shadow(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        lambda _profile: fake,
    )
    novel_id = (await _create_llm_project(async_client, "编辑后采用建议"))["id"]
    generated = await async_client.post(
        "/api/world/object-drafts/generate",
        json={
            "novel_id": novel_id,
            "template": "character",
            "messages": [{"role": "user", "content": "设计一个旧友型反派"}],
            "quality_mode": "fast",
        },
    )
    body = generated.json()

    decided = await async_client.post(
        f"/api/world/suggestions/{body['suggestion']['id']}/edit-confirm",
        params={"novel_id": novel_id},
        json={"name": "沈无忧", "summary": "作者修改后采用的概要。"},
    )

    assert decided.status_code == 200, decided.text
    assert decided.json()["suggestion_status"] == "accepted"
    stored = await db_session.get(CoreEntity, uuid.UUID(body["entity"]["id"]))
    assert stored is not None
    assert stored.name == "沈无忧"
    assert stored.summary == "作者修改后采用的概要。"
    assert stored.status == "canonical"


@pytest.mark.asyncio
async def test_generate_object_draft_accepts_custom_template_prompt(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        lambda _profile: fake,
    )
    novel_id = (await _create_llm_project(async_client, "自定义模板"))["id"]

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
    assert "必须写清楚誓言" not in fake.requests[0].messages[0].content
    assert "<AUTHOR_TEMPLATE_INSTRUCTION>" in fake.requests[0].messages[1].content


def test_selected_chapter_excerpt_prefers_focus_and_keeps_head_tail_fallback() -> None:
    from modules.world.services.worldbuilding.object_draft_generation_service import (
        ObjectDraftGenerationService,
    )

    content = "开场" + "甲" * 700 + "黑曜钥匙在塔顶裂开" + "乙" * 700 + "结尾"
    focused = ObjectDraftGenerationService._excerpt(
        content,
        limit=300,
        focus_text="设计黑曜钥匙的代价",
    )
    fallback = ObjectDraftGenerationService._excerpt(
        content,
        limit=300,
        focus_text="不存在的对象",
    )

    assert "黑曜钥匙在塔顶裂开" in focused
    assert "开场" in fallback
    assert "结尾" in fallback


def test_generated_object_draft_schema_rejects_unknown_enum_values() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from modules.world.llm_schemas import GeneratedObjectDraftOutput

    with pytest.raises(PydanticValidationError):
        GeneratedObjectDraftOutput(
            name="黑曜钥匙",
            summary="一枚可以打开长夜之门的古老钥匙。",
            importance_level="very_important",
            reveal_level="secret",
        )


@pytest.mark.asyncio
async def test_generate_object_draft_rejects_other_project_chapter(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        lambda _profile: fake,
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


@pytest.mark.asyncio
async def test_generate_object_draft_with_builtin_template_id(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        lambda _profile: fake,
    )
    novel_id = (await _create_llm_project(async_client, "模板ID生成"))["id"]

    resp = await async_client.post(
        "/api/world/object-drafts/generate",
        json={
            "novel_id": novel_id,
            "template_id": "builtin:character",
            "template_version": 1,
            "messages": [{"role": "user", "content": "用人物模板生成"}],
            "quality_mode": "fast",
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    entity = body["entity"]
    assert entity["entity_type"] == "character"
    meta = entity["content_json"]["_meta"]
    assert meta["template"] == "character"
    assert meta["template_id"] == "builtin:character"
    assert meta["template_version"] == 1
    assert meta["template_name"] == "人物"
    rendered_prompt = fake.requests[0].messages[1].content
    assert "会作出选择" in rendered_prompt
    assert "不是属性集合" in rendered_prompt


@pytest.mark.asyncio
async def test_generate_object_draft_rejects_archived_template_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        lambda _profile: fake,
    )
    project_resp = await async_client.post(
        "/api/projects",
        json={"title": "归档模板测试"},
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    template_resp = await async_client.post(
        "/api/world/generation-prompt-templates",
        json={
            "novel_id": novel_id,
            "name": "临时模板",
            "object_template": "custom",
            "prompt_text": "临时提示词",
        },
    )
    assert template_resp.status_code == 201
    template = template_resp.json()

    archive_resp = await async_client.delete(
        f"/api/world/generation-prompt-templates/{template['id']}",
        params={"novel_id": novel_id},
    )
    assert archive_resp.status_code == 204

    resp = await async_client.post(
        "/api/world/object-drafts/generate",
        json={
            "novel_id": novel_id,
            "template_id": template["id"],
            "template_version": template["version_number"],
            "messages": [{"role": "user", "content": "用已归档模板生成"}],
            "quality_mode": "fast",
        },
    )

    assert resp.status_code == 404, resp.text
    assert fake.requests == []
