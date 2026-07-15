from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.schemas import LLMCallResponse
from modules.context.models import ContextSnapshot
from modules.world.llm_schemas import (
    GeneratedObjectDraftOutput,
    GeneratedWorldBibleNewPageProposal,
    GeneratedWorldBiblePageProposal,
    GeneratedWorldGenerationChatOutput,
)
from modules.world.models import CoreEntity, CreationSuggestion, WorldBiblePage


class _FakeWorldGenerationClient:
    provider = "fake-provider"
    model_name = "fake-default-model"

    def __init__(self) -> None:
        self.requests = []
        self.error: Exception | None = None
        self.existing_page_type = "background"
        self.existing_page_asset_keys: list[str] = []
        self.existing_page_source_section_keys: list[str | None] = ["S1"]

    async def generate(self, request):
        self.requests.append(request)
        return LLMCallResponse(
            content="这个设定可以更大胆，但需要补足因果连接。",
            model=request.model,
            provider=self.provider,
        )

    async def generate_structured(self, request, schema, **_kwargs):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if schema is GeneratedWorldGenerationChatOutput:
            return schema(reply="这个设定可以更大胆，但需要补足因果连接。")
        if schema is GeneratedObjectDraftOutput:
            return schema(
                name="沈无咎",
                summary="曾经救过主角、后来成为敌人的旧友型反派。",
                public_info="掌管地下情报组织。",
                hidden_truth="目标是逼主角摧毁失控的旧秩序。",
                importance_level="important",
                reveal_level="author_only",
                details={"hook": "旧友反目"},
                character_card={"desire": "重建秩序"},
                review_notes=["其动机依赖旧秩序已经失控。"],
            )
        if schema is GeneratedWorldBiblePageProposal:
            return schema(
                title="长夜后的星海秩序",
                page_type=self.existing_page_type,
                overview="星海帝国不是终结长夜，而是把长夜变成可管理的稀缺资源。",
                sections=[
                    {
                        "source_section_key": source_key,
                        "section_type": "markdown",
                        "title": f"秩序如何运行 {index + 1}",
                        "body_markdown": "帝国用航路配给和黑暗时间税维持统治。",
                    }
                    for index, source_key in enumerate(
                        self.existing_page_source_section_keys
                    )
                ],
                linked_asset_keys=self.existing_page_asset_keys,
                design_rationale="把历史背景改造为能影响行动的机制。",
                review_notes=["需要作者确认黑暗时间税是否成为正式设定。"],
            )
        if schema is GeneratedWorldBibleNewPageProposal:
            return schema(
                title="黑暗时间税",
                page_type="custom",
                overview="船队必须让渡一段可航行时间才能使用帝国航路。",
                sections=[
                    {
                        "section_type": "markdown",
                        "title": "征收与验证",
                        "body_markdown": "税额由航路局的原子钟网验证。",
                    }
                ],
                design_rationale="让帝国权力直接改变旅行和战争的选择。",
            )
        raise AssertionError(f"unexpected schema: {schema}")

    async def close(self) -> None:
        return None


async def _create_llm_project(async_client: AsyncClient, title: str) -> str:
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
    return response.json()["id"]


def _install_fake_llm(monkeypatch: pytest.MonkeyPatch) -> _FakeWorldGenerationClient:
    fake = _FakeWorldGenerationClient()
    monkeypatch.setattr(
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        lambda _profile: fake,
    )
    return fake


