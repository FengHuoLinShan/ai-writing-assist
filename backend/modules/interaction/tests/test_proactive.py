"""RP background review keeps history immutable and rejects invented citations."""

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select

from core.config import get_settings
from infrastructure.tasks.models import AsyncTask
from modules.assistant import proactive as care
from modules.assistant.models import AssistantNotice
from modules.interaction import proactive
from modules.interaction.models import InteractionJourney, InteractionMessageNode
from modules.interaction.schemas import JourneyCreateRequest
from modules.interaction.services import InteractionService


@pytest.mark.asyncio
async def test_rp_policy_is_journey_scoped_and_review_does_not_change_story(
    db_session, async_client, account_llm_connection, monkeypatch
):
    settings = replace(get_settings(), interaction_agent_enabled=True)
    monkeypatch.setattr(care, "get_settings", lambda: settings)
    service = InteractionService()
    response = await service.create_journey(
        db_session,
        JourneyCreateRequest(
            opening_text="我十六岁，来到测试城。", idempotency_key="care-test"
        ),
    )
    journey = await db_session.scalar(
        select(InteractionJourney).where(
            InteractionJourney.id == uuid.UUID(response.journey.id)
        )
    )
    root = await service._repo.get_node(
        db_session, journey=journey, node_id=journey.selected_leaf_node_id
    )
    node = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=root.id,
        role="assistant",
        content="你今年已经二十岁了。",
    )
    sibling = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=root.id,
        role="assistant",
        content="未选分支暗号",
    )
    db_session.add_all([node, sibling])
    await db_session.flush()
    await service._repo.set_selected_child(
        db_session, journey=journey, parent_node_id=root.id, child_node_id=node.id
    )
    journey.selected_leaf_node_id = node.id
    await db_session.commit()
    jid, nid, selected_id = str(journey.id), str(journey.novel_id), node.id
    saved = await async_client.put(
        f"/api/interactions/journeys/{jid}/care/policy",
        json={"enabled": True, "categories": ["interaction"]},
    )
    assert saved.status_code == 200, saved.text
    denied = await async_client.put(
        f"/api/interactions/journeys/{jid}/care/policy",
        json={"enabled": True, "categories": ["world"]},
    )
    assert denied.status_code in {400, 422}
    await care.mark_changed(db_session, nid, "interaction_journey", jid)
    grant = {
        "owner_id": str(journey.owner_id),
        "version": 1,
        "run_id": str(uuid.uuid4()),
        "excluded_targets": [],
    }
    submitted = await proactive.schedule_proactive_review(
        db_session, nid, {"asset_id": jid}, {"_assistant_policy": grant}
    )
    task = await db_session.get(AsyncTask, uuid.UUID(submitted["task_id"]))
    db_session.task_checkpoint_enabled = True

    class Client:
        model_name = "deepseek-v4-flash"
        closed = False

        async def generate_structured(self, request, schema):
            text = "\n".join(message.content for message in request.messages)
            assert "未选分支暗号" not in text
            return schema.model_validate(
                {
                    "findings": [
                        {
                            "title": "年龄变化",
                            "explanation": "两处年龄需要说明",
                            "node_id": str(node.id),
                            "excerpt": "二十岁",
                            "earlier_node_id": str(root.id),
                            "earlier_excerpt": "十六岁",
                        },
                        {
                            "title": "伪造引用",
                            "explanation": "不应返回",
                            "node_id": str(sibling.id),
                            "excerpt": "未选分支暗号",
                            "earlier_node_id": str(root.id),
                            "earlier_excerpt": "十六岁",
                        },
                    ]
                }
            )

        async def close(self):
            self.closed = True

    client = Client()
    monkeypatch.setattr(
        proactive, "create_project_snapshot_llm_client", lambda *args, **kw: client
    )
    result = await proactive.handle_continuity_review(db_session, task)
    assert len(result["findings"]) == 1 and client.closed
    assert len(result["not_checked"]) >= 2
    await db_session.refresh(journey)
    assert journey.selected_leaf_node_id == selected_id
    assert not (await db_session.scalars(select(AssistantNotice))).all()
    task.status, task.result = "done", result
    await db_session.flush()
    assert await proactive.read_continuity_review(db_session, nid, str(task.id)) == {
        "status": "completed"
    }
    journey.web_search_enabled = not journey.web_search_enabled
    await db_session.flush()
    assert await proactive.read_continuity_review(db_session, nid, str(task.id)) == {
        "status": "completed"
    }
    journey.selection_epoch += 1
    await db_session.flush()
    assert await proactive.read_continuity_review(db_session, nid, str(task.id)) == {
        "status": "stale"
    }


@pytest.mark.asyncio
async def test_review_can_quote_agreements_and_fixed_sources_but_not_invent_refs(
    db_session, monkeypatch
):
    from types import SimpleNamespace

    node, overview, source = (str(uuid.uuid4()) for _ in range(3))
    material = {
        "recent_selected_history": [
            {"node_id": node, "text": "你答应立即加入对方阵营。"}
        ],
        "valid_overview": {"long_term_agreements": "不要替我决定加入阵营。"},
        "overview_revision_id": overview,
        "source_revision_id": source,
        "source_revision_fingerprint": "r" * 64,
        "selected_leaf_node_id": node,
        "selection_epoch": 1,
        "overview_epoch": 1,
        "source_epoch": 1,
        "source_fingerprint": "f" * 64,
        "source_context": "本地守卫没有离开过城门，不知道密室口令。",
        "fingerprint": "same-version",
    }

    async def materialize(db, task):
        return material

    async def settings(*args):
        return {"llm": {"provider_id": "deepseek", "model": "deepseek-v4-flash"}}

    class Client:
        model_name = "deepseek-v4-flash"

        async def generate_structured(self, request, schema):
            return schema.model_validate(
                {
                    "findings": [
                        {
                            "title": "需要核对",
                            "explanation": "引用应可回读",
                            "node_id": node,
                            "excerpt": "你答应立即加入对方阵营。",
                            "earlier_reference_id": reference,
                            "earlier_excerpt": quote,
                        }
                        for reference, quote in [
                            (
                                f"overview:{overview}:long_term_agreements",
                                "不要替我决定加入阵营。",
                            ),
                            (f"source:{'f' * 64}", "不知道密室口令"),
                            (
                                f"overview:{uuid.uuid4()}:long_term_agreements",
                                "不要替我决定加入阵营。",
                            ),
                        ]
                    ]
                }
            )

        async def close(self):
            pass

    db_session.task_checkpoint_enabled = True
    monkeypatch.setattr(proactive, "_materialize", materialize)
    monkeypatch.setattr(proactive, "restore_project_llm_execution_settings", settings)
    monkeypatch.setattr(
        proactive, "create_project_snapshot_llm_client", lambda *a, **kw: Client()
    )
    task = SimpleNamespace(
        novel_id=uuid.uuid4(),
        meta={"journey_id": "journey", "llm_execution_snapshot": {}},
    )
    result = await proactive.handle_continuity_review(db_session, task)
    assert len(result["findings"]) == 2
    assert result["findings"][0]["location"]["earlier_reference"]["id"] == overview
    assert result["findings"][1]["location"]["earlier_reference"]["id"] == source
    assert any("成对证据" in item for item in result["not_checked"])
