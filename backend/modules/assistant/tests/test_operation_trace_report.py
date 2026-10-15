from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from sqlalchemy import select

from app.assistant_operation_registry import assistant_notice_operations
from core.container import container_scope
from core.service_keys import ASSISTANT_OPERATION_TRACE
from modules.account.facade import current_account_id
from modules.assistant import operation_trace_report as report_module
from modules.assistant.contracts import AssistantOperation
from modules.assistant.goal_runs.contracts import GoalPlan, GoalStep
from modules.assistant.goal_runs.service import (
    _goal_usage_delta,
    _record_goal_plan_approval,
)
from modules.assistant.operation_trace_models import (
    AssistantOperationSequenceAggregate,
    AssistantOperationTrace,
    AssistantOperationTraceAggregate,
    AssistantOperationTraceLifecycleAggregate,
    AssistantOperationTraceMetricAggregate,
    AssistantOperationTraceParameterAggregate,
)
from modules.assistant.operation_trace_report import build_operation_trace_report
from modules.assistant.operation_trace_service import (
    _lifecycle_daily_counts,
    _parameter_profile,
    archive_expired_operation_traces,
    operation_trace_sequence_records,
    operation_trace_sequences,
)


def _row(
    event: str,
    event_id: int,
    occurred_at: datetime,
    call_id: UUID | None,
    *,
    op_id: str = "project.add_task",
    run_id: UUID | None = None,
    session_id: UUID | None = None,
    duration_ms: int | None = None,
    usage: dict | None = None,
    parameters: dict | None = None,
):
    return SimpleNamespace(
        id=event_id,
        event_type=event,
        occurred_at=occurred_at,
        call_id=call_id,
        run_id=run_id,
        session_id=session_id,
        op_id=op_id,
        duration_ms=duration_ms,
        usage=usage,
        parameter_summary=parameters
        or {"fields": {}, "unknown_fields": {"present": False}},
    )


def test_lifecycle_counts_dedupe_repeated_confirmations_and_require_event_order():
    day = datetime(2026, 10, 1, 12, tzinfo=UTC)
    accepted = uuid4()
    unknown = uuid4()
    crossed = uuid4()
    rows = [
        _row("proposed", 1, day, accepted),
        _row("edited", 2, day + timedelta(seconds=1), accepted),
        _row("confirmed", 3, day + timedelta(seconds=2), accepted),
        _row("confirmed", 4, day + timedelta(seconds=3), accepted),
        _row("executed", 5, day + timedelta(seconds=4), accepted),
        _row("restored", 6, day + timedelta(seconds=5), accepted),
        _row("proposed", 7, day, unknown),
        _row("outcome_unknown", 8, day + timedelta(seconds=1), unknown),
        _row("confirmed", 9, day, crossed),
        _row("edited", 10, day + timedelta(seconds=1), crossed),
        _row("proposed", 11, day + timedelta(seconds=2), crossed),
        _row("failed", 12, day + timedelta(seconds=3), crossed),
    ]

    counts = _lifecycle_daily_counts(rows)[(day.date(), "project.add_task")]

    assert counts["proposed_count"] == 3
    assert counts["accepted_count"] == 1
    assert counts["edited_accepted_count"] == 1
    assert counts["confirmed_event_count"] == 3
    assert counts["outcome_unknown_count"] == 1
    assert counts["executed_count"] == 1
    assert counts["failed_execution_count"] == 1
    assert counts["matched_reversal_count"] == 1
    assert counts["ambiguous_count"] == 0
    assert counts["unmatched_decision_count"] == 1


def test_terminal_sequence_is_sorted_and_repeated_terminal_state_counts_once():
    day = datetime(2026, 10, 2, 12, tzinfo=UTC)
    run_id = uuid4()
    call_a = uuid4()
    call_b = uuid4()
    rows = [
        _row("executed", 1, day, call_a, op_id="project.add_task", run_id=run_id),
        _row("failed", 2, day, call_a, op_id="project.add_task", run_id=run_id),
        _row("executed", 3, day, call_b, op_id="world.dossier.entry.edit", run_id=run_id),
    ]

    assert operation_trace_sequences(rows) == [
        (day.date(), ["project.add_task", "world.dossier.entry.edit"])
    ]
    counts = _lifecycle_daily_counts(rows)[(day.date(), "project.add_task")]
    assert counts["executed_count"] == 0
    assert counts["failed_execution_count"] == 1


