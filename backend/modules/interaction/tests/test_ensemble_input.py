"""Real project gateway; only provider transport is replaced for intent/bootstrap."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.errors import ConflictError
from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from modules.interaction.ensemble_input import prepare_player_input
from modules.project.facade import open_project_llm_client


async def test_bootstrap_uses_committed_story_and_reuses_bound_action_receipt(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    db, nid, player, actor = db_session, test_project_id, str(uuid4()), str(uuid4())
    source_id = str(uuid4())
    nodes = [
        SimpleNamespace(
            id=uuid4(),
            role="user",
            content="我有无限黄金",
            completion_state="complete",
            message_kind="story",
        ),
        SimpleNamespace(
            id=uuid4(),
            role="assistant",
            content="隐藏设定：宝藏在北边",
            completion_state="complete",
            message_kind="setup",
        ),
        SimpleNamespace(
            id=source_id,
            role="assistant",
            content="钥匙放在桌上，无人持有。",
            completion_state="complete",
            message_kind="story",
        ),
        SimpleNamespace(
            id=uuid4(),
            role="user",
            content="我伸手拿钥匙。",
            completion_state="complete",
            message_kind="story",
        ),
    ]
    seen, checkpoints = [], []

    async def provider(self, request):
        assert not db.in_transaction()
        text = "\n".join(message.content or "" for message in request.messages)
        assert "无限黄金" not in text and "宝藏在北边" not in text
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        seen.append(schema)
        if schema == "EnsembleInputPlan":
            payload = json.loads(
                next(m.content for m in request.messages if m.role == "user")
            )
            assert payload["committed_story"] == {source_id: "钥匙放在桌上，无人持有。"}
            assert payload["input"] == "我伸手拿钥匙。"
            value = {
                "resources": [
                    {
                        "key": "钥匙",
                        "holder": None,
                        "source_id": source_id,
                        "excerpt": "钥匙放在桌上，无人持有。",
                    }
                ],
                "action_kind": "act",
                "resource_key": "钥匙",
            }
        else:
            assert schema == "AuditVerdictOutput"
            value = {
                "verdict": "pass",
                "dimensions": [
                    {"dimension": key, "checked": True}
                    for key in ("prior_prose", "world_rules", "outline")
                ],
            }
        return LLMCallResponse(
            content=json.dumps(value, ensure_ascii=False),
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )

    async def checkpoint(values=None):
        checkpoints.append(values)
        await db.commit()

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    async with open_project_llm_client(db, nid) as client:
        run = SimpleNamespace(
            db=db,
            novel_id=nid,
            client=client,
            state={},
            budget=AgentRunBudget(mode="rp"),
            checkpoint=checkpoint,
        )
        labels = {player: "你", actor: "守卫"}
        result = await prepare_player_input(run, nodes, {}, player, labels, "action")
        assert result.resource_key == "钥匙" and result.resources[0].holder is None
        assert run.budget.requests == 2 and len(seen) == 2
        assert (
            checkpoints
            and run.state["ensemble_input_plan"]["knowledge_review"]["status"] == "passed"
        )
        assert (
            await prepare_player_input(run, nodes, {}, player, labels, "action") == result
        )
        assert len(seen) == 2
        nodes[-1].content = "我已拿走钥匙。"
        with pytest.raises(ConflictError, match="原资料已经变化"):
            await prepare_player_input(run, nodes, {}, player, labels, "action")
        assert len(seen) == 2