async def _create_published_page(
    async_client: AsyncClient,
    novel_id: str,
) -> dict:
    created = await async_client.post(
        "/api/world/bible/drafts",
        json={
            "novel_id": novel_id,
            "title": "世界背景",
            "page_type": "background",
            "free_text": "星海帝国建立于长夜之后。",
            "sections_json": [
                {
                    "section_id": "history",
                    "section_type": "markdown",
                    "title": "历史",
                    "body_markdown": "长夜结束后，帝国重建了航路。",
                    "sort_order": 0,
                    "linked_asset_ref_hashes": [],
                    "projection_policy": "eligible",
                    "sensitivity_hint": "author_safe",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    published = await async_client.post(
        f"/api/world/bible/drafts/{created.json()['id']}/publish",
        params={"novel_id": novel_id},
    )
    assert published.status_code == 200, published.text
    return published.json()


def _project_source_payload(novel_id: str) -> dict:
    return {
        "novel_id": novel_id,
        "source_context": {"kind": "project"},
        "target": {"kind": "core_entity", "template": "character"},
        "messages": [{"role": "user", "content": "帮我设计一个反派"}],
        "quality_mode": "fast",
    }


@pytest.mark.asyncio
async def test_generation_center_chat_is_read_only_and_records_snapshot(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "世界共创聊天")

    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=_project_source_payload(novel_id),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "因果连接" in body["reply"]
    assert body["source_snapshot"]["kind"] == "project"
    assert await db_session.scalar(select(func.count(CoreEntity.id))) == 0
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0
    snapshot_id = body["context_usage"]["context_snapshot_id"]
    snapshot = await db_session.get(ContextSnapshot, uuid.UUID(snapshot_id))
    assert snapshot is not None
    assert snapshot.status == "succeeded"
    assert snapshot.compile_options["scope"] == "generation_center"
    assert snapshot.compile_options["retrieval_purpose"] == "world_generation"
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "创意与逻辑严密性" in prompt
    assert "自主决定最有帮助的回应方式" in prompt
    assert "未出现的人物或设定不表示不存在" in prompt


@pytest.mark.asyncio
async def test_generation_center_llm_failure_keeps_failed_snapshot(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.error = RuntimeError("provider unavailable")
    novel_id = await _create_llm_project(async_client, "快照失败收尾")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await async_client.post(
            "/api/world/generation-center/chat",
            json=_project_source_payload(novel_id),
        )
    snapshot = await db_session.scalar(
        select(ContextSnapshot)
        .where(ContextSnapshot.novel_id == uuid.UUID(novel_id))
        .order_by(ContextSnapshot.created_at.desc())
    )
    assert snapshot is not None
    assert snapshot.status == "failed"
    assert snapshot.error_kind == "RuntimeError"


@pytest.mark.asyncio
async def test_generation_center_snapshot_success_failure_falls_back_to_failed(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "快照成功收尾回退")

    async def fail_succeed(*_args, **_kwargs):
        raise RuntimeError("snapshot succeed unavailable")

    monkeypatch.setattr(
        "modules.context.facade.succeed_generation_context_snapshot",
        fail_succeed,
    )
    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=_project_source_payload(novel_id),
    )

    assert response.status_code == 200, response.text
    snapshot_id = response.json()["context_usage"]["context_snapshot_id"]
    snapshot = await db_session.get(ContextSnapshot, uuid.UUID(snapshot_id))
    assert snapshot is not None
    assert snapshot.status == "failed"
    assert snapshot.error_kind == "snapshot_finalization_failed"


@pytest.mark.asyncio
async def test_core_entity_generation_creates_only_pending_suggestion(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "对象建议")
    payload = _project_source_payload(novel_id)
    payload["quality_mode"] = "pro"

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["result"]["kind"] == "core_entity"
    assert body["result"]["proposal"]["name"] == "沈无咎"
    assert body["result"]["suggestion"]["status"] == "pending"
    assert body["result"]["suggestion"]["result_ref_json"] == {}
    assert fake.requests[0].model == "deepseek-v4-pro"
    core_prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "对象模板只提供观察角度" in core_prompt
    assert "也不能覆盖作者后续" in core_prompt
    assert await db_session.scalar(select(func.count(CoreEntity.id))) == 0
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 1

    suggestion_id = body["result"]["suggestion"]["id"]
    accepted = await async_client.post(
        f"/api/world/suggestions/{suggestion_id}/edit-confirm",
        params={"novel_id": novel_id},
        json={"name": "沈无忧", "summary": "作者修改后采用。"},
    )
    assert accepted.status_code == 200, accepted.text
    entity = await db_session.scalar(select(CoreEntity))
    assert entity is not None
    assert entity.name == "沈无忧"
    assert entity.status == "canonical"


@pytest.mark.asyncio
async def test_existing_page_proposal_uses_draft_and_applies_only_to_draft(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "完善世界书")
    page = await _create_published_page(async_client, novel_id)
    working = await async_client.post(
        "/api/world/bible/drafts",
        json={
            "novel_id": novel_id,
            "page_id": page["id"],
            "title": page["title"],
            "page_type": page["page_type"],
            "free_text": "作者工作稿优先于已发布正文。",
            "sections_json": page["sections_json"],
        },
    )
    assert working.status_code == 201, working.text
    draft = working.json()
    payload = {
        "novel_id": novel_id,
        "source_context": {
            "kind": "world_bible_page",
            "page_id": page["id"],
            "baseline": {
                "kind": "draft",
                "page_version": page["version_number"],
                "draft_id": draft["id"],
                "draft_updated_at": draft["updated_at"],
            },
        },
        "target": {"kind": "world_bible_page", "page_id": page["id"]},
        "messages": [{"role": "user", "content": "把这页改造成可以推动剧情的设定"}],
    }

    generated = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )

    assert generated.status_code == 201, generated.text
    page_prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "作者最新明确的选择、否定和修正优先" in page_prompt
    assert "已被否定或替换的方向不应重新出现" in page_prompt
    result = generated.json()["result"]
    assert result["kind"] == "world_bible_page"
    assert result["proposal"]["operation"] == "replace_existing"
    assert result["proposal"]["baseline"]["draft_id"] == draft["id"]
    assert result["proposal"]["page"]["sections_json"][0]["section_id"] == "history"
    assert (
        result["proposal"]["page"]["sections_json"][0]["projection_policy"] == "eligible"
    )
    assert (
        result["proposal"]["page"]["sections_json"][0]["sensitivity_hint"]
        == "author_safe"
    )

    generic_confirm = await async_client.post(
        f"/api/world/suggestions/{result['suggestion']['id']}/confirm",
        params={"novel_id": novel_id},
    )
    assert generic_confirm.status_code == 400

    edited_page = result["proposal"]["page"]
    edited_page["title"] = "作者编辑后的星海秩序"
    applied = await async_client.post(
        f"/api/world/generation-center/suggestions/{result['suggestion']['id']}/apply-page-draft",
        params={"novel_id": novel_id},
        json={"page": edited_page},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["draft"]["title"] == "作者编辑后的星海秩序"
    canonical = await db_session.get(WorldBiblePage, uuid.UUID(page["id"]))
    assert canonical is not None
    assert canonical.title == "世界背景"
    assert canonical.free_text == "星海帝国建立于长夜之后。"

    repeated = await async_client.post(
        f"/api/world/generation-center/suggestions/{result['suggestion']['id']}/apply-page-draft",
        params={"novel_id": novel_id},
        json={"page": edited_page},
    )
    assert repeated.status_code == 409


@pytest.mark.asyncio
async def test_existing_page_baseline_drift_returns_409(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "基线冲突")
    page = await _create_published_page(async_client, novel_id)
    payload = {
        "novel_id": novel_id,
        "source_context": {
            "kind": "world_bible_page",
            "page_id": page["id"],
            "baseline": {
                "kind": "published",
                "page_version": page["version_number"],
            },
        },
        "target": {"kind": "world_bible_page", "page_id": page["id"]},
        "messages": [{"role": "user", "content": "重构当前页"}],
    }
    generated = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )
    assert generated.status_code == 201, generated.text
    result = generated.json()["result"]

    created_draft = await async_client.post(
        "/api/world/bible/drafts",
        json={
            "novel_id": novel_id,
            "page_id": page["id"],
            "title": page["title"],
            "page_type": page["page_type"],
            "free_text": "作者在生成后新增的工作稿。",
            "sections_json": page["sections_json"],
        },
    )
    assert created_draft.status_code == 201, created_draft.text

    applied = await async_client.post(
        f"/api/world/generation-center/suggestions/{result['suggestion']['id']}/apply-page-draft",
        params={"novel_id": novel_id},
        json={},
    )
    assert applied.status_code == 409, applied.text


@pytest.mark.asyncio
async def test_world_bible_page_source_requires_explicit_baseline(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "缺少来源基线")
    page = await _create_published_page(async_client, novel_id)

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            "novel_id": novel_id,
            "source_context": {
                "kind": "world_bible_page",
                "page_id": page["id"],
            },
            "target": {"kind": "world_bible_page", "page_id": page["id"]},
            "messages": [{"role": "user", "content": "重构当前页"}],
        },
    )

    assert response.status_code == 422, response.text
    assert fake.requests == []


@pytest.mark.asyncio
async def test_published_source_baseline_rejects_new_working_draft_before_llm(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "已发布来源冲突")
    page = await _create_published_page(async_client, novel_id)
    draft = await async_client.post(
        "/api/world/bible/drafts",
        json={
            "novel_id": novel_id,
            "page_id": page["id"],
            "title": page["title"],
            "page_type": page["page_type"],
            "free_text": "作者已创建新工作稿。",
            "sections_json": page["sections_json"],
        },
    )
    assert draft.status_code == 201, draft.text

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            "novel_id": novel_id,
            "source_context": {
                "kind": "world_bible_page",
                "page_id": page["id"],
                "baseline": {
                    "kind": "published",
                    "page_version": page["version_number"],
                },
            },
            "target": {"kind": "world_bible_page", "page_id": page["id"]},
            "messages": [{"role": "user", "content": "重构当前页"}],
        },
    )

    assert response.status_code == 409, response.text
    assert fake.requests == []


