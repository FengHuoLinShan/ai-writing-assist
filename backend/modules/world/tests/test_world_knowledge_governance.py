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
    fake.chat_contents = [
        "主角其实早已死亡，这段是凶手视角的剧透正文。",
        "返修后仍是剧透正文。",
    ]
    fake.audit_verdicts = ["blocked", "blocked"]
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
    assert body["knowledge_review"]["repaired"] is True


@pytest.mark.asyncio
async def test_chat_repairs_once_with_the_original_reply_and_rechecks(
    async_client, monkeypatch
):
    fake = _install_fake_llm(monkeypatch)
    fake.chat_contents = ["人物偷知隐藏真相。", "人物只按已知线索行动。"]
    fake.audit_verdicts = ["blocked", "pass"]
    novel_id = await _create_llm_project(async_client, "聊天修复")
    response = await async_client.post(
        "/api/world/generation-center/chat", json=_project_source_payload(novel_id)
    )
    assert response.status_code == 200
    assert response.json()["reply"] == "人物只按已知线索行动。"
    assert response.json()["knowledge_review"]["repaired"] is True
    assert any(
        message.role == "assistant" and message.content == "人物偷知隐藏真相。"
        for message in fake.requests[-1].messages
    )


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


@pytest.mark.asyncio
async def test_govern_world_output_passes_frozen_requirements_to_audit() -> None:
    """审查看到完整冻结的资料和作者要求，不做第二次静默截断。"""
    from modules.evidence.compilation.knowledge.llm_schemas import (
        AuditDimensionCheck,
        AuditVerdictOutput,
    )
    from modules.world.services.worldbuilding.knowledge_governance import (
        govern_world_output,
    )

    audit_prompts: list[str] = []

    class AuditOnlyClient:
        async def generate_structured(self, request, schema, **kwargs):  # noqa: ANN001
            audit_prompts.append(request.messages[-1].content)
            return AuditVerdictOutput(
                findings=[],
                dimensions=[
                    AuditDimensionCheck(dimension=d, checked=True)
                    for d in ("world_entities", "world_rules", "world_bible", "timeline")
                ],
                verdict="pass",
            )

    requirements = (
        '<AUTHOR_DECISION_STATE>{"confirmed_requirements": '
        f'"不得复活死者", "padding": "{"x" * 25_000}"}}</AUTHOR_DECISION_STATE>'
    )
    result = await govern_world_output(
        AuditOnlyClient(),
        capability="world.generation.suggestion",
        novel_id=str(uuid.uuid4()),
        source_refs=[],
        rendered_context="资" * 30_000,
        output="提案正文",
        task_instruction="生成对象建议",
        author_requirements=requirements,
    )
    assert result["status"] == "passed"
    prompt = audit_prompts[0]
    assert "不得复活死者" in prompt
    assert "【作者要求（冻结投影）】" in prompt
    assert "【输出权限】" in prompt
    assert "x" * 25_000 in prompt  # 作者要求投影未被 24K 截断
    assert "资" * 30_000 in prompt


@pytest.mark.asyncio
async def test_world_review_receives_workspace_first_turn_and_repairs_exact_draft():
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
    from modules.evidence.compilation.knowledge.llm_schemas import AuditVerdictOutput
    from modules.world.schemas import WorldDesignIterationOutput
    from modules.world.services.worldbuilding.world_generation_center_service import (
        WorldGenerationCenterService,
    )

    class Client:
        audits = []
        repairs = []

        async def generate_structured(self, request, schema, **_kwargs):
            if schema is AuditVerdictOutput:
                self.audits.append(request.messages[-1].content)
                return schema(
                    findings=[],
                    dimensions=[],
                    verdict="blocked" if len(self.audits) == 1 else "pass",
                )
            self.repairs.append(request)
            return schema(summary="已补轮值", changes={})

    client = Client()
    service = WorldGenerationCenterService()
    output, review = await service._govern_structured(
        client,
        capability="world.generation.design_iteration",
        novel_id=str(uuid.uuid4()),
        prepared={
            "source_refs": [],
            "background": {"rendered_context": "公共背景"},
            "knowledge_context": "已保存成果：盐料七日，双人轮值。",
            "conversation_messages": [
                LLMMessage(role="user", content="只整理已有轮值，不增加机构")
            ],
        },
        generated=WorldDesignIterationOutput(summary="初稿缺少轮值安排", changes={}),
        request=LLMCallRequest(
            messages=[LLMMessage(role="user", content="原始生成请求")]
        ),
        schema=WorldDesignIterationOutput,
        decision_state=None,
        step_name="world.generation.design_iteration",
        quality_mode="fast",
        task_instruction="整理",
    )
    assert review["status"] == "passed"
    assert output.summary == "已补轮值"
    assert all("已保存成果：盐料七日，双人轮值。" in prompt for prompt in client.audits)
    assert all("只整理已有轮值，不增加机构" in prompt for prompt in client.audits)
    assert all("来源回溯" in prompt for prompt in client.audits)
    assert any(
        message.role == "assistant" and "初稿缺少轮值安排" in message.content
        for message in client.repairs[0].messages
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["pass", "blocked"])
async def test_deterministic_boundary_failure_uses_the_single_repair_allowance(verdict):
    from core.errors import ValidationError
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
    from modules.evidence.compilation.knowledge.llm_schemas import AuditVerdictOutput
    from modules.world.schemas import WorldDesignIterationOutput
    from modules.world.services.worldbuilding.world_generation_center_service import (
        WorldGenerationCenterService,
    )

    class Client:
        repairs = 0
        audits = 0

        async def generate_structured(self, request, schema, **_kwargs):
            if schema is AuditVerdictOutput:
                self.audits += 1
                return schema(findings=[], dimensions=[], verdict=verdict)
            self.repairs += 1
            assert "未确认的来源" in "\n".join(m.content for m in request.messages)
            return schema(summary="修复来源", changes={})

    def validate(output, _previous):
        if output.summary == "错误来源":
            raise ValidationError("本轮变化引用了未确认的来源")
        return output

    client = Client()
    _, review = await WorldGenerationCenterService()._govern_structured(
        client,
        capability="world.generation.design_iteration",
        novel_id=str(uuid.uuid4()),
        prepared={"source_refs": [], "background": {}},
        generated=WorldDesignIterationOutput(summary="错误来源", changes={}),
        request=LLMCallRequest(messages=[LLMMessage(content="生成")]),
        schema=WorldDesignIterationOutput,
        decision_state=None,
        step_name="world.generation.design_iteration",
        quality_mode="fast",
        task_instruction="推演",
        normalize=validate,
    )
    assert client.repairs == client.audits == 1
    assert review["repaired"] is True
    assert review["status"] == ("passed" if verdict == "pass" else "blocked")
