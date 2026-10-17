from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.assistant_operation_registry import _materialize, assistant_notice_operations
from core.config import get_settings
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.facade import current_account_id
from modules.account.models import Account
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.models import AssistantRun
from modules.assistant.operation_trace_models import (
    AssistantOperationSequenceAggregate,
    AssistantOperationTrace,
    AssistantOperationTraceAggregate,
    AssistantOperationTracePreference,
    AssistantOperationTraceProjectSalt,
)
from modules.assistant.operation_trace_service import (
    archive_expired_operation_traces,
    bind_operation_trace_context,
    operation_trace_enabled,
    record_operation_trace,
    reset_operation_trace_context,
    set_operation_trace_preference,
)
from modules.assistant.schemas import WorkContext
from modules.assistant.service import AssistantService
from modules.project.models import Project


async def _ensure_account(db, owner_id: UUID) -> None:
    if await db.get(Account, owner_id) is None:
        db.add(Account(id=owner_id, support_code=uuid4().hex))
        await db.flush()


@pytest.mark.asyncio
async def test_trace_failure_marks_current_run_without_failing_business(
    db_session, test_project_id, monkeypatch
):
    from modules.assistant import operation_trace_service as service

    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: replace(
            get_settings(), auth_mode="local", assistant_operation_trace_enabled=True
        ),
    )
    owner_id = current_account_id()
    await _ensure_account(db_session, owner_id)

    async def reject_salt(*_args):
        raise RuntimeError("synthetic trace store failure")

    monkeypatch.setattr(service, "_project_salt", reject_salt)
    state = {}
    token = bind_operation_trace_context(state)
    try:
        saved = await record_operation_trace(
            db_session,
            novel_id=test_project_id,
            owner_id=str(owner_id),
            operation=assistant_notice_operations["assistant.notice.set_disposition"],
            event_type="executed",
        )
    finally:
        reset_operation_trace_context(token)
    assert saved is False and state["incomplete_count"] == 1
    run = AssistantRun(
        novel_id=UUID(test_project_id),
        owner_id=owner_id,
        request_hash="t" * 64,
        request_json={"runtime_version": "7"},
        checkpoint_json={"operation_trace_incomplete": True},
    )
    assert AssistantService().view(run)["result"]["operation_trace_incomplete"]