@pytest.mark.asyncio
async def test_new_page_target_creates_unpublished_working_draft(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "新页提案")
    generated = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            "novel_id": novel_id,
            "source_context": {"kind": "project"},
            "target": {"kind": "world_bible_new_page", "page_type": "custom"},
            "messages": [{"role": "user", "content": "设计一种与航行相关的时间税"}],
        },
    )
    assert generated.status_code == 201, generated.text
    new_page_prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "作者最新明确的选择、否定和修正优先" in new_page_prompt
    assert "未出现不表示不存在" in new_page_prompt
    result = generated.json()["result"]
    assert result["kind"] == "world_bible_new_page"
    assert result["proposal"]["operation"] == "create_new"
    assert result["proposal"]["page"]["sections_json"][0]["section_id"].startswith("ai-")

    applied = await async_client.post(
        f"/api/world/generation-center/suggestions/{result['suggestion']['id']}/apply-page-draft",
        params={"novel_id": novel_id},
        json={},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["draft"]["page_id"] is None
    assert applied.json()["draft"]["title"] == "黑暗时间税"
    assert await db_session.scalar(select(func.count(WorldBiblePage.id))) == 0


@pytest.mark.asyncio
async def test_new_page_target_requires_author_selected_page_type(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_llm_project(async_client, "缺少新页类别")
    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            "novel_id": novel_id,
            "source_context": {"kind": "project"},
            "target": {"kind": "world_bible_new_page"},
            "messages": [{"role": "user", "content": "创建新页"}],
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_new_page_target_rejects_unknown_author_selected_page_type_before_llm(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "无效新页类别")

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            "novel_id": novel_id,
            "source_context": {"kind": "project"},
            "target": {
                "kind": "world_bible_new_page",
                "page_type": "not-a-page-type",
            },
            "messages": [{"role": "user", "content": "创建新页"}],
        },
    )

    assert response.status_code == 400, response.text
    assert "Unknown World Bible page type" in response.json()["detail"]
    assert fake.requests == []


