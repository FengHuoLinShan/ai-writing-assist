"""RP Agent integration preserves the existing attempt and selected history."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from core.config import get_settings
from infrastructure.llm.schemas import (
    LLMCallResponse,
    LLMStreamChunk,
    LLMToolCall,
    LLMUsage,
)
from infrastructure.tasks.models import AsyncTask
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionMessageNode,
)
from modules.interaction.runtime_policy import (
    AGENT_STORY_TASK,
    agent_story_enabled,
    story_task_type,
)
from modules.interaction.schemas import JourneyCreateRequest
from modules.interaction.services import InteractionService
from modules.interaction.tasks import handle_interaction_story_generate


class PlanningClient:
    model_name = "deepseek-v4-flash"

    def __init__(self):
        self.calls = 0
        self.closed = False
        self.fail_stream = False

    async def generate(self, request, *, transport_retries):
        assert not transport_retries
        self.calls += 1
        assert "私密支线" not in str(
            [message.provider_message() for message in request.messages]
        )
        if self.calls == 1:
            call = LLMToolCall(
                id="history-1", name="lookup_history", arguments='{"query":"测试城"}'
            )
        else:
            evidence = json.loads(request.messages[-1].content)["hits"][0]["evidence_id"]
            tool = next(
                t
                for t in request.tools
                if "scene_intent" in t.parameters.get("properties", {})
            )
            call = LLMToolCall(
                id="plan-1",
                name=tool.name,
                arguments=json.dumps(
                    {
                        "scene_intent": "在街上观察，保持记者身份",
                        "evidence_ids": [evidence],
                    },
                    ensure_ascii=False,
                ),
            )
        return LLMCallResponse(
            tool_calls=[call],
            usage=LLMUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
        )

    async def generate_stream(self, request, *, transport_retries):
        assert not transport_retries
        content = "\n".join(m.content for m in request.messages)
        assert "私密支线" not in content
        assert "在街上观察" in content
        assert request.messages[-1].content == "我来到测试城，作为记者沿街观察。"
        yield LLMStreamChunk(content="街道很静，报童站在路口。")
        if self.fail_stream:
            raise ConnectionError("synthetic provider interruption")
        yield LLMStreamChunk(
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=7, completion_tokens=5, total_tokens=12),
        )

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_stream", [False, True])
async def test_agent_story_uses_selected_history_then_existing_stream_finalizer(
    db_session, account_llm_connection, monkeypatch, fail_stream
):
    settings = replace(get_settings(), interaction_agent_enabled=True)
    monkeypatch.setattr("modules.project.llm_runtime.get_settings", lambda: settings)
    client = PlanningClient()
    client.fail_stream = fail_stream
    monkeypatch.setattr(
        "modules.interaction.tasks.create_project_snapshot_llm_client",
        lambda *a, **kw: client,
    )
    db_session.task_checkpoint_enabled = True
    response = await InteractionService().create_journey(
        db_session,
        JourneyCreateRequest(
            opening_text="我来到测试城，作为记者沿街观察。",
            idempotency_key="agent-runtime-integration",
        ),
    )
    attempt_id = uuid.UUID(response.attempt.id)
    attempt = await db_session.get(InteractionGenerationAttempt, attempt_id)
    db_session.add(
        InteractionMessageNode(
            novel_id=attempt.novel_id,
            journey_id=attempt.journey_id,
            parent_node_id=attempt.response_to_node_id,
            role="assistant",
            content="私密支线：测试城的另一个未选择结局。",
        )
    )
    task_row = await db_session.get(AsyncTask, attempt.task_id)
    assert task_row.task_type == AGENT_STORY_TASK
    task = SimpleNamespace(
        id=task_row.id,
        meta=dict(task_row.meta),
        task_type=task_row.task_type,
        progress=0.0,
    )
    task.update_progress = lambda value: setattr(task, "progress", value)
    await db_session.commit()
    if fail_stream:
        with pytest.raises(ConnectionError):
            await handle_interaction_story_generate(db_session, task)
    else:
        result = await handle_interaction_story_generate(db_session, task)
        assert result["status"] == "completed"
    attempt = await db_session.get(InteractionGenerationAttempt, attempt_id)
    assert attempt.visible_text == "街道很静，报童站在路口。"
    assert attempt.usage["agent_budget"]["requests"] == 3
    assert attempt.status == ("failed" if fail_stream else "completed")
    assert attempt.usage["prompt_tokens"] == (20 if fail_stream else 27)
    assert attempt.usage["completion_tokens"] == (6 if fail_stream else 11)
    assert client.calls == 2 and client.closed


def test_legacy_snapshot_cannot_be_silently_upgraded():
    assert not agent_story_enabled({})
    assert story_task_type({}) == "interaction_story_generate"
    with pytest.raises(ValueError):
        agent_story_enabled({"agent_runtime": {"version": "unknown"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("private_query", ["银钥城", "银城", "长夜之书", "private"])
async def test_web_rejects_source_identity_and_tool_read_private_text(private_query):
    from infrastructure.llm.schemas import LLMMessage
    from modules.interaction.agent_runtime import InteractionAgentRun

    async def noop(*args, **kwargs):
        pass

    async def guard():
        return (
            SimpleNamespace(
                title="我的旅程", opening_text="出发", web_search_enabled=False
            ),
            None,
            SimpleNamespace(
                title="长夜之书",
                reference_manifest=[{"label": "银钥城", "aliases": ["银城"]}],
            ),
        )

    async def research(*args, **kwargs):
        pytest.fail("private material reached the supplier")

    agent = InteractionAgentRun(
        SimpleNamespace(commit=noop, expire_all=lambda: None),
        SimpleNamespace(),
        SimpleNamespace(_task_ids=lambda _: ("n", "j", "a")),
    )
    agent.guard = guard
    private = (
        "这是仅在先前选中故事中出现的私文，经过回顾压缩后由历史工具回读，"
        "任何一段都不应发到外部搜索服务。"
    )
    agent.references = {"known": {"kind": "selected_history", "text": private}}
    agent.prepared = SimpleNamespace(messages=[LLMMessage(role="user", content="继续")])
    agent.client = SimpleNamespace(research=research)
    result = await agent.web(private if private_query == "private" else private_query)
    assert "omission" in result


@pytest.mark.asyncio
async def test_planning_preserves_server_material_but_replaces_story_instruction(
    monkeypatch,
):
    from infrastructure.llm.schemas import LLMMessage
    from modules.interaction import agent_runtime
    from modules.interaction.generation import PreparedStoryGeneration

    messages = [
        LLMMessage(role="system", content="原始故事执行指令"),
        *[
            LLMMessage(role="system", content=text)
            for text in ["长期约定哨兵", "有效回顾哨兵", "固定来源哨兵"]
        ],
        LLMMessage(role="user", content="继续"),
    ]
    prepared = PreparedStoryGeneration(
        novel_id="n",
        journey_id="j",
        attempt_id="a",
        request_kind="message",
        messages=messages,
        existing_visible_text="",
        executable_settings={
            "llm": {"provider_id": "deepseek", "model": "deepseek-v4-flash"}
        },
    )

    async def checkpoint(*args):
        pass

    async def planning(client, request, **kwargs):
        content = "\n".join(m.content for m in request.messages)
        assert "原始故事执行指令" not in content
        for expected in ["长期约定哨兵", "有效回顾哨兵", "固定来源哨兵"]:
            assert expected in content
        return SimpleNamespace(
            output=agent_runtime.StoryPreparation(scene_intent="接续现场")
        )

    async def stream(request, **kwargs):
        yield LLMStreamChunk(content="正文")

    agent = agent_runtime.InteractionAgentRun(
        None, None, SimpleNamespace(_task_ids=lambda _: ("n", "j", "a"))
    )
    agent.checkpoint = checkpoint
    monkeypatch.setattr(agent_runtime, "run_project_agent", planning)
    client = SimpleNamespace(model_name="deepseek-v4-flash", generate_stream=stream)
    assert [chunk.content async for chunk in agent.stream(client, prepared)] == ["正文"]


@pytest.mark.asyncio
async def test_self_hosted_research_needs_new_snapshot_and_explicit_journey_consent(
    monkeypatch,
):
    from infrastructure.llm import web_search
    from modules.interaction.agent_runtime import InteractionAgentRun

    config = replace(get_settings(), web_search_url="http://search:8080")
    monkeypatch.setattr(web_search, "get_settings", lambda: config)
    journey = SimpleNamespace(
        title="我的旅程", opening_text="出发", web_search_enabled=True
    )
    calls = []

    async def noop(*args, **kwargs):
        pass

    async def guard():
        return journey, None, None

    async def search(question, **kwargs):
        calls.append("search")
        await kwargs["before_request"]()
        return {
            "hits": [
                {
                    "url": "https://example.org/water",
                    "title": "水",
                    "coverage": "search_snippet",
                }
            ]
        }

    async def read(url, **kwargs):
        calls.append("read")
        await kwargs["before_request"]()
        return {
            "url": url,
            "title": "水",
            "text": "沸点随压力变化",
            "coverage": "page_text",
        }

    monkeypatch.setattr(web_search, "search_public_fact", search)
    monkeypatch.setattr(web_search, "read_public_page", read)
    agent = InteractionAgentRun(
        SimpleNamespace(commit=noop, expire_all=lambda: None),
        SimpleNamespace(),
        SimpleNamespace(_task_ids=lambda _: ("n", "j", "a")),
    )
    agent.guard = guard
    agent.checkpoint = noop
    agent.prepared = SimpleNamespace(
        messages=[],
        executable_settings={
            "_agent_runtime": {"version": "1", "mode": "rp", "allow_web": True}
        },
    )
    assert "omission" in await agent.search_public("水的沸点")
    agent.prepared.executable_settings["_agent_runtime"] = {
        "version": "2",
        "mode": "rp",
        "web_search": web_search.search_snapshot(),
    }
    result = await agent.search_public("水的沸点")
    key = result["hits"][0]["evidence_id"]
    first = await agent.read_public(key)
    with pytest.raises(ModelRetry, match="本次搜索"):
        await agent.read_public("unseen-source")
    assert await agent.read_public(key) == first
    assert calls == ["search", "read"]
    assert agent.budget.web_requests == 2 and agent.budget.requests == 0
    journey.web_search_enabled = False
    assert "omission" in await agent.read_public(key)
    assert calls == ["search", "read"]


@pytest.mark.asyncio
async def test_closed_search_does_not_break_a_frozen_length_continuation(monkeypatch):
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
    from modules.interaction import agent_runtime as runtime

    async def noop(*args, **kwargs):
        pass

    async def scope():
        return False, [], []

    class Client:
        model_name = "deepseek-flash"

        async def generate_stream(self, request, **kwargs):
            yield LLMStreamChunk(
                content="继续保留原有选择。",
                usage=LLMUsage(prompt_tokens=2, completion_tokens=2, total_tokens=4),
            )

    monkeypatch.setattr(
        runtime,
        "story_request",
        lambda _: LLMCallRequest(
            model="deepseek-flash",
            messages=[
                LLMMessage(role="system", content="故事"),
                LLMMessage(role="user", content="继续"),
            ],
        ),
    )
    monkeypatch.setattr(
        runtime,
        "capability_from_execution_settings",
        lambda _: SimpleNamespace(hard_input_tokens=10000),
    )
    agent = runtime.InteractionAgentRun(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(_task_ids=lambda _: ("n", "j", "a")),
    )
    agent.external_scope, agent.checkpoint = scope, noop
    agent.state = {"plan": {"scene_intent": "接续先前故事", "evidence_ids": []}}
    prepared = SimpleNamespace(
        existing_visible_text="先前已输出的故事",
        executable_settings={
            "_agent_runtime": {
                "version": "2",
                "web_search": {"protocol": "searxng-v1", "endpoint_hash": "x" * 64},
            }
        },
    )
    chunks = [chunk async for chunk in agent.stream(Client(), prepared)]
    assert chunks[0].content == "继续保留原有选择。"
    assert agent.budget.requests == 1 and agent.budget.web_requests == 0


@pytest.mark.asyncio
async def test_rp_web_subbudget_returns_omission_without_spending_final_story_budget(
    monkeypatch,
):
    from infrastructure.llm import web_search
    from modules.interaction.agent_runtime import InteractionAgentRun

    async def noop(*args, **kwargs):
        pass

    async def scope():
        return {}, [], []

    async def redirect_read(url, **kwargs):
        await kwargs["before_request"]()
        await kwargs["before_request"]()
        pytest.fail("redirect exceeded the remaining web budget")

    agent = InteractionAgentRun(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(_task_ids=lambda _: ("n", "j", "a")),
    )
    agent.public_scope, agent.checkpoint = scope, noop
    agent.budget.web_requests = 1
    agent.references = {
        "search": {
            "kind": "external_search",
            "web_result": {"url": "https://example.org"},
        }
    }
    monkeypatch.setattr(web_search, "read_public_page", redirect_read)
    result = await agent.read_public("search")
    assert "额度" in result["omission"]
    assert agent.budget.web_requests == 2 and agent.budget.requests == 0
    agent.budget.reserve(requests=1)
    assert agent.budget.requests == 1