@pytest.mark.asyncio
async def test_trace_summary_hashes_declared_text_and_only_marks_unknown_presence(
    db_session, project_factory, monkeypatch
):
    from modules.assistant import operation_trace_service as service

    settings = replace(
        get_settings(), auth_mode="local", assistant_operation_trace_enabled=True
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    owner_id = current_account_id()
    await _ensure_account(db_session, owner_id)
    first_novel_id = await project_factory.create_project("trace one")
    second_novel_id = await project_factory.create_project("trace two")
    operation = assistant_notice_operations["assistant.notice.mute_category"]
    prose = "秘密正文不得写入留痕"
    arguments = {
        "source_id": "writing.conflict",
        "category": prose,
        "expected_row_version": 3,
        "future_private_field": prose,
        prose: "untrusted field name",
        "nested": {"content": prose},
    }

    first = await record_operation_trace(
        db_session,
        enabled=True,
        novel_id=str(first_novel_id),
        owner_id=str(owner_id),
        operation=operation,
        event_type="proposed",
        arguments=arguments,
        preview={
            "nested": {"id": prose},
            "target": {"type": "notice", "id": str(uuid4())},
        },
        usage={"requests": 2, "prompt_tokens": prose, "usage_unknown": prose},
        call_id=str(uuid4()),
    )
    second = await record_operation_trace(
        db_session,
        enabled=True,
        novel_id=str(second_novel_id),
        owner_id=str(owner_id),
        operation=operation,
        event_type="proposed",
        arguments=arguments,
        call_id=str(uuid4()),
    )
    assert first and second
    rows = (
        await db_session.scalars(
            select(AssistantOperationTrace).where(
                AssistantOperationTrace.op_id == operation.op_id
            )
        )
    ).all()
    summaries = [row.parameter_summary for row in rows]
    serialized = json.dumps(summaries, ensure_ascii=False)
    assert prose not in serialized
    assert prose not in json.dumps([row.target_refs for row in rows], ensure_ascii=False)
    assert rows[0].usage == {"requests": 2}
    assert rows[0].target_refs and rows[0].target_refs[0]["type"] == "notice"
    assert all(summary["unknown_fields"] == {"present": True} for summary in summaries)
    categories = [summary["fields"]["category"] for summary in summaries]
    assert all(item["length"] == len(prose) for item in categories)
    assert categories[0]["project_hash"] != categories[1]["project_hash"]
    salts = (
        await db_session.scalars(
            select(AssistantOperationTraceProjectSalt).where(
                AssistantOperationTraceProjectSalt.novel_id.in_(
                    [first_novel_id, second_novel_id]
                )
            )
        )
    ).all()
    assert len(salts) == 2 and salts[0].salt != salts[1].salt


@pytest.mark.asyncio
async def test_local_default_public_opt_in_and_demo_never(db_session, monkeypatch):
    from modules.assistant import operation_trace_service as service

    owner_id = current_account_id()
    await _ensure_account(db_session, owner_id)
    settings = replace(
        get_settings(), auth_mode="local", assistant_operation_trace_enabled=True
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    assert await operation_trace_enabled(db_session, str(owner_id)) is True

    await set_operation_trace_preference(db_session, str(owner_id), False)
    assert await operation_trace_enabled(db_session, str(owner_id)) is False

    await set_operation_trace_preference(db_session, str(owner_id), True)
    assert await operation_trace_enabled(db_session, str(owner_id)) is True

    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: replace(settings, auth_mode="public"),
    )
    await db_session.delete(
        await db_session.get(AssistantOperationTracePreference, owner_id)
    )
    await db_session.flush()
    assert await operation_trace_enabled(db_session, str(owner_id)) is False
    await set_operation_trace_preference(db_session, str(owner_id), True)
    assert await operation_trace_enabled(db_session, str(owner_id)) is True

    token = bind_principal(
        AccountPrincipal(
            account_id=owner_id,
            status="active",
            identity_type="test",
            support_code="trace-demo",
            access_scope="demo_readonly",
            demo_project_id=uuid4(),
        )
    )
    try:
        assert await operation_trace_enabled(db_session, str(owner_id)) is False
    finally:
        reset_principal(token)


@pytest.mark.asyncio
async def test_owner_can_read_existing_aggregate_after_switching_trace_off(
    db_session, project_factory
):
    from modules.assistant.api import _operation_trace_aggregate

    owner_id = current_account_id()
    await _ensure_account(db_session, owner_id)
    novel_id = await project_factory.create_project("past trace")
    db_session.add(
        AssistantOperationTraceAggregate(
            novel_id=novel_id,
            occurred_on=datetime.now(UTC).date(),
            op_id="project.add_task",
            event_type="executed",
            event_count=2,
        )
    )
    await set_operation_trace_preference(db_session, str(owner_id), False)
    await db_session.flush()
    report = await _operation_trace_aggregate(db_session, novel_id, str(owner_id))
    assert report["events"][0]["count"] == 2


@pytest.mark.asyncio
async def test_trace_failure_savepoint_does_not_rollback_business_change(
    db_session, test_project_id, monkeypatch
):
    from modules.assistant import operation_trace_service as service

    settings = replace(
        get_settings(), auth_mode="local", assistant_operation_trace_enabled=True
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    owner_id = current_account_id()
    await _ensure_account(db_session, owner_id)
    novel_id = UUID(test_project_id)
    project = await db_session.get(Project, novel_id)
    original_title = project.title
    project.title = "业务事务仍保留"
    await db_session.flush()

    saved = await record_operation_trace(
        db_session,
        enabled=True,
        novel_id=str(novel_id),
        owner_id=str(owner_id),
        operation=assistant_notice_operations["assistant.notice.mute_category"],
        event_type="not-a-valid-lifecycle-event",
        arguments={"category": "不应出现"},
    )
    assert saved is False
    assert project.title == "业务事务仍保留"
    assert project.title != original_title
    assert (
        await db_session.scalar(
            select(AssistantOperationTrace.id).where(
                AssistantOperationTrace.novel_id == novel_id,
                AssistantOperationTrace.event_type == "not-a-valid-lifecycle-event",
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_materialized_operation_callbacks_record_prepare_and_apply_lifecycle(
    db_session, test_project_id, monkeypatch
):
    from modules.assistant import operation_trace_service as service

    settings = replace(
        get_settings(), auth_mode="local", assistant_operation_trace_enabled=True
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    owner_id = current_account_id()
    await _ensure_account(db_session, owner_id)
    operation_id = uuid4()

    class Args(BaseModel):
        instruction: str

    async def prepare(_db, _novel_id, args, *, context=None):
        return {"target": {"type": "draft", "id": str(operation_id)}}

    async def apply(_db, novel_id, _args, _preview, *, context=None):
        project = await db_session.get(Project, UUID(novel_id))
        project.title = "confirmed write"
        await db_session.flush()
        return {"type": "writing_draft", "id": str(operation_id)}

    operation = _materialize(
        {
            "test.trace_write": {
                "label": "test operation",
                "schema": Args,
                "prepare": prepare,
                "apply": apply,
                "permission": "confirm",
                "op_version": "1",
                "description": "test trace wrapper",
                "risk_level": "R2",
                "fee_category": "free",
                "reversibility": "restorable_append_only",
                "preconditions": ("stable test data",),
                "produces": ("writing_draft",),
                "target_type": "writing_draft",
                "ai_available": True,
                "transaction_mode": "single_transaction",
                "trace_rule": {
                    "parameter_fields": ("instruction",),
                    "mode": "per_call",
                },
            }
        }
    )["test.trace_write"]
    context = AssistantOperationContext(
        str(uuid4()), str(owner_id), WorkContext(), trace_enabled=True
    )
    args = Args(instruction="不得保存原文")
    preview = await operation.prepare(db_session, test_project_id, args, context=context)
    await operation.apply(db_session, test_project_id, args, preview, context=context)

    rows = (
        await db_session.scalars(
            select(AssistantOperationTrace)
            .where(AssistantOperationTrace.op_id == "test.trace_write")
            .order_by(AssistantOperationTrace.id)
        )
    ).all()
    assert [row.event_type for row in rows] == ["proposed", "previewed", "executed"]
    assert len({row.call_id for row in rows}) == 1
    assert "不得保存原文" not in json.dumps(
        [row.parameter_summary for row in rows], ensure_ascii=False
    )


@pytest.mark.asyncio
async def test_multistage_apply_error_is_recorded_as_unknown(
    db_session, test_project_id, monkeypatch
):
    from modules.assistant import operation_trace_service as service

    settings = replace(
        get_settings(), auth_mode="local", assistant_operation_trace_enabled=True
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    owner_id = current_account_id()
    await _ensure_account(db_session, owner_id)

    class Args(BaseModel):
        instruction: str

    async def prepare(*_args, **_kwargs):
        return {"receipt": {"id": str(uuid4())}}

    async def apply(*_args, **_kwargs):
        raise RuntimeError("receipt unavailable")

    operation = _materialize(
        {
            "test.trace_multistage": {
                "label": "test multi-stage",
                "schema": Args,
                "prepare": prepare,
                "apply": apply,
                "permission": "confirm",
                "op_version": "1",
                "description": "test unknown stage",
                "risk_level": "R2",
                "fee_category": "free",
                "reversibility": "none",
                "preconditions": ("stable test data",),
                "produces": ("receipt",),
                "target_type": "receipt",
                "ai_available": True,
                "transaction_mode": "multi_stage",
                "trace_rule": {
                    "parameter_fields": ("instruction",),
                    "mode": "per_call",
                },
            }
        }
    )["test.trace_multistage"]
    context = AssistantOperationContext(
        str(uuid4()), str(owner_id), WorkContext(), trace_enabled=True
    )
    args = Args(instruction="synthetic")
    preview = await operation.prepare(db_session, test_project_id, args, context=context)
    with pytest.raises(RuntimeError, match="receipt unavailable"):
        await operation.apply(db_session, test_project_id, args, preview, context=context)
    assert (
        await db_session.scalar(
            select(AssistantOperationTrace.event_type)
            .where(AssistantOperationTrace.op_id == "test.trace_multistage")
            .order_by(AssistantOperationTrace.id.desc())
        )
        == "outcome_unknown"
    )


@pytest.mark.asyncio
async def test_expired_details_become_id_free_counts_and_sequences(
    db_session, test_project_id
):
    novel_id = UUID(test_project_id)
    owner_id = current_account_id()
    session_id = uuid4()
    old_time = datetime.now(UTC) - timedelta(days=181)
    operation = assistant_notice_operations["assistant.notice.set_disposition"]
    for op_id in (operation.op_id, "world.dossier.entry.edit"):
        db_session.add(
            AssistantOperationTrace(
                novel_id=novel_id,
                owner_id=owner_id,
                session_id=session_id,
                actor_type="assistant",
                entrypoint="assistant.test",
                op_id=op_id,
                op_version="1",
                risk_level="R2",
                fee_category="free",
                event_type="executed",
                target_type="author_notice",
                target_refs=[{"type": "notice", "id": str(uuid4())}],
                parameter_summary={"fields": {}, "unknown_fields": {}},
                result_refs=[],
                occurred_at=old_time,
            )
        )
    await db_session.flush()

    deleted = await archive_expired_operation_traces(db_session, str(novel_id))
    assert deleted == 2
    assert (
        await db_session.scalar(
            select(AssistantOperationTrace.id).where(
                AssistantOperationTrace.novel_id == novel_id
            )
        )
        is None
    )
    events = (
        await db_session.scalars(
            select(AssistantOperationTraceAggregate).where(
                AssistantOperationTraceAggregate.novel_id == novel_id
            )
        )
    ).all()
    assert len(events) == 2 and sum(row.event_count for row in events) == 2
    sequences = (
        await db_session.scalars(
            select(AssistantOperationSequenceAggregate).where(
                AssistantOperationSequenceAggregate.novel_id == novel_id
            )
        )
    ).all()
    assert len(sequences) == 1
    assert sequences[0].operation_sequence == [
        operation.op_id,
        "world.dossier.entry.edit",
    ]
    assert sequences[0].sequence_count == 1
