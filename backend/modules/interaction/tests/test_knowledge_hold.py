"""RP held release 单元测试：hold 私有性、释放与关闭时保留。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest


def _attempt() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        visible_text="",
        visible_offset=0,
        agent_checkpoint_json={},
        usage={},
        status="running",
        metadata_text=None,
        last_checkpoint_at=None,
    )


def test_hold_writes_stay_private() -> None:
    from modules.interaction.generation import InteractionGenerationWorkflow

    workflow = InteractionGenerationWorkflow.__new__(InteractionGenerationWorkflow)
    attempt = _attempt()
    for delta in ("第一段。", "第二段。"):
        hold = workflow._knowledge_hold(attempt)
        hold["release_state"] = "held"
        hold["text"] = str(hold.get("text") or "") + delta
        workflow._write_knowledge_hold(attempt, hold)
    assert attempt.visible_text == ""
    assert attempt.visible_offset == 0
    assert attempt.agent_checkpoint_json["knowledge_hold"]["text"] == "第一段。第二段。"
    assert attempt.agent_checkpoint_json["knowledge_hold"]["release_state"] == "held"


def test_clear_private_agent_state_preserves_hold() -> None:
    from modules.interaction.runtime_policy import clear_private_agent_state

    attempt = _attempt()
    attempt.agent_checkpoint_json = {
        "budget": {"requests": 1},
        "references": {"abc": {"text": "秘密"}},
        "knowledge_hold": {"release_state": "held", "text": "未公开正文"},
    }
    clear_private_agent_state(attempt)
    preserved = attempt.agent_checkpoint_json
    assert "references" not in preserved, "可恢复模型消息必须清除"
    assert preserved["evidence_receipts"] == [{}]
    assert preserved["knowledge_hold"]["text"] == "未公开正文"


def test_clear_private_agent_state_drops_hold_when_released() -> None:
    from modules.interaction.runtime_policy import clear_private_agent_state

    attempt = _attempt()
    attempt.agent_checkpoint_json = {
        "budget": {},
        "knowledge_hold": {"release_state": "released", "knowledge_review": {}},
    }
    clear_private_agent_state(attempt)
    # released 后正文已在 visible_text，私有 hold 只留回执
    assert attempt.agent_checkpoint_json["knowledge_hold"]["release_state"] == "released"
    assert "text" not in attempt.agent_checkpoint_json["knowledge_hold"]


@pytest.mark.asyncio
async def test_govern_held_story_pass_and_block_paths(monkeypatch) -> None:  # noqa: ANN001
    """govern：审计 pass 直接放行；blocked 且返修仍 blocked 时返回 blocked。"""
    from infrastructure.llm.schemas import LLMMessage
    from modules.evidence.compilation.knowledge.llm_schemas import (
        AuditDimensionCheck,
        AuditFindingOutput,
        AuditVerdictOutput,
        DirectorShardPlan,
    )
    from modules.interaction.generation import (
        InteractionGenerationWorkflow,
        PreparedStoryGeneration,
    )

    workflow = InteractionGenerationWorkflow.__new__(InteractionGenerationWorkflow)
    novel_id = str(uuid.uuid4())
    journey_id = str(uuid.uuid4())
    attempt_id = str(uuid.uuid4())
    task = SimpleNamespace(
        meta={
            "novel_id": novel_id,
            "journey_id": journey_id,
            "attempt_id": attempt_id,
        }
    )
    attempt = SimpleNamespace(
        source_context_fingerprint="f" * 16,
        agent_checkpoint_json={
            "knowledge_hold": {"release_state": "held", "text": "待审正文。"}
        },
    )

    async def _get_journey_for_task(db, *, journey_id, novel_id, for_update=False):  # noqa: ANN001
        return SimpleNamespace(novel_id=novel_id)

    async def _get_attempt(db, *, journey, attempt_id):  # noqa: ANN001
        return attempt

    fake_repo = SimpleNamespace(
        get_journey_for_task=_get_journey_for_task,
        get_attempt=_get_attempt,
    )
    object.__setattr__(workflow, "_repo", fake_repo)

    prepared = PreparedStoryGeneration(
        novel_id=novel_id,
        journey_id=journey_id,
        attempt_id=attempt_id,
        request_kind="message",
        messages=[
            LLMMessage(
                role="user",
                content="Earlier event. " * 2000 + "本轮选择：绕开卫兵，从码头离开。",
            ),
            LLMMessage(role="assistant", content="你来到码头。"),
            LLMMessage(role="user", content="修正：随身只有一封信，没有工具箱。"),
        ],
        executable_settings={"llm": {"model": "m", "max_tokens": 128}},
        existing_visible_text="",
    )

    class _PassClient:
        async def generate_structured(self, request, schema, **kwargs):  # noqa: ANN001
            assert "本轮选择：绕开卫兵，从码头离开。" in request.messages[-1].content
            requirements = (
                request.messages[-1]
                .content.split("【作者要求（冻结投影）】\n", 1)[1]
                .split("【生成者可见资料】", 1)[0]
            )
            assert "随身只有一封信，没有工具箱" in requirements
            assert "Earlier event" not in requirements
            if schema is DirectorShardPlan:
                return DirectorShardPlan(dispositions=[])
            return AuditVerdictOutput(
                findings=[],
                dimensions=[AuditDimensionCheck(dimension="source_canon", checked=True)],
                verdict="pass",
            )

    governed = await workflow.govern_held_story(
        None, task=task, client=_PassClient(), prepared=prepared
    )
    assert governed["status"] == "passed"
    assert governed["text"] == "待审正文。"
    assert governed["review"]["status"] == "passed"

    class _BlockClient:
        def __init__(self) -> None:
            self.repair_calls = 0

        async def generate_structured(self, request, schema, **kwargs):  # noqa: ANN001
            if schema is DirectorShardPlan:
                return DirectorShardPlan(dispositions=[])
            return AuditVerdictOutput(
                findings=[
                    AuditFindingOutput(
                        kind="premature_reveal",
                        severity="blocker",
                        message="提前揭示",
                    )
                ],
                dimensions=[AuditDimensionCheck(dimension="source_canon", checked=True)],
                verdict="blocked",
            )

        async def generate(self, request, **kwargs):  # noqa: ANN001
            from infrastructure.llm.schemas import LLMCallResponse

            self.repair_calls += 1
            return LLMCallResponse(content="返修后仍剧透。")

    blocker = _BlockClient()
    from dataclasses import replace

    governed_blocked = await workflow.govern_held_story(
        None,
        task=task,
        client=blocker,
        prepared=replace(prepared, messages=[LLMMessage(role="user", content="继续")]),
    )
    assert governed_blocked["status"] == "blocked"
    assert governed_blocked["text"] == ""
    assert governed_blocked["review"]["status"] == "blocked"
    assert governed_blocked["review"]["repaired"] is True
    assert blocker.repair_calls == 1, "一次语义返修后仍失败即阻断"

    class _RepairPassClient(_BlockClient):
        async def generate_structured(self, request, schema, **kwargs):  # noqa: ANN001
            if schema is DirectorShardPlan:
                return DirectorShardPlan(dispositions=[])
            if self.repair_calls:
                assert "INTERACTION_META_V1" not in request.messages[-1].content
                return AuditVerdictOutput(
                    findings=[],
                    dimensions=[
                        AuditDimensionCheck(dimension="source_canon", checked=True)
                    ],
                    verdict="pass",
                )
            return await super().generate_structured(request, schema, **kwargs)

        async def generate(self, request, **kwargs):  # noqa: ANN001
            from infrastructure.llm.schemas import LLMCallResponse
            from modules.interaction.framing import META_END, META_START

            self.repair_calls += 1
            return LLMCallResponse(
                content=(
                    "返修后的故事。"
                    + META_START
                    + '{"version":1,"response_kind":"story","suggested_title":"返修标题"}'
                    + META_END
                )
            )

    repaired = await workflow.govern_held_story(
        None,
        task=task,
        client=_RepairPassClient(),
        prepared=replace(prepared, messages=[LLMMessage(role="user", content="继续")]),
    )
    assert repaired["status"] == "passed"
    assert repaired["text"] == "返修后的故事。"
    assert repaired["metadata"].suggested_title == "返修标题"