def test_unlinked_terminal_events_remain_unmeasurable_and_mark_sequence_incomplete():
    day = datetime(2026, 10, 2, 12, tzinfo=UTC)
    rows = [
        _row("executed", 1, day, None, run_id=uuid4()),
        _row("executed", 2, day + timedelta(seconds=1), None, run_id=uuid4()),
        _row("outcome_unknown", 3, day + timedelta(seconds=2), None, run_id=uuid4()),
    ]

    counts = _lifecycle_daily_counts(rows)[(day.date(), "project.add_task")]
    sequences = operation_trace_sequence_records(rows)

    assert counts["executed_count"] == 0
    assert counts["failed_execution_count"] == 0
    assert counts["unknown_execution_count"] == 0
    assert counts["unlinked_execution_events"] == 3
    assert len(sequences) == 3
    assert all(not complete for _date, _operations, complete in sequences)


def test_parameter_profiles_drop_content_hashes_values_and_exact_lengths():
    profile = _parameter_profile(
        {
            "fields": {
                "instruction": {
                    "present": True,
                    "type": "string",
                    "length": 934,
                    "project_hash": "salted-text-hash",
                },
                "mode": {"present": True, "type": "boolean", "value": True},
                "target_id": {"present": True, "type": "string", "length": 36},
            },
            "unknown_fields": {"present": True},
        }
    )

    serialized = json.dumps(profile, ensure_ascii=False)
    assert profile["fields"]["instruction"]["length"] == "50+"
    assert profile["fields"]["mode"] == {"present": True, "type": "boolean"}
    assert "salted-text-hash" not in serialized
    assert "934" not in serialized
    assert "target_id" in serialized


def test_goal_usage_delta_uses_only_exact_step_ledger_differences():
    before = SimpleNamespace(
        legacy_untracked=False,
        requests_started=3,
        requests_settled=3,
        requests_unknown=0,
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4),
    )
    after = SimpleNamespace(
        legacy_untracked=False,
        requests_started=5,
        requests_settled=4,
        requests_unknown=0,
        usage=SimpleNamespace(prompt_tokens=15, completion_tokens=8),
    )

    delta = _goal_usage_delta(before, after)

    assert delta == {
        "requests": 2,
        "prompt_tokens": 5,
        "completion_tokens": 4,
        "pending_usage": 1,
        "usage_unknown": True,
        "usage_complete": False,
    }
    assert "tool_attempts" not in delta and "web_requests" not in delta
    assert _goal_usage_delta(before, before) is None


@pytest.mark.asyncio
async def test_goal_plan_edit_and_accept_are_recorded_only_for_proven_same_operation(
    db_session,
):
    from pydantic import BaseModel

    class Args(BaseModel):
        name: str

    first = AssistantOperation(
        "first", Args, lambda *_args, **_kwargs: None, op_id="project.update_task"
    )
    second = AssistantOperation(
        "second", Args, lambda *_args, **_kwargs: None, op_id="project.add_task"
    )
    run = SimpleNamespace(
        id=uuid4(),
        novel_id=uuid4(),
        owner_id=current_account_id(),
        request_json={"operation_trace_enabled": True},
    )
    previous = GoalPlan(
        title="旧计划",
        steps=[
            GoalStep(
                step_id="edit",
                operation_id="project.update_task",
                parameters={"name": "旧值"},
                intent="更新作者待办",
            )
        ],
    )
    accepted = GoalPlan(
        title="修改后计划",
        steps=[
            GoalStep(
                step_id="edit",
                operation_id="project.update_task",
                parameters={"name": "新值"},
                intent="更新作者待办",
            ),
            GoalStep(
                step_id="added",
                operation_id="project.add_task",
                parameters={"name": "新增待办"},
                intent="新增作者待办",
            ),
        ],
    )
    goal = {"operation_trace_plan_epoch": 3}
    seen = []

    async def trace_port(_db, **values):
        seen.append(values)
        return True

    with container_scope({ASSISTANT_OPERATION_TRACE: trace_port}):
        await _record_goal_plan_approval(
            db_session,
            run,
            goal,
            previous,
            accepted,
            {first.op_id: first, second.op_id: second},
        )

    assert [item["event_type"] for item in seen] == ["edited", "confirmed", "confirmed"]
    assert seen[0]["metadata"] == {"changed_fields": ["name"]}
    assert seen[0]["call_id"] == seen[1]["call_id"]
    assert seen[2]["operation"].op_id == "project.add_task"
    assert seen[2]["event_type"] == "confirmed"
    assert all(item["event_type"] != "proposed" for item in seen)


