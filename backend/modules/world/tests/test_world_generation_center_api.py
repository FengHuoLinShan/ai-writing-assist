from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from inspect import isawaitable
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.schemas import LLMCallResponse
from infrastructure.tasks.models import AsyncTask
from modules.evidence.compilation.models import ContextSnapshot
from modules.evidence.contracts import StructureContextBundle
from modules.project.models import Project
from modules.story.outline_state.models import Scene
from modules.world.llm_schemas import (
    GeneratedAskWorldOutput,
    GeneratedObjectDraftOutput,
    GeneratedWorldBibleNewPageProposal,
    GeneratedWorldBiblePageProposal,
    GeneratedWorldGenerationChatOutput,
    GeneratedWorldGenerationConvergenceOutput,
    GeneratedWorldGenerationDecisionAudit,
    GeneratedWorldGenerationDecisionState,
    GeneratedWorldGenerationExplorationOutput,
    GeneratedWorldSemanticInspectionOutput,
)
from modules.world.models import (
    CharacterKnowledge,
    ConflictCheckQueueItem,
    CoreEntity,
    CreationSuggestion,
    WorldBiblePage,
    WorldBiblePageDraft,
)
from modules.world.tests.helpers import publish_bible_draft

pytestmark = pytest.mark.usefixtures("account_llm_connection")


class _FakeWorldGenerationClient:
    provider = "fake-provider"
    model_name = "fake-default-model"

    def __init__(self) -> None:
        self.requests = []
        self.error: Exception | None = None
        self.before_generate = None
        self.profile = None
        self.chat_contents = ["这个设定可以更大胆，但需要补足因果连接。"]
        self.existing_page_type = "background"
        self.existing_page_asset_keys: list[str] = []
        self.existing_page_source_section_keys: list[str | None] = ["S1"]
        self.core_entity_name = "沈无咎"
        self.core_entity_names: list[str] = []
        self.convergence_drop_last = False
        self.world_core_factory = None
        self.exploration_target_count = 3
        self.ask_world_answer = "现有证据显示帝国在长夜后重建航路。"
        self.ask_world_uncertainty = "当前只核对了命中的世界书页面。"
        self.semantic_findings = [
            {
                "author_action": "needs_decision",
                "finding_type": "open_question",
                "summary": "开放税率被写成唯一事实",
                "evidence": "页面同时保留待定标记与固定三成税率。",
                "location": "历史分区",
                "next_step": "由作者决定税率是否继续开放，然后重检当前页。",
            }
        ]
        self.source_revision = False
        self.decision_audits: list[GeneratedWorldGenerationDecisionAudit] = []
        self.decision_state = GeneratedWorldGenerationDecisionState(
            current_author_goal="收束作者当前选择的世界对象",
            confirmed_requirements=["保留作者最后确认的方向"],
            supported_developments=[],
            rejected_elements=[],
            forbidden_exact_terms=[],
            unresolved_choices=[],
            naming_policy="allowed",
            confidence=1.0,
        )

    async def generate(self, request):
        if self.before_generate is not None:
            hook_result = self.before_generate()
            if isawaitable(hook_result):
                await hook_result
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return LLMCallResponse(
            content=self.chat_contents.pop(0),
            model=request.model,
            provider=self.provider,
        )

    async def generate_structured(self, request, schema, **_kwargs):
        if self.before_generate is not None:
            hook_result = self.before_generate()
            if isawaitable(hook_result):
                await hook_result
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if schema is GeneratedWorldGenerationChatOutput:
            return schema(reply="这个设定可以更大胆，但需要补足因果连接。")
        if schema is GeneratedWorldGenerationDecisionState:
            return self.decision_state
        if schema is GeneratedWorldGenerationDecisionAudit:
            if self.decision_audits:
                return self.decision_audits.pop(0)
            return schema(verdict="pass", violations=[])
        if schema is GeneratedWorldGenerationConvergenceOutput:
            keys = self._convergence_source_keys(request)
            if self.convergence_drop_last:
                keys = keys[:-1]
            world_core = (
                self.world_core_factory(keys) if self.world_core_factory else None
            )
            request_text = "\n".join(message.content for message in request.messages)
            external_packet = (
                "EXTERNAL_PACKET_CONTRACT" in request_text
                or '"external_disposition"' in request_text
            )
            return schema(
                detail_count_before_grouping=len(keys),
                detail_count_after_deduplication=len(keys),
                retained_detail_count=0,
                decision_cards=(
                    [
                        {
                            "title": "当前需要作者决定的共同边界",
                            "common_ground": ["材料都围绕同一轮世界设定展开。"],
                            "items": (
                                [
                                    {
                                        "text": atom["title"],
                                        "suggested_disposition": "include",
                                        "world_core_rule_key": atom["rule_key"],
                                        "external_disposition": (
                                            "repair" if external_packet else None
                                        ),
                                    }
                                    for atom in world_core["rule_atoms"]
                                ]
                                if world_core
                                else [
                                    {
                                        "text": (
                                            "保留已经形成的制度骨架，具体数字继续开放。"
                                        ),
                                        "suggested_disposition": "include",
                                        "external_disposition": (
                                            "repair" if external_packet else None
                                        ),
                                    }
                                ]
                            ),
                            "dependencies": [],
                            "affected_targets": ["current_world_target"],
                            "source_keys": keys,
                            "why_now": "继续增加同级候选前需要先确认这一边界。",
                        }
                    ]
                    if keys
                    else []
                ),
                retained_source_keys=[],
                shared_source_keys=[],
                next_boundary="只有新材料会改变人物选择或采用判断时再继续扩展。",
                world_core=world_core,
            )
        if schema is GeneratedWorldGenerationExplorationOutput:
            keys = self._convergence_source_keys(request)
            labels = ["边境道路", "地方税契", "夜航邮驿"]
            return schema(
                targets=[
                    {
                        "title": labels[index],
                        "gap": f"{labels[index]}尚未说明如何受当前制度约束。",
                        "why_it_matters": "它会改变普通人的移动与资源选择。",
                        "author_boundary": "具体执行者和代价仍由作者决定。",
                        "reverse_check_focus": "来源页是否需要补充这条制度后果。",
                        "source_keys": keys[:1],
                    }
                    for index in range(self.exploration_target_count)
                ],
                stop_reason="本次只到一个相邻世界书页，不继续下一跳。",
            )
        if schema is GeneratedWorldSemanticInspectionOutput:
            keys = self._convergence_source_keys(request)
            return schema(
                findings=[
                    {**finding, "source_keys": keys[:1]}
                    for finding in self.semantic_findings
                ]
            )
        if schema is GeneratedAskWorldOutput:
            content = "\n".join(message.content for message in request.messages)
            start = content.index("<SOURCE_EVIDENCE>\n") + len("<SOURCE_EVIDENCE>\n")
            end = content.index("\n</SOURCE_EVIDENCE>", start)
            evidence = json.loads(content[start:end])
            return schema(
                answer=self.ask_world_answer,
                claims=[
                    {
                        "text": "帝国在长夜后重建了航路。",
                        "citation_keys": [evidence[0]["citation_key"]],
                    }
                ],
                uncertainty=self.ask_world_uncertainty,
                no_answer=False,
            )
        if schema is GeneratedObjectDraftOutput:
            return schema(
                name=(
                    self.core_entity_names.pop(0)
                    if self.core_entity_names
                    else self.core_entity_name
                ),
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
                source_revision=(
                    {
                        "title": "世界背景",
                        "page_type": "background",
                        "overview": "星海帝国建立于长夜之后，并以地方税契约束边境航路。",
                        "sections": [
                            {
                                "source_section_key": "S1",
                                "section_type": "markdown",
                                "title": "历史",
                                "body_markdown": (
                                    "长夜结束后，帝国重建航路并授权地方征收时间税。"
                                ),
                            }
                        ],
                        "design_rationale": "新页给出了会改变来源页解释的制度后果。",
                        "review_notes": ["来源页修订仍需作者单独审阅。"],
                    }
                    if self.source_revision
                    else None
                ),
            )
        raise AssertionError(f"unexpected schema: {schema}")

    @staticmethod
    def _convergence_source_keys(request) -> list[str]:
        content = "\n".join(message.content for message in request.messages)
        if "<SOURCE_MANIFEST" in content:
            start = content.index("\n", content.index("<SOURCE_MANIFEST")) + 1
            end = content.index("\n</SOURCE_MANIFEST>", start)
            return [item["key"] for item in json.loads(content[start:end])]
        start = content.index("\n", content.index("<MAP_RESULTS>")) + 1
        end = content.index("\n</MAP_RESULTS>", start)
        return [
            key for item in json.loads(content[start:end]) for key in item["source_keys"]
        ]

    async def close(self) -> None:
        return None


