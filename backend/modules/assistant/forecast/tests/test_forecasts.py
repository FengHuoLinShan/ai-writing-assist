"""Saved-only reading, provider-only analysis, precise decisions and stale results."""

import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from core.config import get_settings
from core.errors import ConflictError
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.assistant.forecast import runtime, service
from modules.assistant.forecast.contracts import FocusRequest
from modules.assistant.forecast.models import ForecastCandidate
from modules.assistant.models import AssistantNotice
from modules.writing.facade import create_draft_only


def settings_on(monkeypatch):
    settings = replace(
        get_settings(),
        assistant_enabled=True,
        assistant_forecast_enabled=True,
        assistant_forecast_semantic_enabled=True,
    )
    for module in ("runtime", "service", "api", "policy"):
        monkeypatch.setattr(
            f"modules.assistant.forecast.{module}.get_settings", lambda: settings
        )


async def test_provider_only_forecast_read_decide_and_no_old_resurrection(
    async_client, db_session, test_project_id, account_llm_connection, monkeypatch
):
    settings_on(monkeypatch)
    db, nid = db_session, test_project_id
    draft = await create_draft_only(
        db, nid, 1, "小镇", "她把铜铃放进衣袋。铁匠欲言又止。"
    )
    focus = {
        "client_context_id": str(uuid4()),
        "focus_seq": 1,
        "page": "writing",
        "draft_id": draft.id,
        "expected_source_hash": draft.content_hash,
        "editor_state": "saved",
    }
    url = "/api/assistant/forecasts"
    before = await db.scalar(select(func.count()).select_from(AsyncTask))
    response = await async_client.post(
        f"{url}/feed", params={"novel_id": nid}, json={"context": focus}
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "not_checked"
    assert response.json()["references"][0]["resource_id"] == draft.id
    assert await db.scalar(select(func.count()).select_from(AsyncTask)) == before
    calls = []
    choices = []

    async def provider(self, request):
        assert not db.in_transaction()
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])
        calls.append(schema["title"])
        if schema["title"] == "ForecastOutput":
            inputs = json.loads(
                next(m.content for m in request.messages if m.role == "user")
            )
            assert inputs["author_decisions"] == choices
            value = {
                "items": [
                    {
                        "capability_index": 0,
                        "question_kind": "continuation",
                        "anchor_evidence_id": "source_0",
                        "anchor_text": "铁匠欲言又止",
                        "proposal": {
                            "title": "可以轻声追问，也可以先离开",
                            "kind": "creative_opportunity",
                            "statements": [
                                {
                                    "text": "铁匠欲言又止。",
                                    "basis": "observed",
                                    "evidence_ids": ["source_0"],
                                }
                            ],
                            "why_now": "主角仍在铁匠身边，可以回应这一反应。",
                            "directions": [
                                {
                                    "direction_id": "light_touch",
                                    "title": "轻量回应",
                                    "condition": "如果想保持局部节奏",
                                    "proposal": "让她留下一句询问，不急于解释铜铃。",
                                    "narrative_commitment": "low",
                                    "may_leave_open": True,
                                }
                            ],
                            "unknowns": ["铜铃也可能只是普通遗物"],
                            "verdict": "propose",
                        },
                    }
                ]
            }
        else:
            assert schema["title"] == "AuditVerdictOutput"
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

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    body = {
        "operation_id": str(uuid4()),
        "context": focus,
        "horizon": {"unit": "scene"},
        "requested_capabilities": ["writing.next_beat.v1"],
    }
    response = await async_client.post(
        f"{url}/evaluate", params={"novel_id": nid}, json=body
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    from modules.assistant.models import AssistantRun

    run = await db.get(AssistantRun, UUID(run_id))
    original_compute_key = run.request_json["compute_key"]
    task = await db.get(AsyncTask, run.task_id)
    await runtime.execute(db, task)
    response = await async_client.post(
        f"{url}/feed",
        params={"novel_id": nid},
        json={"context": {**focus, "editor_state": "dirty", "focus_seq": 2}},
    )
    assert response.status_code == 200, response.text
    candidate = response.json()["items"][0]
    assert candidate["basis_label"].startswith("基于上次保存")
    assert calls == ["ForecastOutput", "AuditVerdictOutput"]
    prepare_body = {
        "operation_id": str(uuid4()),
        "expected_assessment_hash": candidate["assessment_hash"],
        "action_id": "project.prepare_task",
        "context": focus,
    }
    from modules.assistant.models import AssistantActionBatch
    from modules.project.models import ProjectAuthorTask

    task_count = await db.scalar(select(func.count()).select_from(ProjectAuthorTask))
    preview = await async_client.post(
        f"{url}/candidates/{candidate['candidate_id']}/prepare",
        params={"novel_id": nid},
        json=prepare_body,
    )
    assert preview.status_code == 200, preview.text
    preview = preview.json()
    assert (
        preview["status"] == "preview_ready"
        and preview["domain_write_performed"] is False
    )
    assert (
        await db.scalar(select(func.count()).select_from(ProjectAuthorTask)) == task_count
    )
    replay = await async_client.post(
        f"{url}/candidates/{candidate['candidate_id']}/prepare",
        params={"novel_id": nid},
        json=prepare_body,
    )
    assert replay.json()["batch_id"] == preview["batch_id"]
    assert await db.scalar(select(func.count()).select_from(AssistantActionBatch)) == 1
    adopted = await async_client.post(
        f"/api/assistant/batches/{preview['batch_id']}/decide",
        json={
            "novel_id": nid,
            "fingerprint": preview["batch_fingerprint"],
            "confirmed": True,
            "selected": ["selected"],
        },
    )
    assert adopted.status_code == 200, adopted.text
    assert adopted.json()["status"] == "completed"
    assert (
        await db.scalar(select(func.count()).select_from(ProjectAuthorTask))
        == task_count + 1
    )
    assert calls == ["ForecastOutput", "AuditVerdictOutput"]
    decision = {
        "expected_notice_version": candidate["notice_version"],
        "expected_assessment_hash": candidate["assessment_hash"],
        "action": "as_ordinary_detail",
    }
    response = await async_client.post(
        f"{url}/candidates/{candidate['candidate_id']}/decision",
        params={"novel_id": nid},
        json=decision,
    )
    assert response.status_code == 200, response.text
    assert response.json()["domain_state_changed"] is False
    response = await async_client.post(
        f"{url}/candidates/{candidate['candidate_id']}/decision",
        params={"novel_id": nid},
        json=decision,
    )
    assert response.status_code == 409
    notice = await db.scalar(
        select(AssistantNotice).where(AssistantNotice.novel_id == UUID(nid))
    )
    assert notice.disposition == "as_ordinary_detail"
    repeated = await async_client.post(
        f"{url}/evaluate",
        params={"novel_id": nid},
        json={**body, "operation_id": str(uuid4())},
    )
    assert repeated.status_code == 202, repeated.text
    next_run = await db.get(AssistantRun, UUID(repeated.json()["run_id"]))
    choices = next_run.request_json["author_decisions"]
    assert choices[0]["disposition"] == "as_ordinary_detail"
    assert choices[0]["choice"]["question"] == "可以轻声追问，也可以先离开"
    assert next_run.request_json["compute_key"] != original_compute_key
    task = await db.get(AsyncTask, next_run.task_id)
    await runtime.execute(db, task)
    assert calls == ["ForecastOutput", "AuditVerdictOutput"] * 2

    new_row = await db.scalar(
        select(ForecastCandidate).where(
            ForecastCandidate.run_id == UUID(repeated.json()["run_id"])
        )
    )
    row = await db.get(ForecastCandidate, UUID(candidate["candidate_id"]))
    assert new_row.issue_key == row.issue_key
    await db.refresh(notice)
    assert notice.disposition == "as_ordinary_detail"
    from modules.assistant.forecast.contracts import DecisionRequest

    await service.decide(
        db,
        nid,
        new_row.id,
        DecisionRequest(
            expected_notice_version=notice.row_version,
            expected_assessment_hash=new_row.assessment_hash,
            action="reopen",
        ),
    )
    assert row.validation_state == "valid"
    new_row.validation_state = "stale"
    await db.flush()
    response = await async_client.post(
        f"{url}/feed", params={"novel_id": nid}, json={"context": focus}
    )
    assert response.json()["items"] == []
    assert calls == ["ForecastOutput", "AuditVerdictOutput"] * 2

    # Moving the same physical quotation keeps the issue; unrelated replacement
    # at that offset must not inherit a declined direction from a different issue.
    for quote, inherited in [("铁匠欲言又止", True), ("孩子买来新鞋子", False)]:
        content = "夜深了。她把铜铃放进衣袋。" + quote + "。"
        saved = await create_draft_only(db, nid, 1, "改过标题", content)
        start = content.index(quote)
        item = {
            "issue_key": "fresh-issue",
            "capability_id": row.capability_id,
            "payload": {
                "anchor": {
                    **row.payload_json["anchor"],
                    "resource_id": saved.id,
                    "start": start,
                    "end": start + len(quote),
                }
            },
        }
        next_run = await db.get(AssistantRun, UUID(repeated.json()["run_id"]))
        identity = await service.inherit_issue_identity(db, next_run, item, {})
        assert (identity == row.issue_key) is inherited


async def test_character_response_v2_runs_through_scene_feed_and_writing_preview(
    async_client, db_session, test_project_id, account_llm_connection, monkeypatch
):
    settings_on(monkeypatch)
    from modules.assistant.models import AssistantRun
    from modules.story.outline_state.repositories import SceneRepository
    from modules.story.outline_state.schemas import SceneCreate
    from modules.world.models.character import Character
    from modules.world.models.core import CoreEntity

    db, nid = db_session, test_project_id
    viewpoint_id, other_id = uuid4(), uuid4()
    db.add_all(
        [
            CoreEntity(
                id=viewpoint_id,
                novel_id=UUID(nid),
                entity_type="character",
                name="岑遥",
                summary="沿河找回丢失的钥匙",
                hidden_truth="POV_SECRET_NOT_KNOWN_TO_CENYAO",
                reveal_level="author_only",
                status="canonical",
            ),
            Character(
                entity_id=viewpoint_id,
                novel_id=UUID(nid),
                name="岑遥",
                personality="谨慎，习惯先听再答",
                secret="POV_CHARACTER_SECRET_NOT_KNOWN_TO_CENYAO",
                status="canonical",
            ),
            CoreEntity(
                id=other_id,
                novel_id=UUID(nid),
                entity_type="character",
                name="旁观者隐名",
                summary="OTHER_CHARACTER_SECRET_NOT_KNOWN_TO_CENYAO",
                hidden_truth="OTHER_HIDDEN_TRUTH_NOT_KNOWN_TO_CENYAO",
                reveal_level="author_only",
                status="canonical",
            ),
            Character(
                entity_id=other_id,
                novel_id=UUID(nid),
                name="旁观者隐名",
                secret="OTHER_CHARACTER_SECRET_NOT_KNOWN_TO_CENYAO",
                status="canonical",
            ),
        ]
    )
    await db.flush()
    scene = await SceneRepository().create(
        db,
        UUID(nid),
        SceneCreate(
            scene_index=2,
            title="河边停步",
            goal="回忆丢失钥匙的经过",
            must_happen="AUTHOR_FUTURE_PLAN_MUST_NOT_ENTER_ROLE_CONTEXT",
            chapter_ids=["1"],
            pov_character_id=str(viewpoint_id),
            status="canonical",
        ),
    )
    draft = await create_draft_only(
        db,
        nid,
        1,
        "河边停步",
        "MANUSCRIPT_SECRET_NOT_FOR_ROLE_FORECAST",
    )
    focus = {
        "client_context_id": str(uuid4()),
        "focus_seq": 1,
        "page": "scene",
        "scene_id": str(scene.id),
        "draft_id": draft.id,
        "expected_source_hash": draft.content_hash,
        "editor_state": "saved",
        "explicit_instruction": "保持克制，不急于解释钥匙的来历",
    }
    calls = []
    llm_inputs = []
    invalid_basis = False

    async def provider(self, request):
        assert not db.in_transaction()
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])
        calls.append(schema["title"])
        if schema["title"] == "CharacterResponseForecastOutput":
            value = json.loads(
                next(
                    message.content
                    for message in request.messages
                    if message.role == "user"
                )
            )
            llm_inputs.append(value)
            serialized = json.dumps(value, ensure_ascii=False)
            for secret in (
                "POV_SECRET_NOT_KNOWN_TO_CENYAO",
                "POV_CHARACTER_SECRET_NOT_KNOWN_TO_CENYAO",
                "OTHER_CHARACTER_SECRET_NOT_KNOWN_TO_CENYAO",
                "OTHER_HIDDEN_TRUTH_NOT_KNOWN_TO_CENYAO",
                "AUTHOR_FUTURE_PLAN_MUST_NOT_ENTER_ROLE_CONTEXT",
                "MANUSCRIPT_SECRET_NOT_FOR_ROLE_FORECAST",
            ):
                assert secret not in serialized
            assert value["sources"][0]["text"]
            assert value["intent"].startswith("保持克制")
            option = {
                "direction_id": "protect_first",
                "motive": "protect",
                "motive_reason": "先保护自己的不安，不让追问扩大",
                "trigger": "如果对方继续追问钥匙的去向",
                "behavior": ["先把手收回袖中", "停顿后只问对方看见了什么"],
                "expression": "眼神短暂落向河面",
                "body_language": "肩膀收紧，脚尖转向岸边",
                "voice": {
                    "line": "你最后一次看见它是什么时候？",
                    "delivery": "声音放轻，句尾收住",
                    "subtext": "我还没准备好解释自己为何在找它",
                },
                "psychology": "想确认线索，同时避免暴露焦虑",
                "psychological_trigger": "对方开始追问失物的意义",
                "defense": "把问题转回可核对的经过",
                "notices": ["对方回避视线"],
                "overlooks": ["没有注意到对方手上的泥水"],
                "change": {
                    "emotion": "从警惕转为略微集中",
                    "relationship": "信任仍未验证",
                    "goal": "先核实目击时间",
                },
                "basis": [
                    {
                        "kind": "manuscript" if invalid_basis else "author_condition",
                        "evidence_ids": ["source_0"],
                        "quote": (
                            "未提供的正文片段"
                            if invalid_basis
                            else "保持克制，不急于解释钥匙的来历"
                        ),
                        "note": "作者要求保持克制，这只是表达边界",
                    }
                ],
                "assumptions": ["对话仍在继续"],
            }
            second = {
                **option,
                "direction_id": "understand_first",
                "motive": "understand",
                "motive_reason": "把不确定感转成具体核对",
                "behavior": ["先复述听到的时间", "请对方指出当时的位置"],
                "trigger": "如果现场没有迫近危险",
            }
            answer = {
                "items": [
                    {
                        "proposal": {
                            "title": "先守住边界，再核对线索",
                            "why_now": (
                                "当前场景需要选择回应尺度；候选没有成为已发生事实。"
                            ),
                            "options": [option, second],
                            "unknowns": ["没有已确认的人物时点状态"],
                        }
                    }
                ]
            }
        else:
            assert schema["title"] == "AuditVerdictOutput"
            answer = {
                "verdict": "pass",
                "dimensions": [
                    {"dimension": key, "checked": True}
                    for key in ("prior_prose", "world_rules", "outline")
                ],
            }
        return LLMCallResponse(
            content=json.dumps(answer, ensure_ascii=False),
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    url = "/api/assistant/forecasts"
    body = {
        "operation_id": str(uuid4()),
        "context": focus,
        "horizon": {"unit": "scene"},
        "requested_capabilities": ["story.character_response.v1"],
    }
    submitted = await async_client.post(
        f"{url}/evaluate", params={"novel_id": nid}, json=body
    )
    assert submitted.status_code == 202, submitted.text
    run = await db.get(AssistantRun, UUID(submitted.json()["run_id"]))
    assert run.request_json["selected_capabilities"] == ["story.character_response.v2"]
    assert run.request_json["understanding_enabled"] is False
    await runtime.execute(db, await db.get(AsyncTask, run.task_id))
    assert calls == ["CharacterResponseForecastOutput", "AuditVerdictOutput"]
    assert llm_inputs[0]["sources"][0]["text"]

    # A persisted character_response.v1 result uses its original materializer and
    # response shape when a new Scene feed is rendered.
    from datetime import UTC, datetime, timedelta

    from infrastructure.llm.collaboration import content_hash
    from modules.assistant.forecast.context import materialize
    from modules.assistant.forecast.models import ForecastDependency
    from modules.assistant.forecast.ranking import (
        assessment_hash,
        notice_key,
        stable_issue_key,
    )

    legacy_ctx = await materialize(
        db,
        nid,
        FocusRequest.model_validate(focus),
        capabilities=["story.character_response.v1"],
    )
    legacy_operation_id = uuid4()
    legacy_run_id = uuid4()
    legacy_request = {
        "protocol": "forecast_v1",
        "context": focus,
        "selected_capabilities": ["story.character_response.v1"],
        "understanding_enabled": True,
        "scope": legacy_ctx.scope.model_dump(mode="json"),
    }
    legacy_run = AssistantRun(
        id=legacy_run_id,
        novel_id=UUID(nid),
        owner_id=run.owner_id,
        operation_id=legacy_operation_id,
        mode="author",
        status="completed",
        request_hash=content_hash(legacy_request),
        request_json=legacy_request,
        budget_json={},
        checkpoint_json={"phase": "done"},
        result_json={"completion": "complete"},
    )
    db.add(legacy_run)
    legacy_issue = stable_issue_key(
        "story.character_response.v1",
        legacy_ctx.scope.audience_key,
        ["scene", str(scene.id)],
        "reaction",
    )
    legacy_proposal = {
        "title": "历史人物反应候选",
        "kind": "creative_opportunity",
        "statements": [
            {
                "text": "旧版候选内容保留原格式。",
                "basis": "proposed",
                "evidence_ids": [],
                "assumptions": [],
            }
        ],
        "why_now": "这是已保存的 v1 候选。",
        "directions": [
            {
                "direction_id": "legacy_option",
                "title": "轻声回应",
                "condition": "如果作者仍想回应",
                "proposal": "先问一个可核验的问题。",
                "possible_effects": [],
                "assumptions": [],
                "narrative_commitment": "low",
                "may_leave_open": True,
            }
        ],
        "unknowns": [],
        "verdict": "propose",
    }
    legacy_payload = {
        "proposal": legacy_proposal,
        "evidence": [ref.model_dump(mode="json") for ref in legacy_ctx.evidence],
        "knowledge_review": {"status": "legacy_saved"},
        "ranking": {"evidence": 1},
        "actions": [],
        "navigation": {"page": "scene", "scene_id": str(scene.id)},
        "context_keys": legacy_ctx.scope.context_keys,
        "understanding_enabled": True,
    }
    legacy_id = uuid4()
    dependencies = legacy_ctx.dependencies
    legacy_candidate = ForecastCandidate(
        id=legacy_id,
        novel_id=UUID(nid),
        run_id=legacy_run_id,
        ordinal=0,
        issue_key=legacy_issue,
        audience_key=legacy_ctx.scope.audience_key,
        scope_hash=legacy_ctx.scope.scope_hash,
        context_hash=legacy_ctx.scope.context_hash,
        assessment_hash=assessment_hash(legacy_payload, dependencies),
        capability_id="story.character_response.v1",
        protocol_version="forecast_v1",
        output_kind=legacy_proposal["kind"],
        tier="next",
        policy_generation=legacy_ctx.scope.policy_generation,
        payload_json=legacy_payload,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(legacy_candidate)
    for dependency in dependencies:
        db.add(
            ForecastDependency(
                novel_id=UUID(nid),
                candidate_id=legacy_id,
                **{
                    **dependency,
                    "resource_id": UUID(str(dependency["resource_id"])),
                },
            )
        )
    db.add(
        AssistantNotice(
            novel_id=UUID(nid),
            fingerprint=notice_key(nid, legacy_candidate.audience_key, legacy_issue),
            kind="suggestion",
            title=legacy_proposal["title"],
            summary=legacy_proposal["why_now"],
            result_ref_json={
                "type": "forecast",
                "forecast_v1": {
                    "candidate_id": str(legacy_id),
                    "assessment_hash": legacy_candidate.assessment_hash,
                    "issue_key": legacy_issue,
                },
            },
        )
    )
    await db.flush()

    feed = await async_client.post(
        f"{url}/feed", params={"novel_id": nid}, json={"context": focus}
    )
    assert feed.status_code == 200, feed.text
    cards = feed.json()["items"]
    card = next(
        item for item in cards if item["capability_id"] == "story.character_response.v2"
    )
    legacy_card = next(
        item for item in cards if item["capability_id"] == "story.character_response.v1"
    )
    assert "character_response" not in legacy_card
    legacy_detail = await async_client.get(
        f"{url}/candidates/{legacy_id}", params={"novel_id": nid}
    )
    assert legacy_detail.status_code == 200, legacy_detail.text
    assert "character_response" not in legacy_detail.json()
    assert card["capability_id"] == "story.character_response.v2"
    assert card["character_response"]["character_name"] == "岑遥"
    assert card["character_response"]["schema_version"] == "character_response.v2"
    assert [item["motive"] for item in card["character_response"]["options"]] == [
        "protect",
        "understand",
    ]
    assert card["character_response"]["source_gaps"]
    action = next(
        item
        for item in card["actions"]
        if item["action_id"].startswith("writing.prepare_candidate.")
    )
    preview = await async_client.post(
        f"{url}/candidates/{card['candidate_id']}/prepare",
        params={"novel_id": nid},
        json={
            "operation_id": str(uuid4()),
            "expected_assessment_hash": card["assessment_hash"],
            "action_id": action["action_id"],
            "context": focus,
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] == "preview_ready"

    invalid_basis = True
    failure_focus = {
        **focus,
        "focus_seq": 2,
        "explicit_instruction": "保持克制；验证不接受未提供的正文来源",
    }
    failed_submission = await async_client.post(
        f"{url}/evaluate",
        params={"novel_id": nid},
        json={
            "operation_id": str(uuid4()),
            "context": failure_focus,
            "horizon": {"unit": "scene"},
            "requested_capabilities": ["story.character_response.v2"],
        },
    )
    assert failed_submission.status_code == 202, failed_submission.text
    failed_run = await db.get(AssistantRun, UUID(failed_submission.json()["run_id"]))
    candidate_count = await db.scalar(select(func.count()).select_from(ForecastCandidate))
    with pytest.raises(ConflictError, match="候选依据引用了本轮未提供的资料类型"):
        await runtime.execute(db, await db.get(AsyncTask, failed_run.task_id))
    await db.refresh(failed_run)
    assert failed_run.status == "failed"
    assert failed_run.result_json["error_code"] == "UNKNOWN_EVIDENCE"
    assert (
        await db.scalar(select(func.count()).select_from(ForecastCandidate))
        == candidate_count
    )


async def test_dirty_compute_and_spoofed_automatic_trigger_are_rejected(
    async_client, db_session, test_project_id, monkeypatch
):
    settings_on(monkeypatch)
    draft = await create_draft_only(
        db_session, test_project_id, 1, "草稿", "普通的一天。"
    )
    body = {
        "operation_id": str(uuid4()),
        "context": {
            "client_context_id": str(uuid4()),
            "focus_seq": 0,
            "page": "writing",
            "draft_id": draft.id,
            "editor_state": "dirty",
        },
        "horizon": {"unit": "scene"},
    }
    response = await async_client.post(
        "/api/assistant/forecasts/evaluate",
        params={"novel_id": test_project_id},
        json=body,
    )
    assert response.status_code == 422
    body["context"]["editor_state"] = "saved"
    body["trigger"] = "saved_change"
    response = await async_client.post(
        "/api/assistant/forecasts/evaluate",
        params={"novel_id": test_project_id},
        json=body,
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "page", ["today", "project", "account", "imports", "world", "map", "rag", "assistant"]
)
async def test_domain_receipts_are_pure_reads_and_deterministic_calculation(
    db_session, test_project_id, page
):
    from modules.assistant.forecast.context import materialize
    from modules.assistant.forecast.contracts import FocusRequest
    from modules.assistant.forecast.deterministic import calculate
    from modules.assistant.forecast.registry import CAPABILITIES

    before = await db_session.scalar(select(func.count()).select_from(AsyncTask))
    focus = FocusRequest(client_context_id=uuid4(), focus_seq=1, page=page)
    context = await materialize(db_session, test_project_id, focus)
    rows, missing = calculate(context, list(CAPABILITIES))
    assert "account.cost_gate.v1" not in missing
    assert any(row["capability_id"] == "account.cost_gate.v1" for row in rows)
    assert await db_session.scalar(select(func.count()).select_from(AsyncTask)) == before
    assert (await materialize(db_session, test_project_id, focus)).scope == context.scope