@pytest.mark.asyncio
async def test_archive_full_days_once_or_in_batches_yields_same_id_free_aggregates(
    db_session, project_factory
):
    owner_id = current_account_id()
    one_shot_id = await project_factory.create_project("trace one-shot")
    batch_id = await project_factory.create_project("trace batched")
    run_id = uuid4()
    session_id = uuid4()
    operation = assistant_notice_operations["assistant.notice.set_disposition"]
    fixed_now = datetime(2026, 10, 16, tzinfo=UTC)

    for novel_id in (one_shot_id, batch_id):
        for event_id, days_ago, op_id, event_type in (
            (1, 183, operation.op_id, "executed"),
            (2, 182, "world.dossier.entry.edit", "failed"),
        ):
            db_session.add(
                AssistantOperationTrace(
                    id=None,
                    novel_id=novel_id,
                    owner_id=owner_id,
                    occurred_at=fixed_now - timedelta(days=days_ago),
                    actor_type="ui",
                    entrypoint="assistant.test",
                    run_id=run_id,
                    session_id=session_id,
                    call_id=uuid4(),
                    op_id=op_id,
                    op_version="1",
                    risk_level="R2",
                    fee_category="free",
                    event_type=event_type,
                    target_type="author_task",
                    target_refs=[],
                    parameter_summary={
                        "fields": {},
                        "unknown_fields": {"present": False},
                    },
                    result_refs=[],
                    duration_ms=27,
                    usage={"requests": 1, "prompt_tokens": 3, "completion_tokens": 2},
                )
            )
    await db_session.flush()

    assert (
        await archive_expired_operation_traces(
            db_session, str(one_shot_id), now=fixed_now
        )
        == 2
    )
    assert (
        await archive_expired_operation_traces(
            db_session, str(batch_id), now=fixed_now, max_days=1
        )
        == 1
    )
    assert (
        await archive_expired_operation_traces(
            db_session, str(batch_id), now=fixed_now, max_days=1
        )
        == 1
    )

    async def snapshot(novel_id):
        return {
            "events": sorted(
                (row.occurred_on, row.op_id, row.event_type, row.event_count)
                for row in (
                    await db_session.scalars(
                        select(AssistantOperationTraceAggregate).where(
                            AssistantOperationTraceAggregate.novel_id == novel_id
                        )
                    )
                ).all()
            ),
            "sequences": sorted(
                (
                    row.occurred_on,
                    tuple(row.operation_sequence),
                    row.sequence_count,
                    row.sequence_complete,
                )
                for row in (
                    await db_session.scalars(
                        select(AssistantOperationSequenceAggregate).where(
                            AssistantOperationSequenceAggregate.novel_id == novel_id
                        )
                    )
                ).all()
            ),
            "metrics": sorted(
                (
                    row.occurred_on,
                    row.op_id,
                    row.event_type,
                    row.observed_event_count,
                    row.duration_ms_total,
                    row.usage_totals,
                )
                for row in (
                    await db_session.scalars(
                        select(AssistantOperationTraceMetricAggregate).where(
                            AssistantOperationTraceMetricAggregate.novel_id == novel_id
                        )
                    )
                ).all()
            ),
            "lifecycle": sorted(
                (
                    row.occurred_on,
                    row.op_id,
                    row.executed_count,
                    row.failed_execution_count,
                )
                for row in (
                    await db_session.scalars(
                        select(AssistantOperationTraceLifecycleAggregate).where(
                            AssistantOperationTraceLifecycleAggregate.novel_id == novel_id
                        )
                    )
                ).all()
            ),
            "parameters": sorted(
                (
                    row.occurred_on,
                    row.op_id,
                    row.event_type,
                    row.event_count,
                    row.parameter_profile,
                )
                for row in (
                    await db_session.scalars(
                        select(AssistantOperationTraceParameterAggregate).where(
                            AssistantOperationTraceParameterAggregate.novel_id == novel_id
                        )
                    )
                ).all()
            ),
        }

    assert await snapshot(one_shot_id) == await snapshot(batch_id)


@pytest.mark.asyncio
async def test_batch_author_decision_uses_one_stable_trace_call_id(
    db_session, test_project_id
):
    from modules.assistant.operations import _record_batch_event

    owner_id = current_account_id()
    run_id = uuid4()
    session_id = uuid4()
    seen = []

    async def trace_port(_db, **values):
        seen.append(values)
        return True

    run = SimpleNamespace(
        id=run_id,
        novel_id=UUID(test_project_id),
        owner_id=owner_id,
        session_id=session_id,
        request_json={"operation_trace_enabled": True},
        checkpoint_json={},
    )
    operation = assistant_notice_operations["assistant.notice.set_disposition"]
    item = {
        "key": "choose",
        "arguments": {"source_id": "writing.conflict", "category": "scope"},
        "preview": {},
    }
    with container_scope({ASSISTANT_OPERATION_TRACE: trace_port}):
        await _record_batch_event(db_session, run, item, operation, "confirmed")

    assert len(seen) == 1
    assert seen[0]["event_type"] == "confirmed"
    assert seen[0]["call_id"] == str(uuid5(NAMESPACE_URL, f"{run_id}:action:choose"))
    assert seen[0]["parent_call_id"] == str(run_id)
    assert seen[0]["actor_type"] == "ui"