@pytest.mark.asyncio
async def test_existing_page_new_section_uses_author_only_projection_defaults(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.existing_page_source_section_keys = [None]
    novel_id = await _create_llm_project(async_client, "现有页新章节投影")
    page = await _create_published_page(async_client, novel_id)

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            "novel_id": novel_id,
            "source_context": {
                "kind": "world_bible_page",
                "page_id": page["id"],
                "baseline": {
                    "kind": "published",
                    "page_version": page["version_number"],
                },
            },
            "target": {"kind": "world_bible_page", "page_id": page["id"]},
            "messages": [{"role": "user", "content": "增加一个全新章节"}],
        },
    )

    assert response.status_code == 201, response.text
    section = response.json()["result"]["proposal"]["page"]["sections_json"][0]
    assert section["section_id"].startswith("ai-")
    assert section["projection_policy"] == "excluded"
    assert section["sensitivity_hint"] == "author_only"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_section_keys", "message"),
    [
        (["S99"], "Unknown source section key"),
        (["S1", "S1"], "Duplicate source section key"),
    ],
)
async def test_existing_page_rejects_invalid_source_section_keys(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    source_section_keys: list[str | None],
    message: str,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.existing_page_source_section_keys = source_section_keys
    novel_id = await _create_llm_project(async_client, "无效来源章节")
    page = await _create_published_page(async_client, novel_id)

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            "novel_id": novel_id,
            "source_context": {
                "kind": "world_bible_page",
                "page_id": page["id"],
                "baseline": {
                    "kind": "published",
                    "page_version": page["version_number"],
                },
            },
            "target": {"kind": "world_bible_page", "page_id": page["id"]},
            "messages": [{"role": "user", "content": "重构当前页"}],
        },
    )

    assert response.status_code == 400, response.text
    assert message in response.json()["detail"]
    assert len(fake.requests) == 1
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0


