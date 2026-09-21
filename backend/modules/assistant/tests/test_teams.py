"""Team scope, safe citations, idempotent API, and model protocol contracts."""

import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from core.config import get_settings
from core.errors import ConflictError
from modules.assistant.teams.contracts import Investigation
from modules.assistant.teams.runner import validate_investigation
from modules.evidence.contracts import TeamProjection
from modules.evidence.facade import project_team_artifact


async def test_bad_model_read_offset_is_retryable_without_expanding_scope(
    db_session, test_project_id
):
    from infrastructure.llm.agent_runtime import AgentRunBudget
    from modules.account.facade import current_account_id
    from modules.assistant.evidence_tools import (
        AssistantToolContext,
        inspect_current,
        read_evidence,
    )
    from modules.assistant.schemas import WorkContext
    from modules.writing.facade import create_draft_only

    draft = await create_draft_only(
        db_session, test_project_id, 1, content="只有这一句。"
    )
    await db_session.commit()
    deps = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(draft_id=draft.id, chapter_index=1),
        None,
        AgentRunBudget(),
        None,
    )
    with pytest.raises(ModelRetry, match="next_offset"):
        await inspect_current(SimpleNamespace(deps=deps), offset=8000)
    with pytest.raises(ModelRetry):
        await read_evidence(SimpleNamespace(deps=deps), evidence_id="invented")


def test_restricted_source_taints_summary_and_safe_error():
    recipient = TeamProjection(
        novel_id="a",
        scope_hash="b" * 64,
        recipient="reader",
        source_keys=frozenset({"public"}),
    )
    for novel, sources in [("other", {"public"}), ("a", {"public", "hidden"})]:
        with pytest.raises(ConflictError) as caught:
            project_team_artifact(
                artifact={"summary": "pretend sanitized"},
                source_keys=sources,
                novel_id=novel,
                scope_hash="b" * 64,
                recipient=recipient,
            )
        assert "hidden" not in str(caught.value)


def test_forged_quotes_and_unknown_sources_rejected():
    key = "a" * 64
    output = Investigation(
        summary="待核对",
        findings=[
            {
                "title": "信息来源",
                "claim": "角色已经知道秘密",
                "category": "character",
                "severity": "major",
                "claim_type": "inference",
                "evidence": [{"evidence_id": key, "excerpt": "伪造引文"}],
            }
        ],
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(evidence_refs={key: {"text": "他对此并不知情。"}})
    )
    with pytest.raises(ModelRetry):
        validate_investigation(ctx, output)
    output.findings[0].evidence[0].excerpt = "并不知情"
    assert validate_investigation(ctx, output) is output


def test_opposing_member_reports_cannot_vote_themselves_verified():
    from modules.assistant.teams.contracts import TeamAnswer
    from modules.assistant.teams.runner import validate_team_answer

    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            evidence_refs={
                "yes": {"text": "他声称自己知道。"},
                "no": {"text": "信中说他并不知道。"},
            },
            team_blueprint="deep_review",
            operations={},
        )
    )
    result = TeamAnswer(
        answer="两段证据矛盾，尚不能裁定。",
        findings=[
            {
                "title": "知识状态待核实",
                "summary": "仍有反证未解释",
                "kind": "suggestion",
                "evidence_ids": ["yes", "no"],
            }
        ],
        omissions=["没有领域复核回执"],
    )
    assert validate_team_answer(ctx, result) is result
    result.findings[0].kind = "issue"
    result.findings[0].domain_finding_id = "invented-majority-vote"
    with pytest.raises(ModelRetry, match="领域复核"):
        validate_team_answer(ctx, result)


async def test_team_start_idempotency_scope_and_switch(
    async_client,
    db_session,
    test_project_id,
    account_llm_connection,
    monkeypatch,
):
    from modules.writing.facade import create_draft_only

    settings = replace(
        get_settings(), assistant_enabled=True, assistant_deep_review_enabled=True
    )
    monkeypatch.setattr("modules.assistant.service.get_settings", lambda: settings)
    draft = await create_draft_only(
        db_session, test_project_id, 1, content="他仍遵守昨日的承诺。"
    )
    await db_session.commit()
    session = (
        await async_client.post(
            "/api/assistant/sessions", json={"novel_id": test_project_id}
        )
    ).json()["id"]
    payload = {
        "novel_id": test_project_id,
        "operation_id": str(uuid.uuid4()),
        "message": "查这一章",
        "blueprint": "deep_review",
        "context": {"page": "writing", "draft_id": draft.id, "chapter_index": 1},
    }
    url = f"/api/assistant/sessions/{session}/team-runs"
    response = await async_client.post(url, json=payload)
    assert response.status_code == 202, response.text
    assert (await async_client.post(url, json=payload)).json()["id"] == payload[
        "operation_id"
    ]
    assert (
        await async_client.post(url, json={**payload, "message": "另一任务"})
    ).status_code == 409
    response = await async_client.get(
        f"/api/assistant/runs/{payload['operation_id']}/collaboration",
        params={"novel_id": test_project_id},
    )
    assert response.status_code == 200
    assert "members" not in response.json()
    assert "checkpoint" not in response.text
    settings = replace(settings, assistant_deep_review_enabled=False)
    assert (
        await async_client.post(url, json={**payload, "operation_id": str(uuid.uuid4())})
    ).status_code == 409


def test_import_consult_cannot_select_another_group_and_readonly_teams_cannot_plan():
    from modules.assistant.schemas import WorkContext
    from modules.assistant.teams.contracts import TeamAnswer
    from modules.assistant.teams.runner import validate_team_answer

    task_id = str(uuid.uuid4())
    target = {
        "target_type": "import_review_resolution",
        "target_id": task_id,
        "target_path": "group-a",
    }
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            team_blueprint="import_consult",
            work=WorkContext(target=target),
            operations=None,
            evidence_refs={
                "a" * 64: {
                    "target_ref": target,
                    "inspection": {
                        "item": {
                            "summary": {
                                "groups": [{"key": "allowed", "fingerprint": "fresh"}]
                            }
                        }
                    },
                }
            },
        )
    )
    answer = TeamAnswer(
        answer="请审阅",
        plans=[
            {
                "key": "minimal",
                "title": "采用这组明确资料",
                "actions": [
                    {
                        "key": "accept",
                        "title": "采用",
                        "capability": "imports.accept_review",
                        "arguments": {
                            "task_id": task_id,
                            "candidate_keys": ["allowed"],
                            "expected_fingerprints": {"allowed": "fresh"},
                        },
                    }
                ],
            }
        ],
    )
    assert validate_team_answer(ctx, answer) is answer
    action = answer.plans[0].actions[0]
    original = dict(action.arguments)
    action.arguments = {
        **original,
        "candidate_keys": ["sibling"],
        "expected_fingerprints": {"sibling": "fresh"},
    }
    with pytest.raises(ModelRetry, match="原疑难组"):
        validate_team_answer(ctx, answer)
    action.arguments = original
    for blueprint in ("deep_review", "blind_reader", "research"):
        ctx.deps.team_blueprint = blueprint
        with pytest.raises(ModelRetry, match="不得包含修改方案"):
            validate_team_answer(ctx, answer)
