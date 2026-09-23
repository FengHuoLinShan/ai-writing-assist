"""Real materialization and queue paths preserve task, source and legacy boundaries."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.models import AsyncTask
from modules.assistant.contracts import ForecastDomainFact
from modules.assistant.forecast import preparation, runtime, service
from modules.assistant.forecast.context import materialize, scope_matches
from modules.assistant.forecast.contracts import (
    CandidateProposal,
    DecisionRequest,
    EvaluateRequest,
    FocusRequest,
    Horizon,
    PrepareRequest,
)
from modules.assistant.forecast.deterministic import calculate
from modules.assistant.forecast.models import ForecastCandidate
from modules.assistant.forecast.tests.test_forecasts import settings_on
from modules.assistant.models import AssistantNotice, AssistantRun
from modules.collaboration.contracts import Grant
from modules.collaboration.tests.test_cognition import seed_understanding
from modules.writing.facade import create_draft_only


async def test_cognition_exclusion_covers_old_drafts_and_scene_history(
    db_session, test_project_id
):
    from modules.collaboration.cognition import commit_changes
    from modules.evidence.facade import collect_creative_manifest
    from modules.story.outline_state.models import Scene

    db, nid = db_session, test_project_id
    old = await create_draft_only(db, nid, 1, content="青竹说渡口封锁。")
    current = await create_draft_only(db, nid, 1, content="青竹说渡口封锁，但无人确认。")
    focus_draft = await create_draft_only(db, nid, 3, content="林舟继续等候。")
    grant = Grant(
        resources=[{"kind": "writing_draft", "id": current.id}],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    receipt, _, change = await seed_understanding(db, nid, grant)
    await commit_changes(
        db,
        nid,
        operation_id=uuid4(),
        expected_commit_id=UUID(receipt["commit_id"]),
        changes=[{**change, "learned_at_chapter": 1}],
        read_set=[],
        method_version="test/v1",
    )
    focus = FocusRequest(
        client_context_id=uuid4(), focus_seq=0, page="writing", draft_id=focus_draft.id
    )
    assert (await materialize(db, nid, focus)).understanding["records"]
    excluded = await materialize(
        db,
        nid,
        focus.model_copy(update={"excluded_targets": [f"writing_draft:{old.id}"]}),
    )
    assert not excluded.understanding["records"]
    assert all(str(ref.resource_id) != current.id for ref in excluded.evidence)
    scene = Scene(
        novel_id=UUID(nid),
        scene_index=0,
        chapter_ids=[1],
        scene_chunks=[],
        status="draft",
    )
    db.add(scene)
    await db.flush()
    for fields in (
        {"scene_id": scene.id},
        {"target": {"resource_kind": "scene", "resource_id": str(scene.id)}},
    ):
        scene_focus = FocusRequest.model_validate(
            {**focus.model_dump(mode="json"), **fields}
        )
        assert not (await materialize(db, nid, scene_focus)).understanding["records"]
    historical = await collect_creative_manifest(
        db, nid, grant.model_copy(update={"cutoff_chapter": 1}), 1
    )
    assert not historical.cognition.records


async def test_cursor_focus_is_not_authority_and_exclusions_are_enforced(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    draft = await create_draft_only(
        db, nid, 1, content="前段。\n她关上门。\n未来的另一段。"
    )
    focus = FocusRequest(
        client_context_id=uuid4(),
        focus_seq=1,
        page="writing",
        draft_id=draft.id,
        expected_source_hash=draft.content_hash,
        cursor_offset=5,
        task_hint="polish",
    )
    original = await materialize(db, nid, focus)
    assert original.sources[0]["text"] == "她关上门。"
    assert "光标所在段落" in original.evidence[0].label
    shifted = await materialize(
        db, nid, focus.model_copy(update={"focus_seq": 2, "cursor_offset": 6})
    )
    assert original.scope.context_hash != shifted.scope.context_hash
    assert (
        original.scope.context_keys["presentation_focus"]
        != shifted.scope.context_keys["presentation_focus"]
    )
    candidate = SimpleNamespace(
        payload_json={"context_keys": original.scope.context_keys}
    )
    assert service.is_applicable(candidate, shifted)
    changed_task = await materialize(
        db, nid, focus.model_copy(update={"task_hint": "continue"})
    )
    assert not service.is_applicable(candidate, changed_task)
    changed_source = await materialize(
        db, nid, focus.model_copy(update={"cursor_offset": 1})
    )
    assert not service.is_applicable(candidate, changed_source)
    with pytest.raises(NotFoundError):
        await materialize(
            db,
            nid,
            focus.model_copy(update={"excluded_targets": [f"writing_draft:{draft.id}"]}),
        )
    selected_focus = FocusRequest.model_validate(
        {
            **focus.model_dump(mode="json"),
            "selected_range": {"start_offset": 4, "end_offset": 9},
        }
    )
    selected = await materialize(db, nid, selected_focus)
    work = await preparation.work_context(db, nid, selected)
    assert work.task_hint == "polish" and work.selection == "她关上门。"
    assert (work.selection_start, work.selection_end) == (4, 9)


async def test_old_queued_scope_and_operation_replay_keep_the_frozen_shape(
    db_session, test_project_id, monkeypatch
):
    settings_on(monkeypatch)
    db, nid = db_session, test_project_id
    draft = await create_draft_only(db, nid, 1, content="她仍未确认封锁。")
    await seed_understanding(
        db,
        nid,
        Grant(
            resources=[{"kind": "writing_draft", "id": draft.id}],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    request = EvaluateRequest(
        operation_id=uuid4(),
        context=FocusRequest(client_context_id=uuid4(), focus_seq=0, page="project"),
        horizon=Horizon(unit="decision"),
        requested_capabilities=["account.cost_gate.v1"],
    )
    response = await runtime.submit(db, nid, request)
    run = await db.get(AssistantRun, response.run_id)
    frozen = (
        await materialize(db, nid, request.context, include_understanding=False)
    ).scope.model_dump(mode="json")
    frozen.pop("context_keys")
    run.request_json = {**run.request_json, "scope": frozen}
    run.request_json.pop("understanding_enabled", None)
    old_request = request.model_dump(mode="json")
    assert "cursor_offset" not in old_request["context"]
    assert "excluded_targets" not in old_request["context"]
    run.request_hash = content_hash(old_request)
    await db.flush()
    replay = await runtime.submit(db, nid, request)
    assert replay.run_id == run.id
    assert scope_matches(
        (await materialize(db, nid, request.context, include_understanding=False)).scope,
        frozen,
    )
    task = await db.get(AsyncTask, run.task_id)
    task.status = "failed"
    task.meta = {**task.meta, "recovery_required": True}
    task.result = {**(task.result or {}), "recovery_required": True}
    await db.flush()
    assert (await runtime.view(db, nid, run.id)).can_resume
    assert (await runtime.resume(db, nid, run.id)).status == "pending"
    await runtime.execute(db, await db.get(AsyncTask, run.task_id))
    assert run.status == "completed"
    assert run.request_json["scope"] == frozen
    from sqlalchemy import select

    from modules.assistant.forecast.contracts import FeedRequest

    candidate = await db.scalar(
        select(ForecastCandidate).where(ForecastCandidate.run_id == run.id)
    )
    assert candidate is not None
    assert (await service.require_candidate(db, nid, candidate.id))[0].id == candidate.id
    assert (await service.feed(db, nid, FeedRequest(context=request.context))).items


async def test_domain_root_is_shared_and_notice_is_rechecked_after_the_lock(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    ctx = await materialize(
        db, nid, FocusRequest(client_context_id=uuid4(), focus_seq=0, page="project")
    )
    fact = ForecastDomainFact(
        capability_id="world.rule_impact.v1",
        subject="world:rule:one",
        title="规则影响",
        summary="同一条规则影响两处。",
        source={},
        scope_label="所查规则",
    )
    ctx.facts = [(fact, ctx.evidence[0])]
    rows, _ = calculate(ctx, ["world.rule_impact.v1", "assistant.cross_domain_root.v1"])
    other, _ = calculate(ctx, ["assistant.cross_domain_root.v1"])
    assert len(rows) == len(other) == 1 and rows[0]["issue_key"] == other[0]["issue_key"]
    run = AssistantRun(
        novel_id=UUID(nid),
        owner_id=ctx.scope.owner_id,
        request_hash="a" * 64,
        request_json={
            "protocol": "forecast_v1",
            "context": ctx.focus.model_dump(mode="json"),
        },
    )
    db.add(run)
    await db.flush()
    original = (await service.publish(db, run, ctx, rows))[0]
    notice = await service.require_current_notice(db, original)
    version = notice.row_version
    next_run = AssistantRun(
        novel_id=UUID(nid),
        owner_id=ctx.scope.owner_id,
        request_hash="b" * 64,
        request_json=run.request_json,
    )
    db.add(next_run)
    await db.flush()
    newer = (await service.publish(db, next_run, ctx, other))[0]
    assert (await service.require_current_notice(db, newer)).row_version == version + 1
    with pytest.raises(ConflictError, match="已有更新"):
        await service.require_current_notice(db, original)


async def test_declined_direction_survives_read_and_rewording_without_hiding_the_fact(
    db_session, test_project_id, monkeypatch
):
    settings_on(monkeypatch)
    db, nid = db_session, test_project_id
    ctx = await materialize(
        db, nid, FocusRequest(client_context_id=uuid4(), focus_seq=0, page="project")
    )
    fact = ForecastDomainFact(
        capability_id="world.rule_impact.v1",
        subject="world:rule:one",
        title="规则影响",
        summary="同一条规则影响两处。",
        source={},
        scope_label="所查规则",
    )
    ctx.facts = [(fact, ctx.evidence[0])]
    items, _ = calculate(ctx, ["world.rule_impact.v1"])
    payload = items[0]["payload"]
    payload["proposal"]["directions"] = [
        {
            "direction_id": key,
            "title": title,
            "condition": condition,
            "proposal": proposal,
            "narrative_commitment": "low",
        }
        for key, title, condition, proposal in [
            ("ask", "追问", "想解开疑问时", "询问来意。"),
            ("leave", "离开", "想保留悬念时", "先回家。"),
        ]
    ]
    payload["actions"] = preparation.actions_for(
        CandidateProposal.model_validate(payload["proposal"]),
        ctx,
        "story.open_question.v1",
    )
    run = AssistantRun(
        novel_id=UUID(nid),
        owner_id=ctx.scope.owner_id,
        request_hash="a" * 64,
        request_json={
            "protocol": "forecast_v1",
            "context": ctx.focus.model_dump(mode="json"),
        },
    )
    db.add(run)
    await db.flush()
    candidate = (await service.publish(db, run, ctx, items))[0]
    notice = await service.require_current_notice(db, candidate)
    request = PrepareRequest(
        operation_id=uuid4(),
        expected_assessment_hash=candidate.assessment_hash,
        action_id="project.prepare_task",
        context=ctx.focus,
    )
    preview = await preparation.prepare(db, nid, candidate.id, request)
    child = await db.get(AssistantRun, preview.run_id)
    # Legacy preparation idempotency used the pre-addition serialized request.
    child.request_hash = content_hash(
        [str(candidate.id), request.model_dump(mode="json")]
    )
    parent = {
        key: value
        for key, value in child.request_json["forecast_parent"].items()
        if key != "direction_id"
    }
    child.request_json = {**child.request_json, "forecast_parent": parent}
    assert (
        await preparation.prepare(db, nid, candidate.id, request)
    ).status == "preview_ready"
    await service.decide(
        db,
        nid,
        candidate.id,
        DecisionRequest(
            expected_notice_version=notice.row_version,
            expected_assessment_hash=candidate.assessment_hash,
            action="not_this_direction",
            direction_id="ask",
        ),
    )
    view = service.candidate_view(candidate, notice)
    assert [direction.direction_id for direction in view.directions] == ["leave"]
    assert view.statements
    assert (await preparation.receipt(db, nid, child)).status == "stale"
    with pytest.raises(ConflictError, match="已被暂缓"):
        await preparation.prepare(
            db,
            nid,
            candidate.id,
            request.model_copy(
                update={
                    "operation_id": uuid4(),
                    "action_id": "story.prepare_information_plan.ask",
                }
            ),
        )
    await service.decide(
        db,
        nid,
        candidate.id,
        DecisionRequest(
            expected_notice_version=notice.row_version,
            expected_assessment_hash=candidate.assessment_hash,
            action="read",
        ),
    )
    for index in range(10):
        db.add(
            AssistantNotice(
                novel_id=UUID(nid),
                fingerprint=f"ordinary-{index}",
                kind="suggestion",
                title="已读",
                summary="普通事项",
                status="read",
                disposition="read",
                result_ref_json={
                    "forecast_v1": {
                        "decision_boundary": service.decision_boundary(ctx),
                        "declined_choices": {},
                    }
                },
            )
        )
    await db.flush()
    choices = await service.explicit_decisions(db, ctx)
    assert choices[0]["disposition"] == "not_this_direction"
    assert choices[0]["choice"]["directions"][0]["proposal"] == "询问来意。"
    # Display names and generated IDs do not create a new author choice.
    payload["proposal"]["directions"][0].update(direction_id="renamed", title="温和追问")
    next_run = AssistantRun(
        novel_id=UUID(nid),
        owner_id=ctx.scope.owner_id,
        request_hash="b" * 64,
        request_json=run.request_json,
    )
    db.add(next_run)
    await db.flush()
    newer = (await service.publish(db, next_run, ctx, items))[0]
    assert [
        direction.direction_id
        for direction in service.candidate_view(newer, notice).directions
    ] == ["leave"]