async def _create_llm_project(async_client: AsyncClient, title: str) -> str:
    response = await async_client.post(
        "/api/projects",
        json={"title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _install_fake_llm(monkeypatch: pytest.MonkeyPatch) -> _FakeWorldGenerationClient:
    fake = _FakeWorldGenerationClient()

    def create_fake(profile):
        fake.profile = profile
        fake.model_name = profile.model
        return fake

    monkeypatch.setattr(
        "modules.project.llm_runtime.LLMClient.from_resolved_profile",
        create_fake,
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
    published = await publish_bible_draft(
        async_client,
        novel_id,
        created.json()["id"],
    )
    assert published.status_code == 200, published.text
    return published.json()


async def _empty_ask_world_rag(
    _db,
    *,
    novel_id: str,
    task: str,
    **_kwargs,
) -> StructureContextBundle:
    return StructureContextBundle(
        novel_id=novel_id,
        task=task,
        scope="full",
        rag_chunks=[],
        retrieval_trace={},
    )


def _project_source_payload(novel_id: str) -> dict:
    return {
        "novel_id": novel_id,
        "source_context": {"kind": "project"},
        "target": {"kind": "core_entity", "template": "character"},
        "messages": [{"role": "user", "content": "帮我设计一个反派"}],
        "quality_mode": "fast",
    }


def _valid_world_core(keys: list[str]) -> dict:
    conversation_keys = [key for key in keys if key.startswith("conversation:")]
    author_keys = [conversation_keys[index] for index in (0, 2, 3)]
    atoms = [
        {
            "rule_key": f"rule_{index}",
            "title": title,
            "source_keys": [author_keys[(index - 1) % 2]],
            "can": "城市可以借潮汐输送货物。",
            "cannot": "城市不能绕过潮汐窗口连续运输。",
            "cost": "每次通行都消耗维护配额。",
            "failure": "维护中断会令街区断供。",
            "maintenance": "潮门工每日校准闸门。",
        }
        for index, title in enumerate(("潮门", "维护配额", "断供边界"), start=1)
    ]
    return {
        "author_seeds": [
            {"source_key": author_keys[0], "disposition": "experience_promise"},
            {"source_key": author_keys[1], "disposition": "included"},
            {"source_key": author_keys[2], "disposition": "rejected"},
        ],
        "rule_atoms": atoms,
        "blocking_contradictions": [],
        "vertical_slice": {
            "rule_key": "rule_1",
            "daily_consequence": "居民每日按潮门时刻表通勤和领粮。",
            "failure_consequence": "闸门失准七日后，居民必须在断供和违规夜航之间选择。",
        },
    }


def _page_new_target_payload(novel_id: str, page: dict) -> dict:
    return {
        "novel_id": novel_id,
        "source_context": {
            "kind": "world_bible_page",
            "page_id": page["id"],
            "baseline": {
                "kind": "published",
                "page_version": page["version_number"],
            },
        },
        "target": {"kind": "world_bible_new_page", "page_type": "custom"},
        "messages": [{"role": "user", "content": "只找一个会改变人物选择的相邻缺口"}],
        "quality_mode": "fast",
    }


@pytest.mark.asyncio
async def test_generation_center_chat_is_read_only_and_records_snapshot(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    account_llm_connection: dict,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "世界共创聊天")

    def assert_provider_checkpoint() -> None:
        assert db_session.in_transaction() is False

    fake.before_generate = assert_provider_checkpoint

    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=_project_source_payload(novel_id),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "因果连接" in body["reply"]
    assert body["model"] == account_llm_connection["model"]
    assert body["source_snapshot"]["kind"] == "project"
    assert await db_session.scalar(select(func.count(CoreEntity.id))) == 0
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0
    assert await db_session.scalar(select(func.count(Scene.id))) == 0
    snapshot_id = body["context_usage"]["context_snapshot_id"]
    snapshot = await db_session.get(ContextSnapshot, uuid.UUID(snapshot_id))
    assert snapshot is not None
    assert snapshot.status == "succeeded"
    assert snapshot.model == account_llm_connection["model"]
    assert snapshot.compile_options["scope"] == "generation_center"
    assert snapshot.compile_options["retrieval_purpose"] == "world_generation"
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "创意与逻辑严密性" in prompt
    assert "自主决定最有帮助的回应方式" in prompt
    assert "先完成当前最小有用动作" in prompt
    assert "三至七条真正决定构想能否成立的条件" in prompt
    assert "一个普通人物在普通一天" in prompt
    assert "真正阻断方向时最多问一个问题" in prompt
    assert "不能以\n“最低充分”为由暗中缩短请求" in prompt
    assert "只固定一组“地点或制度载体" in prompt
    assert "核心前提、\n叙事读法、基调与读者承诺" in prompt
    assert "转到现有“故事总览”" in prompt
    assert (
        "只有已经落到\n具体人物选择、事件变化或场景行动时，"
        "才建议进入 Scene 规划" in prompt
    )
    assert "改写\n故事总览（StoryOutline）" in prompt
    assert "未出现的人物或设定不表示不存在" in prompt
    assert "不要复用其中的名称、例子、设定或结论" in prompt
    assert "不要输出 JSON" in prompt
    assert fake.requests[0].response_format is None
    assert fake.requests[0].model == account_llm_connection["model"]
    assert fake.profile is not None
    assert fake.profile.timeout == 1800


@pytest.mark.asyncio
async def test_generation_center_chat_rejects_selected_chapter_drift_after_model(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world import api as world_api

    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "聊天期间章节变化")
    calls = 0

    async def drifting_chapters(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return [
            {
                "chapter_index": 1,
                "title": "第一章",
                "excerpt": (
                    "模型调用前的章节内容" if calls == 1 else "模型调用后的章节内容"
                ),
            }
        ]

    monkeypatch.setattr(
        world_api._world_generation_service,
        "_load_selected_chapters",
        drifting_chapters,
    )
    payload = _project_source_payload(novel_id)
    payload["selected_chapter_indices"] = [1]

    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=payload,
    )

    assert response.status_code == 409, response.text
    assert calls == 2
    assert len(fake.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("author_message", "pasted_context"),
    [
        ("请完整完善整个道路制度，并准备它作为首部小说的主舞台。", None),
        (
            "不要继续补同级制度；固定一个街区和一群通勤者，推演普通日、七日故障与历史反馈。",
            "已有道路重排规则、维护制度、配给制度、职业分工、家庭负担与行政争议，但没有共享同一地点和时间窗口的实例。",
        ),
    ],
)
async def test_chat_prompt_preserves_explicit_scope_and_one_vertical_slice(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    author_message: str,
    pasted_context: str | None,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "最低充分创作回放")
    payload = _project_source_payload(novel_id)
    payload["target"] = {"kind": "core_entity", "template": "none"}
    payload["messages"] = [{"role": "user", "content": author_message}]
    payload["pasted_context"] = pasted_context

    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=payload,
    )

    assert response.status_code == 200, response.text
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert author_message in prompt
    if pasted_context:
        assert pasted_context in prompt
    assert "作者明确要求完整完善整个制度" in prompt
    assert "保持这组锚点" in prompt
    assert "不要展开未选的平行地点、组织或人物" in prompt
    assert await db_session.scalar(select(func.count(CoreEntity.id))) == 0
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0
    assert await db_session.scalar(select(func.count(Scene.id))) == 0


@pytest.mark.asyncio
async def test_generation_center_convergence_is_complete_and_writes_no_assets(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    account_llm_connection: dict,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "只读收束")
    payload = _project_source_payload(novel_id)
    payload["messages"] = [
        {"role": "user", "content": "保留制度骨架，数字先不要确定。"},
        {"role": "assistant", "content": "可以把税率设为三成。"},
    ]
    payload["excluded_message_count"] = 3

    response = await async_client.post(
        "/api/world/generation-center/convergence",
        json=payload,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coverage"]["complete"] is True
    assert body["coverage"]["source_count"] >= 2
    assert body["coverage"]["excluded_message_count"] == 3
    assert body["coverage"]["missing_source_keys"] == []
    assert len(body["decision_cards"]) == 1
    assert body["decision_cards"][0]["items"][0]["suggested_disposition"] == ("include")
    assert {item["key"] for item in body["manifest"]} == set(
        body["coverage"]["covered_source_keys"]
    )
    snapshot = await db_session.get(
        ContextSnapshot,
        uuid.UUID(body["context_usage"]["context_snapshot_id"]),
    )
    assert snapshot is not None
    assert snapshot.operation == "world.generation.convergence"
    assert snapshot.prompt_name == "world.generation.convergence.map"
    assert snapshot.compile_options["scope"] == "generation_center"
    assert snapshot.compile_options["retrieval_purpose"] == "world_generation"
    assert snapshot.model == account_llm_connection["model"]
    assert body["model"] == account_llm_connection["model"]
    assert fake.requests[0].model == account_llm_connection["model"]
    assert await db_session.scalar(select(func.count(CoreEntity.id))) == 0
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "不负责继续发散、采用设定或创建项目资产" in prompt
    assert "不能冒充本地对象 ID 或本地校验回执" in prompt
    assert "SOURCE_MANIFEST" in prompt


@pytest.mark.asyncio
async def test_world_core_convergence_covers_author_seeds_and_returns_handoff(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.world_core_factory = _valid_world_core
    novel_id = await _create_llm_project(async_client, "World Core 收束")
    payload = _project_source_payload(novel_id)
    payload.update(
        {
            "workflow_preset": "world_core",
            "target": {"kind": "core_entity", "template": "none"},
            "messages": [
                {"role": "user", "content": "潮汐决定城市道路。"},
                {"role": "assistant", "content": "可以把所有交通都改成夜航。"},
                {"role": "user", "content": "修正：只有跨区通道受潮汐影响。"},
                {"role": "user", "content": "否定夜航垄断，保留白天步行。"},
            ],
        }
    )

    response = await async_client.post(
        "/api/world/generation-center/convergence", json=payload
    )

    assert response.status_code == 200, response.text
    body = response.json()
    handoff = body["world_core"]
    assert handoff["ready_for_handoff"] is True
    assert handoff["issues"] == []
    assert handoff["rule_count"] == 3
    assert len(handoff["author_seed_source_keys"]) == 3
    assert handoff["snapshot"]["author_seeds"][2]["disposition"] == "rejected"
    assistant_key = next(
        item["key"]
        for item in body["manifest"]
        if item["source_ref"]["source_type"] == "assistant_message"
    )
    assert assistant_key not in handoff["author_seed_source_keys"]
    assert all(
        item["world_core_rule_key"]
        for card in body["decision_cards"]
        for item in card["items"]
    )
    assert await db_session.scalar(select(func.count(CoreEntity.id))) == 0
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "只做一个动作 expand / connect / pressure / consolidate" not in prompt
    assert "不要生成人物、故事总纲、Scene" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_case", "expected_issue"),
    [
        ("missing_seed", "作者 seed 必须恰好覆盖冻结 manifest"),
        ("contradiction", "存在阻断矛盾"),
        ("too_few_rules", "World Core 需要 3–7 条规则"),
        ("missing_slice", "需要完整的日常与故障纵切"),
    ],
)
async def test_world_core_handoff_fails_closed_on_incomplete_core(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    invalid_case: str,
    expected_issue: str,
) -> None:
    fake = _install_fake_llm(monkeypatch)

    def invalid_core(keys: list[str]) -> dict:
        core = _valid_world_core(keys)
        if invalid_case == "missing_seed":
            core["author_seeds"] = core["author_seeds"][:-1]
        elif invalid_case == "contradiction":
            core["blocking_contradictions"] = ["税契与免费通行相互矛盾"]
        elif invalid_case == "too_few_rules":
            core["rule_atoms"] = core["rule_atoms"][:2]
        else:
            core["vertical_slice"] = None
        return core

    fake.world_core_factory = invalid_core
    novel_id = await _create_llm_project(async_client, f"World Core {invalid_case}")
    payload = _project_source_payload(novel_id)
    payload.update(
        {
            "workflow_preset": "world_core",
            "target": {"kind": "core_entity", "template": "none"},
            "messages": [
                {"role": "user", "content": "seed one"},
                {"role": "assistant", "content": "generated bridge"},
                {"role": "user", "content": "seed two"},
                {"role": "user", "content": "seed three"},
            ],
        }
    )

    response = await async_client.post(
        "/api/world/generation-center/convergence", json=payload
    )

    assert response.status_code == 200, response.text
    assert response.json()["world_core"]["ready_for_handoff"] is False
    assert expected_issue in response.json()["world_core"]["issues"]


@pytest.mark.asyncio
async def test_world_core_preset_rejects_non_core_target_before_llm(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "World Core 目标边界")
    payload = _project_source_payload(novel_id)
    payload.update(
        {
            "workflow_preset": "world_core",
            "target": {"kind": "world_bible_new_page", "page_type": "custom"},
        }
    )

    response = await async_client.post("/api/world/generation-center/chat", json=payload)

    assert response.status_code == 422
    assert fake.requests == []


@pytest.mark.asyncio
async def test_world_core_chat_prompt_stays_inside_core_boundary(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "World Core 对话边界")
    payload = _project_source_payload(novel_id)
    payload.update(
        {
            "workflow_preset": "world_core",
            "target": {"kind": "core_entity", "template": "none"},
        }
    )

    response = await async_client.post("/api/world/generation-center/chat", json=payload)

    assert response.status_code == 200, response.text
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "只做一个动作 expand / connect / pressure / consolidate" in prompt
    assert "不要生成人物、故事总纲、Scene" in prompt


@pytest.mark.asyncio
async def test_external_packet_is_hash_bound_and_returns_five_way_receipt(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "外部回包分流")
    packet = "packet_index: 2\npacket_total: 5\nchecks_run: strict\nFIX-147：修订港口税制"
    packet_hash = hashlib.sha256(packet.encode("utf-8")).hexdigest()
    payload = _project_source_payload(novel_id)
    payload["messages"] = [
        {"role": "user", "content": "只核对当前港口制度，不处理故事大纲"}
    ]
    payload["pasted_context"] = packet
    payload["external_packet"] = {
        "sha256": packet_hash,
        "packet_index": 2,
        "packet_total": 5,
    }

    response = await async_client.post(
        "/api/world/generation-center/convergence",
        json=payload,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["external_packet"] == payload["external_packet"]
    assert body["coverage"]["complete"] is True
    assert body["decision_cards"][0]["items"][0]["external_disposition"] == ("repair")
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "EXTERNAL_PACKET_CONTRACT" in prompt
    assert "compatible / repair / candidate / unmapped / exact_duplicate" in prompt
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0

    invalid = dict(payload)
    invalid["external_packet"] = {**payload["external_packet"], "sha256": "0" * 64}
    rejected = await async_client.post(
        "/api/world/generation-center/convergence",
        json=invalid,
    )
    assert rejected.status_code == 422

    oversized_packet = "x" * 55_001
    oversized = {
        **payload,
        "pasted_context": oversized_packet,
        "external_packet": {
            **payload["external_packet"],
            "sha256": hashlib.sha256(oversized_packet.encode("utf-8")).hexdigest(),
        },
    }
    too_large = await async_client.post(
        "/api/world/generation-center/convergence",
        json=oversized,
    )
    assert too_large.status_code == 422
    assert len(fake.requests) == 1


@pytest.mark.asyncio
async def test_generation_center_convergence_fails_closed_on_missing_source_key(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.convergence_drop_last = True
    novel_id = await _create_llm_project(async_client, "收束覆盖失败")
    payload = _project_source_payload(novel_id)
    payload["messages"].append(
        {"role": "assistant", "content": "另一个仍未被作者确认的方向。"}
    )

    response = await async_client.post(
        "/api/world/generation-center/convergence",
        json=payload,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coverage"]["complete"] is False
    assert len(body["coverage"]["missing_source_keys"]) == 1
    assert "缺少 source_key" in body["coverage"]["issues"][0]
    assert len(fake.requests) == 2
    assert await db_session.scalar(select(func.count(CoreEntity.id))) == 0
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0


@pytest.mark.asyncio
async def test_one_hop_exploration_is_read_only_and_creates_only_selected_pair(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.source_revision = True
    novel_id = await _create_llm_project(async_client, "一跳探索")
    page = await _create_published_page(async_client, novel_id)
    payload = _page_new_target_payload(novel_id, page)

    preview = await async_client.post(
        "/api/world/generation-center/exploration",
        json={**payload, "depth": 1},
    )

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["depth"] == 1
    assert len(body["targets"]) == 3
    assert all(item["evidence"] for item in body["targets"])
    snapshot = await db_session.get(
        ContextSnapshot,
        uuid.UUID(body["context_usage"]["context_snapshot_id"]),
    )
    assert snapshot is not None
    assert snapshot.prompt_name == "world.generation.exploration.preview"
    assert snapshot.compile_options["scope"] == "generation_center"
    assert snapshot.compile_options["retrieval_purpose"] == "world_generation"
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0

    selected = body["targets"][1]
    generated = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            **payload,
            "exploration_selection": {
                "depth": 1,
                "request_fingerprint": body["request_fingerprint"],
                **{
                    key: selected[key]
                    for key in (
                        "item_id",
                        "title",
                        "gap",
                        "why_it_matters",
                        "author_boundary",
                        "reverse_check_focus",
                        "source_keys",
                    )
                },
            },
        },
    )

    assert generated.status_code == 201, generated.text
    result = generated.json()
    assert result["result"]["kind"] == "world_bible_new_page"
    assert result["source_revision"]["kind"] == "world_bible_page"
    assert result["source_revision"]["proposal"]["target_page_id"] == page["id"]
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 2
    generation_prompt = next(
        "\n".join(message.content for message in request.messages)
        for request in fake.requests
        if any(
            "<AUTHOR_SELECTED_EXPLORATION>" in message.content
            for message in request.messages
        )
    )
    assert "地方税契" in generation_prompt
    assert "边境道路" not in generation_prompt
    assert "夜航邮驿" not in generation_prompt
    assert "不得继续下一跳" in generation_prompt


@pytest.mark.asyncio
async def test_current_page_semantic_inspection_replaces_stale_queue_results(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "当前页语义检修")
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
        "messages": [],
        "quality_mode": "fast",
        "include_world_synopsis": False,
    }

    first = await async_client.post(
        "/api/world/generation-center/semantic-inspection",
        json=payload,
    )

    assert first.status_code == 200, first.text
    first_body = first.json()
    assert [item["author_action"] for item in first_body["findings"]] == [
        "needs_decision"
    ]
    assert first_body["receipt"]["not_run"]
    assert "完整无误" in first_body["receipt"]["omissions"][0]
    assert "must_fix" not in first.text
    first_snapshot = await db_session.get(
        ContextSnapshot,
        uuid.UUID(first_body["context_usage"]["context_snapshot_id"]),
    )
    assert first_snapshot is not None
    assert first_snapshot.prompt_name == "world.generation.semantic_inspection"
    assert first_snapshot.compile_options["scope"] == "generation_center"
    assert first_snapshot.compile_options["retrieval_purpose"] == "world_generation"

    draft = await async_client.post(
        "/api/world/bible/drafts",
        json={"novel_id": novel_id, "page_id": page["id"]},
    )
    assert draft.status_code == 201, draft.text
    updated = await async_client.patch(
        f"/api/world/bible/drafts/{draft.json()['id']}",
        params={"novel_id": novel_id},
        json={"free_text": "星海帝国建立于长夜之后；港税仍待作者决定。"},
    )
    assert updated.status_code == 200, updated.text
    fake.semantic_findings = [
        {
            "author_action": "can_improve",
            "finding_type": "authorization",
            "summary": "港税结论缺少授权来源",
            "evidence": "页面没有说明这一结论由谁确认。",
            "location": "页面概述",
            "next_step": "补充来源或继续保留为作者候选，然后重检。",
        }
    ]
    payload["source_context"]["baseline"] = {
        "kind": "draft",
        "page_version": page["version_number"],
        "draft_id": updated.json()["id"],
        "draft_updated_at": updated.json()["updated_at"],
    }

    second = await async_client.post(
        "/api/world/generation-center/semantic-inspection",
        json=payload,
    )

    assert second.status_code == 200, second.text
    assert second.json()["findings"][0]["author_action"] == "can_improve"
    items = list(
        (
            await db_session.execute(
                select(ConflictCheckQueueItem).where(
                    ConflictCheckQueueItem.novel_id == uuid.UUID(novel_id),
                    ConflictCheckQueueItem.conflict_type == "semantic_inspection",
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(item.status for item in items) == ["pending", "stale"]
    assert len({item.target_hash for item in items}) == 2
    current = next(item for item in items if item.status == "pending")
    assert current.resolution_json["author_action"] == "can_improve"
    assert current.target["page_id"] == page["id"]


@pytest.mark.asyncio
async def test_exploration_selection_fails_closed_after_context_drift(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "探索过期")
    page = await _create_published_page(async_client, novel_id)
    payload = _page_new_target_payload(novel_id, page)
    preview = await async_client.post(
        "/api/world/generation-center/exploration",
        json=payload,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    selected = body["targets"][0]

    stale = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            **payload,
            "messages": [
                *payload["messages"],
                {"role": "user", "content": "我又改变了探索范围"},
            ],
            "exploration_selection": {
                "depth": 1,
                "request_fingerprint": body["request_fingerprint"],
                **{
                    key: selected[key]
                    for key in (
                        "item_id",
                        "title",
                        "gap",
                        "why_it_matters",
                        "author_boundary",
                        "reverse_check_focus",
                        "source_keys",
                    )
                },
            },
        },
    )

    assert stale.status_code == 409, stale.text
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0
    assert len(fake.requests) == 1


@pytest.mark.asyncio
async def test_generation_center_convergence_reduces_180_fixed_source_blocks(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "一百八十项候选收束")
    monkeypatch.setattr(
        "modules.world.services.worldbuilding.world_generation_center_service."
        "_CONVERGENCE_SOURCE_BLOCK_CHARS",
        300,
    )
    monkeypatch.setattr(
        "modules.world.services.worldbuilding.world_generation_center_service."
        "_CONVERGENCE_CALL_INPUT_CHARS",
        10000,
    )
    payload = _project_source_payload(novel_id)
    payload["pasted_context"] = "边界材料。" * 10800

    response = await async_client.post(
        "/api/world/generation-center/convergence",
        json=payload,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coverage"]["complete"] is True
    assert sum(item["kind"] == "pasted_context" for item in body["manifest"]) == 180
    assert (
        len(body["coverage"]["covered_source_keys"]) == body["coverage"]["source_count"]
    )
    assert len(body["decision_cards"]) <= 7
    assert len(fake.requests) > 2
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0


@pytest.mark.asyncio
async def test_generation_center_convergence_revalidates_source_after_model(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.errors import ConflictError

    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "收束期间来源变化")

    async def source_changed(*_args, **_kwargs) -> None:
        raise ConflictError("World generation source changed while the model was running")

    monkeypatch.setattr(
        "modules.world.api._world_generation_service._revalidate_source",
        source_changed,
    )
    response = await async_client.post(
        "/api/world/generation-center/convergence",
        json=_project_source_payload(novel_id),
    )

    assert response.status_code == 409, response.text
    assert len(fake.requests) == 1


@pytest.mark.asyncio
async def test_convergence_reads_and_revalidates_selected_world_bible_page(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world import api as world_api

    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "相关世界书页收束")
    related_page = await _create_published_page(async_client, novel_id)
    original_asset_catalog = world_api._world_generation_service._asset_catalog
    calls = 0

    async def drifting_asset_catalog(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = await original_asset_catalog(*args, **kwargs)
        if calls == 2:
            result["items"][0]["source_hash"] = "0" * 64
        return result

    monkeypatch.setattr(
        world_api._world_generation_service,
        "_asset_catalog",
        drifting_asset_catalog,
    )
    payload = _project_source_payload(novel_id)
    payload["messages"] = [{"role": "user", "content": "收束这些相关页面"}]
    payload["selected_asset_refs"] = [
        {"type": "world_bible_page", "id": related_page["id"]}
    ]

    response = await async_client.post(
        "/api/world/generation-center/convergence",
        json=payload,
    )

    assert response.status_code == 409, response.text
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "长夜结束后，帝国重建了航路。" in prompt
    assert calls == 2
    assert len(fake.requests) == 1


@pytest.mark.asyncio
async def test_generation_center_rejects_more_than_16_selected_world_pages(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "世界书参考上限")
    payload = _project_source_payload(novel_id)
    payload["selected_asset_refs"] = [
        {"type": "world_bible_page", "id": str(uuid.uuid4())} for _index in range(17)
    ]

    response = await async_client.post(
        "/api/world/generation-center/convergence",
        json=payload,
    )

    assert response.status_code == 422, response.text
    assert "at most 16 World Bible pages" in response.text
    assert fake.requests == []


@pytest.mark.asyncio
async def test_generation_center_convergence_has_one_total_timeout(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "收束总时限")

    async def slow_workflow(*_args, **_kwargs):
        await asyncio.sleep(1.1)
        return None, ["超时前不应返回"], set()

    monkeypatch.setattr(
        "modules.world.api._world_generation_service._run_convergence_workflow",
        slow_workflow,
    )
    monkeypatch.setattr(
        "modules.world.services.worldbuilding.world_generation_center_service."
        "WORLD_GENERATION_TIMEOUT_SECONDS",
        1,
    )

    with pytest.raises(TimeoutError):
        await async_client.post(
            "/api/world/generation-center/convergence",
            json=_project_source_payload(novel_id),
        )
    assert fake.requests == []


@pytest.mark.asyncio
async def test_selective_convergence_message_uses_existing_decision_compiler(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.decision_state = GeneratedWorldGenerationDecisionState(
        current_author_goal="采用制度骨架，保留精度边界",
        confirmed_requirements=["保留税制的征收与验证结构"],
        supported_developments=[],
        rejected_elements=["废弃旧组织"],
        forbidden_exact_terms=["旧组织名"],
        unresolved_choices=["具体税率继续留白"],
        naming_policy="allowed",
        confidence=1.0,
    )
    novel_id = await _create_llm_project(async_client, "选择性采用消息")
    payload = _project_source_payload(novel_id)
    payload["messages"] = [
        {"role": "user", "content": "讨论一套税制"},
        {"role": "assistant", "content": "可以设为三成并建立旧组织名"},
        {
            "role": "user",
            "content": (
                "本次纳入：\n- 保留税制的征收与验证结构\n\n"
                "继续开放（不得写成已确认事实）：\n- 具体税率继续留白\n\n"
                "明确放弃（后续不要恢复）：\n- 废弃旧组织"
            ),
        },
    ]

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["decision_state"]["unresolved_choices"] == ["具体税率继续留白"]
    assert body["decision_state"]["rejected_elements"] == ["废弃旧组织"]
    decision_meta = body["result"]["proposal"]["content_json"]["_meta"][
        "author_decision_state"
    ]
    assert decision_meta == body["decision_state"]
    proposal = body["result"]["proposal"]
    proposal_text = json.dumps(
        {
            "name": proposal["name"],
            "summary": proposal["summary"],
            "public_info": proposal["public_info"],
            "hidden_truth": proposal["hidden_truth"],
            "details": proposal["content_json"]["details"],
        },
        ensure_ascii=False,
    )
    assert "三成" not in proposal_text
    assert "旧组织名" not in proposal_text
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 1
    prompts = "\n".join(
        message.content for request in fake.requests for message in request.messages
    )
    assert "继续开放（不得写成已确认事实）" in prompts


@pytest.mark.asyncio
async def test_convergence_requires_author_content_before_llm(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "空收束范围")
    payload = _project_source_payload(novel_id)
    payload["messages"] = []

    response = await async_client.post(
        "/api/world/generation-center/convergence",
        json=payload,
    )

    assert response.status_code == 400, response.text
    assert fake.requests == []


@pytest.mark.asyncio
async def test_generation_center_chat_retries_blank_text_without_json_mode(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.chat_contents = ["   ", "第二次返回了可见的讨论内容。"]
    novel_id = await _create_llm_project(async_client, "聊天空响应重试")

    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=_project_source_payload(novel_id),
    )

    assert response.status_code == 200, response.text
    assert response.json()["reply"] == "第二次返回了可见的讨论内容。"
    assert len(fake.requests) == 2
    assert all(request.response_format is None for request in fake.requests)
    assert "不要输出 JSON、空白或协议包装" in fake.requests[1].messages[-1].content


@pytest.mark.asyncio
async def test_generation_center_chat_pro_reviews_with_same_account_model(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    account_llm_connection: dict,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.chat_contents = ["初稿回复。", "复核后的最终回复。"]
    novel_id = await _create_llm_project(async_client, "聊天加强复核")
    payload = _project_source_payload(novel_id)
    payload["quality_mode"] = "pro"

    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert response.json()["reply"] == "复核后的最终回复。"
    assert len(fake.requests) == 2
    assert {request.model for request in fake.requests} == {
        account_llm_connection["model"]
    }
    assert "加强复核" in fake.requests[1].messages[-1].content


@pytest.mark.asyncio
async def test_generation_center_chat_and_suggestion_follow_kimi_account_snapshot(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
    from modules.account.settings_constants import (
        ACCOUNT_LLM_PROVIDER_TEMPLATES,
        LOCAL_OWNER_ID,
    )
    from modules.account.settings_repositories import (
        AccountLLMCredentialRepository,
        GlobalLLMDefaultsRepository,
    )

    monkeypatch.setenv("ENABLE_ACCOUNT_KIMI_K3", "1")
    api_key = "unit-test-kimi-key"
    await AccountLLMCredentialRepository().upsert(
        db_session,
        {
            "owner_id": LOCAL_OWNER_ID,
            "provider_id": "kimi",
            "encrypted_api_key": encrypt_secret(api_key),
            "key_fingerprint": fingerprint_secret(
                api_key,
                purpose="account-llm-api-key",
            ),
            "verified_at": datetime.now(UTC),
        },
    )
    await GlobalLLMDefaultsRepository().upsert(
        db_session,
        {
            "owner_id": LOCAL_OWNER_ID,
            **ACCOUNT_LLM_PROVIDER_TEMPLATES["kimi"],
        },
    )
    await db_session.commit()

    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "Kimi 账户路由")
    chat = await async_client.post(
        "/api/world/generation-center/chat",
        json=_project_source_payload(novel_id),
    )
    suggestion_payload = _project_source_payload(novel_id)
    suggestion_payload["quality_mode"] = "pro"
    suggestion = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=suggestion_payload,
    )

    assert chat.status_code == 200, chat.text
    assert suggestion.status_code == 201, suggestion.text
    assert chat.json()["model"] == "kimi-k3"
    assert suggestion.json()["model"] == "kimi-k3"
    assert {request.model for request in fake.requests} == {"kimi-k3"}
    assert (
        "deepseek"
        not in json.dumps(
            [request.model for request in fake.requests],
            ensure_ascii=False,
        ).casefold()
    )
    for response in (chat, suggestion):
        snapshot = await db_session.get(
            ContextSnapshot,
            uuid.UUID(response.json()["context_usage"]["context_snapshot_id"]),
        )
        assert snapshot is not None
        assert snapshot.model == "kimi-k3"


@pytest.mark.asyncio
async def test_generation_center_rejects_deprecated_scene_before_llm(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "拒绝历史 Scene")
    scene = Scene(
        novel_id=uuid.UUID(novel_id),
        scene_index=0,
        title="已经废弃的 Scene",
        status="deprecated",
    )
    db_session.add(scene)
    await db_session.flush()
    payload = _project_source_payload(novel_id)
    payload["scene_id"] = str(scene.id)

    response = await async_client.post(
        "/api/world/generation-center/chat",
        json=payload,
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Selected Scene is not available in this project"
    assert fake.requests == []


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


async def test_pre_llm_projection_failure_closes_opened_context_snapshot(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "背景投影失败收尾")
    from modules.world import api as world_api

    def fail_source_refs(*_args, **_kwargs):
        raise RuntimeError("source projection failed")

    monkeypatch.setattr(
        world_api._world_generation_service,
        "_source_refs",
        fail_source_refs,
    )

    with pytest.raises(RuntimeError, match="source projection failed"):
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
    assert fake.requests == []


async def test_page_catalog_projection_failure_closes_opened_context_snapshot(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "目录投影失败收尾")
    from modules.world import api as world_api

    class _BrokenCatalogPage:
        title = "会在来源引用之后才失败"
        page_type = "background"

        @property
        def free_text(self):
            raise RuntimeError("page catalog projection failed")

    async def list_broken_catalog(*_args, **_kwargs):
        return [_BrokenCatalogPage()], 1

    monkeypatch.setattr(
        world_api._world_generation_service._bible,
        "list_pages",
        list_broken_catalog,
    )

    with pytest.raises(RuntimeError, match="page catalog projection failed"):
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
    assert fake.requests == []


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
        "modules.evidence.facade.succeed_generation_context_snapshot",
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
    account_llm_connection: dict,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.core_entity_names = ["初稿敌手", "复核后敌手"]
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
    assert body["result"]["proposal"]["name"] == "复核后敌手"
    assert body["result"]["suggestion"]["status"] == "pending"
    compatibility_ref = body["result"]["suggestion"]["result_ref_json"]
    assert compatibility_ref["type"] == "core_entity_compatibility"
    assert compatibility_ref["status"] == "pending"
    assert len(fake.requests) == 2
    assert {request.model for request in fake.requests} == {
        account_llm_connection["model"]
    }
    assert body["model"] == account_llm_connection["model"]
    assert "加强复核" in fake.requests[1].messages[-1].content
    core_prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "对象模板只提供观察角度" in core_prompt
    assert "也不能覆盖作者后续" in core_prompt
    assert "<OUTPUT_CONTRACT>" in core_prompt
    assert '"summary"' in core_prompt
    assert await db_session.scalar(select(func.count(CoreEntity.id))) == 1
    shadow = await db_session.get(CoreEntity, uuid.UUID(compatibility_ref["id"]))
    assert shadow is not None
    assert shadow.status == "candidate"
    assert shadow.content_json["_meta"]["compatibility_shadow"] is True
    assert shadow.content_json["_meta"]["source"] == "ai_generated"
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
    assert str(entity.id) == compatibility_ref["id"]
    assert entity.name == "沈无忧"
    assert entity.status == "canonical"


@pytest.mark.asyncio
async def test_generation_task_reuses_operation_and_rejects_drift(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = await _create_llm_project(async_client, "可恢复对象建议")
    operation_id = str(uuid.uuid4())
    payload = _project_source_payload(novel_id) | {"operation_id": operation_id}

    first = await async_client.post(
        "/api/world/generation-center/suggestions/task",
        json=payload,
    )
    repeated = await async_client.post(
        "/api/world/generation-center/suggestions/task",
        json=payload,
    )
    drifted = await async_client.post(
        "/api/world/generation-center/suggestions/task",
        json=payload | {"pasted_context": "不同请求"},
    )

    assert first.status_code == repeated.status_code == 202
    assert (
        first.json()
        == repeated.json()
        == {
            "task_id": operation_id,
            "status": "pending",
        }
    )
    assert drifted.status_code == 409
    tasks = list(
        (
            await db_session.scalars(
                select(AsyncTask).where(AsyncTask.id == uuid.UUID(operation_id))
            )
        ).all()
    )
    assert len(tasks) == 1
    assert tasks[0].task_type == "world_generation_suggestion"


@pytest.mark.asyncio
async def test_generation_center_drops_result_after_project_is_recycled(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "生成期间回收")
    project = await db_session.get(Project, uuid.UUID(novel_id))
    assert project is not None

    def recycle_project() -> None:
        project.deleted_at = datetime.now(UTC)

    fake.before_generate = recycle_project
    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=_project_source_payload(novel_id),
    )

    assert response.status_code == 404, response.text
    assert await db_session.scalar(select(func.count(CoreEntity.id))) == 0
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0


@pytest.mark.asyncio
async def test_core_revision_supersedes_only_previous_pending_version(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.core_entity_names = ["旧版敌手", "修订版敌手"]
    novel_id = await _create_llm_project(async_client, "对象修订链")
    payload = _project_source_payload(novel_id)
    first = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )
    assert first.status_code == 201, first.text
    predecessor = first.json()["result"]["suggestion"]
    predecessor_shadow_id = predecessor["result_ref_json"]["id"]

    incompatible = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            "novel_id": novel_id,
            "source_context": {"kind": "project"},
            "target": {"kind": "world_bible_new_page", "page_type": "custom"},
            "messages": [{"role": "user", "content": "换成一张新页"}],
            "revises_suggestion_id": predecessor["id"],
        },
    )
    assert incompatible.status_code == 400, incompatible.text
    assert len(fake.requests) == 1
    incompatible_template = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            **payload,
            "target": {"kind": "core_entity", "template": "location"},
            "revises_suggestion_id": predecessor["id"],
        },
    )
    assert incompatible_template.status_code == 400, incompatible_template.text
    assert len(fake.requests) == 1
    other_novel_id = await _create_llm_project(async_client, "其他项目的修订")
    foreign_parent = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            **_project_source_payload(other_novel_id),
            "revises_suggestion_id": predecessor["id"],
        },
    )
    assert foreign_parent.status_code == 404, foreign_parent.text
    assert len(fake.requests) == 1

    revised_payload = {**payload, "revises_suggestion_id": predecessor["id"]}
    revised = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=revised_payload,
    )

    assert revised.status_code == 201, revised.text
    successor = revised.json()["result"]["suggestion"]
    assert successor["revision_link"] == {
        "predecessor_suggestion_id": predecessor["id"],
        "successor_suggestion_id": None,
    }
    stored_predecessor = await db_session.get(
        CreationSuggestion,
        uuid.UUID(predecessor["id"]),
    )
    assert stored_predecessor is not None
    assert stored_predecessor.status == "rejected"
    assert stored_predecessor.result_ref_json["revision_link"] == {
        "successor_suggestion_id": successor["id"]
    }
    assert stored_predecessor.result_ref_json["status"] == "archived"
    old_shadow = await db_session.get(CoreEntity, uuid.UUID(predecessor_shadow_id))
    assert old_shadow is not None
    assert old_shadow.status == "ignored"

    pending = await async_client.get(
        "/api/world/suggestions",
        params={
            "novel_id": novel_id,
            "source_module": "world",
            "review_group": "generation_center",
            "status": "pending",
        },
    )
    assert pending.status_code == 200, pending.text
    assert [item["id"] for item in pending.json()["items"]] == [successor["id"]]

    rejected = await async_client.post(
        f"/api/world/suggestions/{successor['id']}/reject",
        params={"novel_id": novel_id},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["result_ref_json"]["revision_link"] == {
        "predecessor_suggestion_id": predecessor["id"]
    }
    old_confirm = await async_client.post(
        f"/api/world/suggestions/{predecessor['id']}/confirm",
        params={"novel_id": novel_id},
    )
    assert old_confirm.status_code == 409


@pytest.mark.asyncio
async def test_new_direction_keeps_both_suggestions_independent(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.core_entity_names = ["方案甲", "方案乙"]
    novel_id = await _create_llm_project(async_client, "独立方向")
    payload = _project_source_payload(novel_id)

    first = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )
    second = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )

    assert first.status_code == second.status_code == 201
    first_suggestion = first.json()["result"]["suggestion"]
    second_suggestion = second.json()["result"]["suggestion"]
    assert first_suggestion["revision_link"] is None
    assert second_suggestion["revision_link"] is None
    for suggestion in (first_suggestion, second_suggestion):
        accepted = await async_client.post(
            f"/api/world/suggestions/{suggestion['id']}/confirm",
            params={"novel_id": novel_id},
        )
        assert accepted.status_code == 200, accepted.text


@pytest.mark.asyncio
async def test_new_page_revision_requires_the_same_page_type(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "新页修订目标")
    payload = {
        "novel_id": novel_id,
        "source_context": {"kind": "project"},
        "target": {"kind": "world_bible_new_page", "page_type": "custom"},
        "messages": [{"role": "user", "content": "设计新页"}],
    }
    first = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )
    assert first.status_code == 201, first.text

    incompatible = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
            **payload,
            "target": {"kind": "world_bible_new_page", "page_type": "background"},
            "revises_suggestion_id": first.json()["result"]["suggestion"]["id"],
        },
    )

    assert incompatible.status_code == 400, incompatible.text
    assert "different target" in incompatible.json()["detail"]
    assert len(fake.requests) == 1


@pytest.mark.asyncio
async def test_revision_cas_conflict_rolls_back_new_suggestion_and_shadow(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world.services.worldbuilding.suggestion_queue_service import (
        SuggestionQueueService,
    )

    _install_fake_llm(monkeypatch)

    async def empty_background(_db: AsyncSession, **_kwargs: object) -> dict:
        return {"rendered_context": "", "context_usage": None}

    async def no_provider_checkpoint(_db: AsyncSession) -> None:
        return None

    monkeypatch.setattr(
        "modules.world.api._world_generation_service._generation_background_provider",
        empty_background,
    )
    monkeypatch.setattr(
        "modules.world.api._world_generation_service._checkpoint_before_provider",
        no_provider_checkpoint,
    )
    novel_id = await _create_llm_project(async_client, "修订并发裁决")
    payload = _project_source_payload(novel_id)
    first = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )
    assert first.status_code == 201, first.text
    predecessor = first.json()["result"]["suggestion"]
    original = SuggestionQueueService.supersede_generation_suggestion

    async def decide_before_supersede(self, db, **kwargs):
        await self.reject(
            db,
            kwargs["novel_id"],
            kwargs["predecessor_suggestion_id"],
        )
        return await original(self, db, **kwargs)

    monkeypatch.setattr(
        SuggestionQueueService,
        "supersede_generation_suggestion",
        decide_before_supersede,
    )
    savepoint = await db_session.begin_nested()
    conflicted = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={**payload, "revises_suggestion_id": predecessor["id"]},
    )
    assert conflicted.status_code == 409, conflicted.text
    await savepoint.rollback()
    db_session.expire_all()

    suggestions = (
        (
            await db_session.execute(
                select(CreationSuggestion).where(
                    CreationSuggestion.novel_id == uuid.UUID(novel_id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(suggestions) == 1
    assert suggestions[0].status == "pending"
    assert await db_session.scalar(select(func.count(CoreEntity.id))) == 1


@pytest.mark.asyncio
async def test_multiturn_generation_compiles_author_decisions_and_keeps_name_unset(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.core_entity_name = "未命名的廷根民俗资料掮客"
    fake.decision_state = GeneratedWorldGenerationDecisionState(
        current_author_goal="收束一个长期主动收集民俗资料的低频信息源",
        confirmed_requirements=["知识来自长期主动收集", "只间接影响塔罗会"],
        supported_developments=["与克莱恩建立谨慎的信息交换关系"],
        rejected_elements=["祖传秘密", "灵性极低解释", "先前作废的姓名"],
        forbidden_exact_terms=["老伊森", "灵性极低"],
        unresolved_choices=["倒吊人是否能够回应民俗词句"],
        naming_policy="unnamed_placeholder",
        confidence=0.98,
    )
    novel_id = await _create_llm_project(async_client, "多轮决策收束")
    payload = _project_source_payload(novel_id)
    payload["messages"] = [
        {"role": "user", "content": "先讨论一个廷根民俗资料掮客，不要命名。"},
        {
            "role": "assistant",
            "content": "可以叫老伊森，并用灵性极低解释他的安全。",
        },
        {
            "role": "user",
            "content": "作废刚才的名字和灵性解释；资料必须来自长期主动收集。",
        },
        {
            "role": "assistant",
            "content": "他会与克莱恩建立谨慎的信息交换关系。",
        },
        {
            "role": "user",
            "content": "采用这个关系，但仍不要命名，倒吊人是否回应保持开放。",
        },
    ]

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["result"]["proposal"]["name"].startswith("未命名")
    assert body["decision_state"] == fake.decision_state.model_dump(mode="json")
    assert body["result"]["suggestion"][
        "decision_state"
    ] == fake.decision_state.model_dump(mode="json")
    assert "先前作废的姓名" not in body["decision_state"]["current_author_goal"]
    assert "先前作废的姓名" in body["decision_state"]["rejected_elements"]
    listed = await async_client.get(
        "/api/world/suggestions",
        params={
            "novel_id": novel_id,
            "source_module": "world",
            "review_group": "generation_center",
            "status": "pending",
        },
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["decision_state"] == body["decision_state"]
    assert len(fake.requests) == 3
    decision_prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "作者决策状态编译器" in decision_prompt
    assert "<OUTPUT_CONTRACT>" in decision_prompt
    assert '"current_author_goal"' in decision_prompt
    proposal_request = fake.requests[1]
    assert all(message.role != "assistant" for message in proposal_request.messages)
    proposal_prompt = "\n".join(message.content for message in proposal_request.messages)
    assert "<AUTHOR_DECISION_STATE>" in proposal_prompt
    assert "naming_policy" in proposal_prompt
    assert "生成建议”只表示" not in proposal_prompt
    audit_prompt = "\n".join(message.content for message in fake.requests[2].messages)
    assert '"verdict"' in audit_prompt


@pytest.mark.asyncio
async def test_multiturn_page_generation_keeps_knowledge_expression_boundary(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    boundary = (
        "作者可见航路局调节长夜核心的完整机制；普通船员只称其为黑暗时间税，"
        "不知道也不能说出底层机制。"
    )
    fake.decision_state = GeneratedWorldGenerationDecisionState(
        current_author_goal="建立作者机制与船员日常表达分离的航路规则",
        confirmed_requirements=["作者层保留完整运行机制", "船员只使用日常称呼"],
        supported_developments=["黑暗时间税会改变旅行选择"],
        rejected_elements=["船员直接讲解底层机制"],
        unresolved_choices=[],
        knowledge_expression_boundaries=[boundary],
        naming_policy="allowed",
        confidence=0.95,
    )
    novel_id = await _create_llm_project(async_client, "知识表达边界")
    payload = _project_source_payload(novel_id)
    payload["target"] = {"kind": "world_bible_new_page", "page_type": "custom"}
    payload["messages"] = [
        {"role": "user", "content": "设计黑暗时间税，作者可以知道完整机制。"},
        {"role": "assistant", "content": "船员也可以直接说明底层机制。"},
        {
            "role": "user",
            "content": "不，船员只把它叫黑暗时间税，不知道底层机制。",
        },
    ]

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["decision_state"]["knowledge_expression_boundaries"] == [boundary]
    assert body["result"]["proposal"]["decision_state"] == body["decision_state"]
    assert body["result"]["suggestion"]["decision_state"] == body["decision_state"]
    assert (
        body["result"]["suggestion"]["payload_json"]["decision_state"]
        == body["decision_state"]
    )
    listed = await async_client.get(
        "/api/world/suggestions",
        params={
            "novel_id": novel_id,
            "source_module": "world",
            "review_group": "generation_center",
            "status": "pending",
        },
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["decision_state"] == body["decision_state"]
    proposal_prompt = "\n".join(message.content for message in fake.requests[1].messages)
    audit_prompt = "\n".join(message.content for message in fake.requests[2].messages)
    assert boundary in proposal_prompt
    assert boundary in audit_prompt
    assert await db_session.scalar(select(func.count(CharacterKnowledge.id))) == 0


@pytest.mark.asyncio
async def test_page_generation_persists_unresolved_choices_in_author_only_section(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    question = "具体税率仍由作者决定"
    fake.decision_state = GeneratedWorldGenerationDecisionState(
        current_author_goal="建立航路税制，但不决定具体税率",
        unresolved_choices=[question],
        naming_policy="allowed",
        confidence=1.0,
    )
    novel_id = await _create_llm_project(async_client, "页面未决项")
    payload = _project_source_payload(novel_id)
    payload["target"] = {"kind": "world_bible_new_page", "page_type": "custom"}
    payload["messages"] = [
        {"role": "user", "content": "整理一套航路税制。"},
        {"role": "assistant", "content": "可以先定为三成税率。"},
        {"role": "user", "content": "保留税制结构，具体税率先保持开放。"},
    ]

    generated = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )

    assert generated.status_code == 201, generated.text
    result = generated.json()["result"]
    section = next(
        item
        for item in result["proposal"]["page"]["sections_json"]
        if item["section_id"] == "author-open-questions"
    )
    assert section["title"] == "仍待作者决定"
    assert section["body_markdown"] == f"- [ ] {question}"
    assert section["projection_policy"] == "excluded"
    assert section["sensitivity_hint"] == "author_only"

    applied = await async_client.post(
        f"/api/world/generation-center/suggestions/{result['suggestion']['id']}/apply-page-draft",
        params={"novel_id": novel_id},
        json={},
    )
    assert applied.status_code == 200, applied.text
    published = await publish_bible_draft(
        async_client,
        novel_id,
        applied.json()["draft"]["id"],
    )
    assert published.status_code == 200, published.text
    assert any(
        item["section_id"] == "author-open-questions"
        and item["body_markdown"] == f"- [ ] {question}"
        for item in published.json()["sections_json"]
    )

    page = published.json()
    fake.existing_page_type = page["page_type"]
    revised = await async_client.post(
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
            "messages": [{"role": "user", "content": "重写正文，但别丢掉我的未决项。"}],
        },
    )
    assert revised.status_code == 201, revised.text
    assert any(
        item["section_id"] == "author-open-questions"
        and item["body_markdown"] == f"- [ ] {question}"
        for item in revised.json()["result"]["proposal"]["page"]["sections_json"]
    )


@pytest.mark.asyncio
async def test_multiturn_generation_retries_proposal_that_reuses_rejected_term(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.core_entity_names = ["伊森", "未命名的民俗资料掮客"]
    fake.decision_state = GeneratedWorldGenerationDecisionState(
        current_author_goal="收束未命名的民俗资料掮客",
        rejected_elements=["先前人物姓名"],
        forbidden_exact_terms=["伊森"],
        naming_policy="unnamed_placeholder",
        confidence=1.0,
    )
    novel_id = await _create_llm_project(async_client, "作废内容守卫")
    payload = _project_source_payload(novel_id)
    payload["messages"] = [
        {"role": "user", "content": "讨论民俗资料掮客，不要命名。"},
        {"role": "assistant", "content": "可以叫伊森。"},
        {"role": "user", "content": "伊森这个名字作废，仍然不要命名。"},
    ]

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )

    assert response.status_code == 201, response.text
    assert response.json()["result"]["proposal"]["name"] == "未命名的民俗资料掮客"
    assert len(fake.requests) == 4
    assert "不能进入待处理队列" in fake.requests[2].messages[-1].content


@pytest.mark.asyncio
async def test_multiturn_generation_retries_semantic_unresolved_choice_violation(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.core_entity_name = "未命名的民俗资料掮客"
    fake.decision_state = GeneratedWorldGenerationDecisionState(
        current_author_goal="收束低频民俗信息源",
        unresolved_choices=["收集民俗的个人动机仍待作者选择"],
        naming_policy="unnamed_placeholder",
        confidence=1.0,
    )
    fake.decision_audits = [
        GeneratedWorldGenerationDecisionAudit(
            verdict="revise",
            violations=["提案把尚未确认的个人动机写成确定事实"],
        ),
        GeneratedWorldGenerationDecisionAudit(verdict="pass", violations=[]),
    ]
    novel_id = await _create_llm_project(async_client, "未决项语义守卫")
    payload = _project_source_payload(novel_id)
    payload["messages"] = [
        {"role": "user", "content": "讨论一个民俗资料掮客，不要命名。"},
        {"role": "assistant", "content": "他的动机也许是保存消失的故事。"},
        {"role": "user", "content": "动机先不决定，生成其他已确认部分。"},
    ]

    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )

    assert response.status_code == 201, response.text
    assert len(fake.requests) == 5
    correction_request = fake.requests[3]
    assert "尚未确认的个人动机" in correction_request.messages[-1].content


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
async def test_existing_page_revision_requires_same_target_and_baseline(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "世界书修订链")
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
    first = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )
    assert first.status_code == 201, first.text
    predecessor = first.json()["result"]["suggestion"]

    revised = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={**payload, "revises_suggestion_id": predecessor["id"]},
    )

    assert revised.status_code == 201, revised.text
    successor = revised.json()["result"]["suggestion"]
    assert successor["revision_link"]["predecessor_suggestion_id"] == predecessor["id"]
    old = await db_session.get(CreationSuggestion, uuid.UUID(predecessor["id"]))
    assert old is not None
    assert old.status == "rejected"
    assert (
        old.result_ref_json["revision_link"]["successor_suggestion_id"]
        == (successor["id"])
    )
    applied = await async_client.post(
        f"/api/world/generation-center/suggestions/{successor['id']}/apply-page-draft",
        params={"novel_id": novel_id},
        json={},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["suggestion"]["revision_link"] == {
        "predecessor_suggestion_id": predecessor["id"],
        "successor_suggestion_id": None,
    }
    assert len(fake.requests) == 2


@pytest.mark.asyncio
async def test_page_revision_source_drift_does_not_create_successor(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.errors import ConflictError

    _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "修订期间页面变化")
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
    first = await async_client.post(
        "/api/world/generation-center/suggestions",
        json=payload,
    )
    assert first.status_code == 201, first.text
    predecessor_id = first.json()["result"]["suggestion"]["id"]

    async def source_changed(*_args, **_kwargs) -> None:
        raise ConflictError("World generation source changed while the model was running")

    monkeypatch.setattr(
        "modules.world.api._world_generation_service._revalidate_source",
        source_changed,
    )
    conflicted = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={**payload, "revises_suggestion_id": predecessor_id},
    )

    assert conflicted.status_code == 409, conflicted.text
    suggestions = (
        (
            await db_session.execute(
                select(CreationSuggestion).where(
                    CreationSuggestion.novel_id == uuid.UUID(novel_id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(suggestions) == 1
    assert str(suggestions[0].id) == predecessor_id
    assert suggestions[0].status == "pending"


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
async def test_existing_page_drift_during_provider_call_returns_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "模型调用期间基线冲突")
    page = await _create_published_page(async_client, novel_id)

    async def update_page_from_another_session() -> None:
        fake.before_generate = None
        async with AsyncSession(
            bind=db_session.bind,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as concurrent:
            current = await concurrent.get(WorldBiblePage, uuid.UUID(page["id"]))
            assert current is not None
            current.version_number += 1
            current.free_text = "作者在模型运行期间发布的新正文。"
            await concurrent.commit()

    fake.before_generate = update_page_from_another_session
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
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0


@pytest.mark.asyncio
async def test_existing_draft_drift_during_provider_call_returns_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    novel_id = await _create_llm_project(async_client, "模型调用期间工作稿冲突")
    page = await _create_published_page(async_client, novel_id)
    working = await async_client.post(
        "/api/world/bible/drafts",
        json={
            "novel_id": novel_id,
            "page_id": page["id"],
            "title": page["title"],
            "page_type": page["page_type"],
            "free_text": "模型调用前的工作稿。",
            "sections_json": page["sections_json"],
        },
    )
    assert working.status_code == 201, working.text
    draft = working.json()

    async def update_draft_from_another_session() -> None:
        fake.before_generate = None
        async with AsyncSession(
            bind=db_session.bind,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as concurrent:
            current = await concurrent.get(WorldBiblePageDraft, uuid.UUID(draft["id"]))
            assert current is not None
            current.free_text = "作者在模型运行期间修改的工作稿。"
            await concurrent.commit()

    fake.before_generate = update_draft_from_another_session
    response = await async_client.post(
        "/api/world/generation-center/suggestions",
        json={
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
            "messages": [{"role": "user", "content": "重构当前工作稿"}],
        },
    )

    assert response.status_code == 409, response.text
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0


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


@pytest.mark.asyncio
async def test_ask_world_api_is_read_only_cited_and_saves_only_a_suggestion(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    account_llm_connection: dict,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    fake.ask_world_answer = "无引用断言：皇帝亲自主持了航路重建。"
    fake.ask_world_uncertainty = "无引用断言：北方还有三条秘密航线。"
    monkeypatch.setattr(
        "modules.evidence.facade.retrieve_planned_context_evidence",
        _empty_ask_world_rag,
    )
    novel_id = await _create_llm_project(async_client, "有引用的问世界")
    page = await _create_published_page(async_client, novel_id)

    def assert_provider_checkpoint() -> None:
        assert db_session.in_transaction() is False

    fake.before_generate = assert_provider_checkpoint
    response = await async_client.post(
        "/api/world/ask-world",
        json={"novel_id": novel_id, "question": "世界背景航路"},
    )
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["no_answer"] is False
    assert result["answer"] == "已从当前可回读证据中整理出以下带来源的结论："
    assert "皇帝亲自" not in result["answer"]
    assert "秘密航线" not in result["uncertainty"]
    assert result["claims"][0]["text"] == "帝国在长夜后重建了航路。"
    assert result["claims"][0]["citation_keys"] == [
        result["citations"][0]["citation_key"]
    ]
    assert result["citations"][0]["page_id"] == page["id"]
    assert result["model"] == account_llm_connection["model"]
    assert fake.requests[0].model == account_llm_connection["model"]
    assert account_llm_connection["api_key"] not in "\n".join(
        message.content for message in fake.requests[0].messages
    )
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0
    assert await db_session.scalar(select(func.count(WorldBiblePage.id))) == 1
    snapshot = await db_session.get(
        ContextSnapshot,
        uuid.UUID(result["context_snapshot_id"]),
    )
    assert snapshot is not None
    assert snapshot.status == "succeeded"
    assert snapshot.operation == "world.ask"
    assert snapshot.context_mode == "canonical"

    opened = await async_client.post(
        "/api/world/ask-world/citations/open",
        json={"novel_id": novel_id, "citation": result["citations"][0]},
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["status"] == "current"
    assert "长夜结束后" in opened.json()["text"]

    save_payload = {
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
    }
    saved = await async_client.post(
        "/api/world/ask-world/suggestions",
        json=save_payload,
    )
    assert saved.status_code == 201, saved.text
    suggestion = saved.json()["suggestion"]
    assert suggestion["status"] == "pending"
    assert suggestion["action_schema"] == "ask_world.page_draft.v1"
    assert suggestion["target_type"] == "world_bible_page_draft"
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 1
    assert await db_session.scalar(select(func.count(WorldBiblePage.id))) == 1

    page_model = await db_session.get(WorldBiblePage, uuid.UUID(page["id"]))
    assert page_model is not None
    page_model.free_text = "星海帝国的航路规则已被作者改写。"
    page_model.version_number += 1
    await db_session.flush()
    stale_save = await async_client.post(
        "/api/world/ask-world/suggestions",
        json=save_payload,
    )
    assert stale_save.status_code == 409, stale_save.text
    assert "citation changed" in stale_save.json()["detail"]

    other_novel_id = await _create_llm_project(async_client, "另一个项目")
    hidden = await async_client.post(
        "/api/world/ask-world/citations/open",
        json={
            "novel_id": other_novel_id,
            "citation": result["citations"][0],
        },
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["status"] == "unavailable"
    assert hidden.json()["title"] == "来源不可用"
    assert hidden.json()["text"] == ""


@pytest.mark.asyncio
async def test_ask_world_api_refuses_without_evidence_before_llm(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake_llm(monkeypatch)
    monkeypatch.setattr(
        "modules.evidence.facade.retrieve_planned_context_evidence",
        _empty_ask_world_rag,
    )
    novel_id = await _create_llm_project(async_client, "无证据问世界")

    response = await async_client.post(
        "/api/world/ask-world",
        json={"novel_id": novel_id, "question": "月海卫星数量"},
    )
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["no_answer"] is True
    assert result["claims"] == []
    assert result["citations"] == []
    assert result["model"] == ""
    assert fake.requests == []
    assert await db_session.scalar(select(func.count(ContextSnapshot.id))) == 0
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0


@pytest.mark.asyncio
async def test_ask_world_api_retrieves_and_reopens_canonical_world_object(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(monkeypatch)
    monkeypatch.setattr(
        "modules.evidence.facade.retrieve_planned_context_evidence",
        _empty_ask_world_rag,
    )
    novel_id = await _create_llm_project(async_client, "对象来源问世界")
    entity = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type="item",
        name="旧塔铜铃",
        summary="旧塔守卫室保存这枚铜铃，只有换岗时允许取出。",
        public_info="城内居民只知道它会在换岗时响起。",
        hidden_truth="铜铃同时记录守卫室开门次数。",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()

    response = await async_client.post(
        "/api/world/ask-world",
        json={"novel_id": novel_id, "question": "旧塔铜铃来历"},
    )

    assert response.status_code == 200, response.text
    citation = response.json()["citations"][0]
    assert citation["kind"] == "world_object"
    assert citation["title"] == "旧塔铜铃"
    opened = await async_client.post(
        "/api/world/ask-world/citations/open",
        json={"novel_id": novel_id, "citation": citation},
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["status"] == "current"
    assert "守卫室保存" in opened.json()["text"]
    assert await db_session.scalar(select(func.count(CreationSuggestion.id))) == 0


@pytest.mark.asyncio
async def test_ask_world_object_recall_marks_the_bounded_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world.schemas import AskWorldQuestionRequest
    from modules.world.services.worldbuilding.ask_world_service import AskWorldService

    class _EmptyBible:
        async def list_pages(self, _db, _novel_id):
            return [], 0

    class _EntityContext:
        async def get_entity_context(self, *_args, **_kwargs):
            return SimpleNamespace(entities=entities)

    async def empty_rag(*_args, **_kwargs):
        return SimpleNamespace(rag_chunks=[], warnings=[], retrieval_trace={})

    entities = [
        SimpleNamespace(
            entity_id=str(uuid.uuid4()),
            entity_type="place",
            name=f"旧址 {index}",
            aliases=["渡桥"] if index == 0 else [],
            summary="",
            public_info="",
            hidden_truth="",
        )
        for index in range(501)
    ]
    service = AskWorldService(bible_service=_EmptyBible())
    service._entity_context = _EntityContext()
    monkeypatch.setattr(
        "modules.evidence.facade.retrieve_planned_context_evidence",
        empty_rag,
    )

    candidates, retrieval = await service._retrieve_candidates(
        None,
        AskWorldQuestionRequest(novel_id=str(uuid.uuid4()), question="渡桥在哪"),
    )

    assert candidates[0]["title"] == "旧址 0"
    assert "别名：渡桥" in candidates[0]["content"]
    assert retrieval["degraded"] is True
    assert "500 项回读上限" in retrieval["warnings"][0]


@pytest.mark.asyncio
async def test_ask_world_citation_open_does_not_mask_infrastructure_failure() -> None:
    from modules.world.schemas import AskWorldCitation
    from modules.world.services.worldbuilding.ask_world_service import AskWorldService

    class _BrokenBible:
        async def get_page(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    citation = AskWorldCitation(
        citation_key="page:test",
        kind="world_bible_page",
        title="测试页",
        source_hash="0" * 64,
        page_id=str(uuid.uuid4()),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await AskWorldService(bible_service=_BrokenBible()).open_citation(
            None,
            str(uuid.uuid4()),
            citation,
        )

    malformed = AskWorldCitation(
        citation_key="manuscript:test",
        kind="manuscript",
        title="测试正文",
        source_hash="0" * 64,
        source_ref={"draft_id": str(uuid.uuid4())},
    )
    opened = await AskWorldService().open_citation(
        None,
        str(uuid.uuid4()),
        malformed,
    )
    assert opened.status == "unavailable"

@pytest.fixture(autouse=True)
def _exercise_generation_behavior_without_repeating_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def skip_preflight(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "modules.world.api._require_generation_confirmation",
        skip_preflight,
    )


def test_ask_world_overlay_keeps_only_confirmed_sources() -> None:
    from modules.world.schemas import AskWorldCitation
    from modules.world.services.worldbuilding.ask_world_service import AskWorldService

    page = {
        "kind": "world_bible_page",
        "citation": AskWorldCitation(
            citation_key="page:1",
            kind="world_bible_page",
            title="保留页",
            source_hash="1" * 64,
            page_id="page-1",
        ),
    }
    excluded_page = {
        "kind": "world_bible_page",
        "citation": AskWorldCitation(
            citation_key="page:2",
            kind="world_bible_page",
            title="排除页",
            source_hash="2" * 64,
            page_id="page-2",
        ),
    }

    assert AskWorldService._confirmed_candidates(
        [page, excluded_page],
        {"world_bible_page": ["page-1"]},
    ) == [page]