@pytest.mark.asyncio
async def test_selected_asset_resolution_is_not_limited_by_background_top_k(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "精确资产解析")
    nid = uuid.UUID(novel_id)
    common_assets = [
        CoreEntity(
            novel_id=nid,
            entity_type="item",
            name=f"高优先级资产 {index}",
            summary="用于填充背景聚合上限。",
            importance=1.0,
            status="canonical",
        )
        for index in range(240)
    ]
    selected = CoreEntity(
        novel_id=nid,
        entity_type="item",
        name="聚合上限之外的作者显式资产",
        summary="必须按 ID 精确解析，不得因 Top-K 丢失。",
        importance=0.0,
        status="canonical",
    )
    db_session.add_all([*common_assets, selected])
    await db_session.flush()

    payload = _project_source_payload(novel_id)
    payload["selected_asset_refs"] = [
        {
            "type": "core_entity",
            "id": str(selected.id),
            "target_path": "public_info",
        }
    ]
    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=payload,
    )

    assert response.status_code == 200, response.text
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert selected.name in prompt
    assert '"target_path": "public_info"' in prompt


@pytest.mark.asyncio
async def test_selected_character_asset_is_sent_to_character_context_loader(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "人物资产分流")
    character = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type="character",
        name="章序使",
        summary="一名被显式选中的人物。",
        status="canonical",
    )
    db_session.add(character)
    await db_session.flush()
    captured: dict[str, object] = {}

    async def capture_background(
        _db: AsyncSession,
        **kwargs: object,
    ) -> dict[str, object]:
        captured.update(kwargs)
        return {"rendered_context": "", "context_usage": None}

    monkeypatch.setattr(
        "modules.world.api._world_generation_service._generation_background_provider",
        capture_background,
    )
    payload = _project_source_payload(novel_id)
    payload["selected_asset_refs"] = [{"type": "core_entity", "id": str(character.id)}]
    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert captured["character_ids"] == [str(character.id)]
    assert captured["entity_ids"] == []
    assert len(fake.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    ["scene_id", "thread_ids", "character_ids", "entity_ids"],
)
async def test_explicit_context_ids_fail_closed_before_llm(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, f"无效显式上下文 {field}")
    payload = _project_source_payload(novel_id)
    missing_id = str(uuid.uuid4())
    payload[field] = missing_id if field == "scene_id" else [missing_id]

    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=payload,
    )

    assert response.status_code in {400, 404}, response.text
    assert fake.requests == []