@pytest.mark.asyncio
async def test_report_merges_live_and_legacy_aggregates_without_leaking_ids_or_hashes(
    db_session, project_factory
):
    novel_id = await project_factory.create_project("trace report")
    owner_id = current_account_id()
    operation = assistant_notice_operations["assistant.notice.set_disposition"]
    now = datetime.now(UTC)
    day = now.date()
    call_id = uuid4()
    run_id = uuid4()
    session_id = uuid4()
    old_day = day - timedelta(days=60)
    profile = {
        "fields": {
            "category": {
                "present": True,
                "type": "string",
                "length": 934,
                "project_hash": "private-salted-text-hash",
            },
            "flag": {"present": True, "type": "boolean", "value": True},
        },
        "unknown_fields": {"present": False},
    }
    sequence = [operation.op_id]
    sequence_hash = hashlib.sha256(
        json.dumps(sequence, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    db_session.add_all(
        [
            AssistantOperationTrace(
                call_id=call_id,
                novel_id=novel_id,
                owner_id=owner_id,
                occurred_at=now,
                actor_type="ui",
                entrypoint="assistant.test",
                run_id=run_id,
                session_id=session_id,
                op_id=operation.op_id,
                op_version="1",
                risk_level="R2",
                fee_category="free",
                event_type="executed",
                target_type="author_notice",
                target_refs=[{"type": "notice", "id": str(uuid4())}],
                parameter_summary=profile,
                result_refs=[],
                duration_ms=120,
                usage={
                    "requests": 1,
                    "prompt_tokens": 9,
                    "completion_tokens": 5,
                    "usage_complete": True,
                },
            ),
            AssistantOperationTraceAggregate(
                novel_id=novel_id,
                occurred_on=old_day,
                op_id=operation.op_id,
                event_type="executed",
                event_count=2,
            ),
            AssistantOperationSequenceAggregate(
                novel_id=novel_id,
                occurred_on=day,
                sequence_hash=sequence_hash,
                operation_sequence=sequence,
                sequence_count=1,
                sequence_complete=False,
            ),
        ]
    )
    await db_session.flush()

    report = await build_operation_trace_report(
        db_session,
        str(novel_id),
        period="90d",
        collection_enabled=True,
    )

    assert report["operation_candidates"][0]["recorded_event_count"] == 3
    assert {row["count"] for row in report["events"]} == {1, 2}
    assert report["coverage"]["missing_metric_event_count"] == 2
    assert report["coverage"]["status"] == "partial"
    assert report["sequences"][0]["complete"] is False
    assert report["sequences"][0]["count"] == 2
    assert next(
        profile["profile"]["fields"]["flag"]
        for profile in report["parameter_profiles"]
        if profile["profile"]["fields"].get("flag")
    ) == {"present": True, "type": "boolean"}
    executed_metrics = next(
        row
        for row in report["metrics"]
        if row["operation"] == operation.op_id and row["event"] == "executed"
    )
    assert executed_metrics["event_count"] == 3
    assert executed_metrics["duration"]["average_ms"] == 120
    assert executed_metrics["duration"]["status"] == "partial"
    serialized = json.dumps(report, ensure_ascii=False)
    for private_value in (
        str(call_id),
        str(run_id),
        str(session_id),
        "private-salted-text-hash",
    ):
        assert private_value not in serialized


@pytest.mark.asyncio
async def test_report_fixed_as_of_excludes_later_same_day_trace(
    db_session, project_factory, monkeypatch
):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 10, 16, 12, tzinfo=UTC)
            return value if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(report_module, "datetime", FrozenDateTime)
    novel_id = await project_factory.create_project("future trace boundary")
    owner_id = current_account_id()
    operation = assistant_notice_operations["assistant.notice.set_disposition"]
    db_session.add(
        AssistantOperationTrace(
            call_id=uuid4(),
            novel_id=novel_id,
            owner_id=owner_id,
            occurred_at=datetime(2026, 10, 16, 13, tzinfo=UTC),
            actor_type="ui",
            entrypoint="assistant.test",
            op_id=operation.op_id,
            op_version="1",
            risk_level="R2",
            fee_category="free",
            event_type="executed",
            target_type="author_notice",
            target_refs=[],
            parameter_summary={"fields": {}, "unknown_fields": {"present": False}},
            result_refs=[],
        )
    )
    await db_session.flush()

    report = await build_operation_trace_report(
        db_session,
        str(novel_id),
        period="30d",
        collection_enabled=True,
    )

    assert report["as_of"] == "2026-10-16T12:00:00+00:00"
    assert report["events"] == []
    assert report["coverage"]["status"] == "no_records"