@pytest.mark.asyncio
async def test_generation_center_rejects_cross_project_page_and_asset_refs(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    source_novel_id = await _create_llm_project(async_client, "来源项目")
    target_novel_id = await _create_llm_project(async_client, "目标项目")
    source_page = await _create_published_page(async_client, source_novel_id)
    source_asset = CoreEntity(
        novel_id=uuid.UUID(source_novel_id),
        entity_type="item",
        name="他项目信物",
        summary="不得被另一项目引用。",
        status="canonical",
    )
    db_session.add(source_asset)
    await db_session.flush()

    page_response = await async_client.post(
        "/api/world/generation-center/chat",
        json={
            "novel_id": target_novel_id,
            "source_context": {
                "kind": "world_bible_page",
                "page_id": source_page["id"],
                "baseline": {
                    "kind": "published",
                    "page_version": source_page["version_number"],
                },
            },
            "target": {"kind": "core_entity", "template": "none"},
            "messages": [{"role": "user", "content": "跨项目页面"}],
        },
    )
    assert page_response.status_code == 404, page_response.text

    asset_payload = _project_source_payload(target_novel_id)
    asset_payload["selected_asset_refs"] = [
        {"type": "core_entity", "id": str(source_asset.id)}
    ]
    asset_response = await async_client.post(
        "/api/world/generation-center/chat",
        json=asset_payload,
    )
    assert asset_response.status_code == 400, asset_response.text
    assert fake.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("page_type", "asset_keys", "message"),
    [
        ("unknown-type", [], "Unknown World Bible page type"),
        ("background", ["A99"], "Unknown asset reference key"),
    ],
)
async def test_page_generation_rejects_unknown_category_or_asset_key(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    page_type: str,
    asset_keys: list[str],
    message: str,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.existing_page_type = page_type
    fake.existing_page_asset_keys = asset_keys
    novel_id = await _create_llm_project(async_client, "无效页面输出")
    page = await _create_published_page(async_client, novel_id)

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            "novel_id": novel_id,
            "source_context": {
                "kind": "world_bible_page",
                "page_id": page["id"],
                "baseline": {
                    "kind": "published",
                    "page_version": page["version_number"],
                },
            },
            "target": {"kind": "world_bible_page", "page_id": page["id"]},
            "messages": [{"role": "user", "content": "重构当前页"}],
        },
    )

    assert response.status_code == 400
    assert message in response.json()["detail"]
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0


@pytest.mark.asyncio
async def test_source_target_page_mismatch_is_rejected_before_llm(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "目标错配")
    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            "novel_id": novel_id,
            "source_context": {
                "kind": "world_bible_page",
                "page_id": str(uuid.uuid4()),
            },
            "target": {
                "kind": "world_bible_page",
                "page_id": str(uuid.uuid4()),
            },
            "messages": [{"role": "user", "content": "重构"}],
        },
    )
    assert response.status_code == 422
    assert fake.requests == []


@pytest.mark.asyncio
async def test_removed_world_ai_routes_are_not_registered(
    async_client: AsyncClient,
) -> None:
    checks = [
        ("/api/world/object-draft-chat", {}),
        ("/api/world/object-drafts/generate", {}),
        (f"/api/world/bible/pages/{uuid.uuid4()}/ai-generate", {}),
        (f"/api/world/suggestions/{uuid.uuid4()}/apply-to-world-bible-draft", {}),
    ]
    for path, payload in checks:
        response = await async_client.post(path, json=payload)
        assert response.status_code == 404, (path, response.text)
