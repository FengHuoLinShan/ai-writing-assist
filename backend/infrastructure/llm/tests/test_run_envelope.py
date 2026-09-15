"""统一 AI 运行信封：契约、累计账本、作用域与兼容投影。"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from infrastructure.llm.agent_step_harness import (
    AI_RUN_STEP_DETAIL_KEY,
    MANAGED_LLM_PROVENANCE_KEY,
    merge_managed_llm_provenance,
    project_managed_llm_steps,
    run_managed_generate,
)
from infrastructure.llm.schemas import (
    AI_RUN_RECENT_ATTEMPT_LIMIT,
    AIChargeState,
    AIRequestOutcome,
    AIRunAuthorizationReason,
    AIRunEnvelopeV1,
    AIRunEnvelopeVersionError,
    AIRunStatus,
    AIStepCallKind,
    AIStepPurpose,
    LLMCallRequest,
    LLMCallResponse,
    LLMUsage,
    read_ai_run_envelope,
)
from infrastructure.llm.workflow_budget import (
    AIManagedStepContext,
    AIManagedStepContextError,
    AIRunBudgetExceededError,
    AIRunDeadlineExceededError,
    AIRunEnvelope,
    AIRunEnvelopeError,
    AIRunIdentityError,
    AIRunStateError,
    ai_run_scope,
    current_ai_run_envelope,
    managed_step_scope,
    new_ai_run_envelope,
)

_STARTED_AT = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


def _raw_envelope(**overrides) -> AIRunEnvelopeV1:
    options = {
        "operation_id": "op-1",
        "run_id": "run-1",
        "root_capability_id": "writing.generate",
        "novel_id": "novel-1",
        "started_at": _STARTED_AT,
        "request_limit": 3,
    }
    options.update(overrides)
    return AIRunEnvelopeV1(**options)


def _ledger(**overrides) -> AIRunEnvelope:
    return AIRunEnvelope(_raw_envelope(**overrides))


def _step(**overrides) -> AIManagedStepContext:
    options = {
        "step_name": "writing.generate.primary",
        "call_kind": AIStepCallKind.generate,
        "profile_hash": "a" * 64,
        "profile_source": "project",
        "profile_summary": {"model": "gpt-x", "provider_id": "openai"},
    }
    options.update(overrides)
    return AIManagedStepContext(**options)


class _FakeClient:
    """最小 provider 替身：每次 generate 预留并落定一次请求。"""

    profile_summary = {"provider_id": "openai", "model": "gpt-x", "timeout": 30}
    runtime_scope = {"novel_id": "novel-1", "profile_source": "project"}

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
        self.calls += 1
        ledger = current_ai_run_envelope()
        if ledger is not None:
            reservation = await ledger.reserve()
            usage = LLMUsage(prompt_tokens=4, completion_tokens=6, total_tokens=10)
            await ledger.settle(
                reservation, usage=usage, elapsed_ms=12.5, finish_reason="stop"
            )
            return LLMCallResponse(content="ok", usage=usage, finish_reason="stop")
        return LLMCallResponse(content="ok", finish_reason="stop")


class TestEnvelopeContract:
    def test_round_trip_preserves_ledger(self) -> None:
        envelope = _raw_envelope(
            deadline_at=_STARTED_AT + timedelta(minutes=5),
            request_limit=1,
            requests_started=1,
            requests_settled=1,
            usage=LLMUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            steps=[
                {
                    "step_name": "writing.generate.primary",
                    "step_capability_id": "writing.generate",
                    "call_kind": AIStepCallKind.generate,
                    "requests_started": 1,
                    "requests_settled": 1,
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 3,
                        "total_tokens": 5,
                    },
                }
            ],
        )
        payload = envelope.model_dump(mode="json")
        restored = read_ai_run_envelope(payload)
        assert restored is not None
        assert restored.model_dump(mode="json") == payload

    def test_v0_payloads_are_readable_not_rejected(self) -> None:
        assert read_ai_run_envelope(None) is None
        assert read_ai_run_envelope([{"step_name": "legacy"}]) is None
        assert read_ai_run_envelope({"step_name": "legacy"}) is None

    def test_unknown_version_fails_closed(self) -> None:
        with pytest.raises(AIRunEnvelopeVersionError):
            read_ai_run_envelope({"version": 99})
        with pytest.raises(AIRunEnvelopeVersionError):
            read_ai_run_envelope("envelope")

    def test_naive_timestamps_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _raw_envelope(started_at=datetime(2026, 9, 15, 10, 0))

    def test_step_capability_must_be_root_or_infrastructure(self) -> None:
        with pytest.raises(ValidationError):
            _raw_envelope(
                request_limit=1,
                requests_started=1,
                requests_settled=1,
                usage=LLMUsage(total_tokens=1),
                steps=[
                    {
                        "step_name": "other.step",
                        "step_capability_id": "world.chat",
                        "call_kind": AIStepCallKind.generate,
                        "requests_started": 1,
                        "requests_settled": 1,
                        "usage": {"total_tokens": 1},
                    }
                ],
            )

    def test_receipts_must_account_for_every_request(self) -> None:
        with pytest.raises(ValidationError):
            _raw_envelope(requests_started=2, request_limit=2)

    def test_legacy_untracked_cannot_claim_complete_usage(self) -> None:
        with pytest.raises(ValidationError):
            _raw_envelope(legacy_untracked=True, usage_complete=True)
        legacy = _raw_envelope(legacy_untracked=True, usage_complete=False)
        assert legacy.requests_started == 0


class TestRunLedger:
    async def test_counts_usage_and_charge_state_accumulate(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(_step()):
            first = await ledger.reserve()
            await ledger.settle(
                first,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                finish_reason="stop",
                elapsed_ms=100.0,
            )
            second = await ledger.reserve(purpose=AIStepPurpose.schema_repair)
            await ledger.settle(
                second,
                outcome=AIRequestOutcome.unknown,
                error_kind="timeout",
                elapsed_ms=5.0,
            )
        snapshot = ledger.snapshot()
        assert snapshot.requests_started == 2
        assert snapshot.requests_settled == 1
        assert snapshot.requests_unknown == 1
        assert snapshot.usage.total_tokens == 15
        assert snapshot.usage_complete is False
        assert snapshot.charge_state is AIChargeState.possible
        assert [(s.purpose, s.charge_state) for s in snapshot.steps] == [
            (AIStepPurpose.primary, AIChargeState.recorded),
            (AIStepPurpose.schema_repair, AIChargeState.possible),
        ]
        assert snapshot.steps[0].finish_reason == "stop"
        assert snapshot.steps[1].error_kind == "timeout"
        assert snapshot.steps[0].elapsed_ms == 100.0

    async def test_budget_rejection_charges_nothing(self) -> None:
        ledger = _ledger(request_limit=1)
        with ai_run_scope(ledger), managed_step_scope(_step()):
            first = await ledger.reserve()
            await ledger.settle(first, usage=LLMUsage(total_tokens=3))
            with pytest.raises(AIRunBudgetExceededError):
                await ledger.reserve()
        snapshot = ledger.snapshot()
        assert snapshot.requests_started == 1
        assert len(snapshot.steps) == 1
        assert len(snapshot.recent_attempts) == 1

    async def test_deadline_rejection_happens_before_any_counting(self) -> None:
        deadline = _STARTED_AT + timedelta(minutes=5)
        ledger = AIRunEnvelope(
            _raw_envelope(deadline_at=deadline),
            clock=lambda: deadline + timedelta(seconds=1),
        )
        with ai_run_scope(ledger), managed_step_scope(_step()):
            with pytest.raises(AIRunDeadlineExceededError):
                await ledger.reserve()
        snapshot = ledger.snapshot()
        assert snapshot.requests_started == 0
        assert snapshot.steps == []
        assert snapshot.recent_attempts == []
        assert snapshot.charge_state is AIChargeState.none

    async def test_remaining_seconds_uses_the_frozen_deadline(self) -> None:
        deadline = _STARTED_AT + timedelta(minutes=5)
        ledger = AIRunEnvelope(
            _raw_envelope(deadline_at=deadline),
            clock=lambda: deadline - timedelta(seconds=30),
        )
        assert ledger.remaining_seconds() == 30.0
        assert ledger.deadline_exceeded() is False

    async def test_missing_usage_never_becomes_zero_usage(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(_step()):
            reservation = await ledger.reserve()
            await ledger.settle(reservation, usage=None)
        snapshot = ledger.snapshot()
        assert snapshot.requests_settled == 0
        assert snapshot.requests_unknown == 1
        assert snapshot.usage == LLMUsage()
        assert snapshot.usage_complete is False
        assert snapshot.steps[0].usage_complete is False

    async def test_reserve_requires_a_managed_step(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger):
            with pytest.raises(AIManagedStepContextError):
                await ledger.reserve()

    async def test_step_capability_drift_is_rejected(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(
            _step(capability_id="world.chat")
        ):
            with pytest.raises(AIRunIdentityError):
                await ledger.reserve()
        assert ledger.snapshot().requests_started == 0

    async def test_infrastructure_helper_step_is_allowed(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(
            _step(step_name="repair", capability_id="infrastructure.format_repair")
        ):
            reservation = await ledger.reserve()
            await ledger.settle(reservation, usage=LLMUsage(total_tokens=1))
        step = ledger.snapshot().steps[0]
        assert step.step_capability_id == "infrastructure.format_repair"

    async def test_double_settle_is_rejected(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(_step()):
            reservation = await ledger.reserve()
            await ledger.settle(reservation, usage=LLMUsage(total_tokens=1))
            with pytest.raises(AIRunEnvelopeError):
                await ledger.settle(reservation, usage=LLMUsage(total_tokens=1))
        assert ledger.snapshot().requests_started == 1

    async def test_foreign_reservation_is_rejected(self) -> None:
        first, second = _ledger(run_id="run-1"), _ledger(run_id="run-2")
        with ai_run_scope(first), managed_step_scope(_step()):
            reservation = await first.reserve()
            with pytest.raises(AIRunIdentityError):
                await second.settle(reservation, usage=LLMUsage(total_tokens=1))

    async def test_retry_counters_stay_per_purpose(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(_step()):
            reservation = await ledger.reserve()
            await ledger.record_retry(reservation, kind="transport")
            await ledger.record_retry(reservation, kind="transport")
            await ledger.record_retry(reservation, kind="format")
            await ledger.settle(reservation, usage=LLMUsage(total_tokens=1))
        step = ledger.snapshot().steps[0]
        assert (step.transport_retries, step.format_retries) == (2, 1)

    async def test_author_authorization_raises_limit_only(self) -> None:
        deadline = _STARTED_AT + timedelta(minutes=5)
        ledger = _ledger(request_limit=1, deadline_at=deadline)
        await ledger.authorize_additional_requests(
            2, reason=AIRunAuthorizationReason.duplicate_charge_confirmed
        )
        snapshot = ledger.snapshot()
        assert snapshot.request_limit == 3
        assert snapshot.authorization_revision == 1
        assert snapshot.deadline_at == deadline
        assert (
            snapshot.authorizations[0].reason
            is AIRunAuthorizationReason.duplicate_charge_confirmed
        )

    async def test_overflow_keeps_every_aggregate_count(self) -> None:
        limit = AI_RUN_RECENT_ATTEMPT_LIMIT + 44
        ledger = _ledger(request_limit=limit)
        with ai_run_scope(ledger), managed_step_scope(_step()):
            for _ in range(limit):
                reservation = await ledger.reserve()
                await ledger.settle(reservation, usage=LLMUsage(total_tokens=1))
        snapshot = ledger.snapshot()
        assert len(snapshot.recent_attempts) == AI_RUN_RECENT_ATTEMPT_LIMIT
        assert snapshot.recent_attempts_overflow == 44
        assert snapshot.requests_started == limit
        assert snapshot.requests_settled == limit
        assert snapshot.usage.total_tokens == limit
        assert snapshot.steps[0].requests_started == limit
        assert read_ai_run_envelope(snapshot.model_dump(mode="json")) is not None

    async def test_recovery_turns_in_flight_requests_into_unknown(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(_step()):
            await ledger.reserve()
        assert await ledger.mark_in_flight_unknown() == 1
        snapshot = ledger.snapshot()
        assert snapshot.requests_started == 1
        assert snapshot.requests_unknown == 1
        assert snapshot.usage_complete is False
        assert snapshot.charge_state is AIChargeState.possible
        assert snapshot.recent_attempts[0].outcome is AIRequestOutcome.unknown
        assert await ledger.mark_in_flight_unknown() == 0

    async def test_finished_run_rejects_further_requests(self) -> None:
        ledger = _ledger()
        await ledger.finish(AIRunStatus.succeeded)
        with ai_run_scope(ledger), managed_step_scope(_step()):
            with pytest.raises(AIRunStateError):
                await ledger.reserve()
        with pytest.raises(AIRunStateError):
            await ledger.finish(AIRunStatus.succeeded)

    async def test_change_notification_carries_the_latest_snapshot(self) -> None:
        seen: list[AIRunEnvelopeV1] = []

        async def on_change(snapshot: AIRunEnvelopeV1) -> None:
            seen.append(snapshot)

        ledger = AIRunEnvelope(_raw_envelope(), on_change=on_change)
        with ai_run_scope(ledger), managed_step_scope(_step()):
            reservation = await ledger.reserve()
            await ledger.settle(reservation, usage=LLMUsage(total_tokens=2))
        assert [item.requests_started for item in seen] == [1, 1]
        assert seen[-1].requests_settled == 1


class TestEnvelopeScopes:
    async def test_nested_scope_reuses_one_ledger(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger):
            with ai_run_scope(ledger) as inner:
                assert inner is ledger
            assert current_ai_run_envelope() is ledger
        assert current_ai_run_envelope() is None

    async def test_nesting_another_run_is_identity_drift(self) -> None:
        with ai_run_scope(_ledger(run_id="run-1")):
            with pytest.raises(AIRunIdentityError):
                with ai_run_scope(_ledger(run_id="run-2")):
                    pass

    async def test_step_scope_restores_the_outer_step(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(_step(step_name="outer")):
            with managed_step_scope(_step(step_name="inner")):
                reservation = await ledger.reserve()
                await ledger.settle(reservation, usage=LLMUsage(total_tokens=1))
            reservation = await ledger.reserve()
            await ledger.settle(reservation, usage=LLMUsage(total_tokens=1))
        assert [s.step_name for s in ledger.snapshot().steps] == ["inner", "outer"]

    async def test_concurrent_runs_do_not_share_ledgers(self) -> None:
        first, second = _ledger(run_id="run-1"), _ledger(run_id="run-2")

        async def worker(ledger: AIRunEnvelope) -> int:
            with ai_run_scope(ledger), managed_step_scope(_step()):
                await asyncio.sleep(0)
                reservation = await ledger.reserve()
                await asyncio.sleep(0)
                assert current_ai_run_envelope() is ledger
                await ledger.settle(reservation, usage=LLMUsage(total_tokens=1))
            return ledger.snapshot().requests_started

        assert await asyncio.gather(worker(first), worker(second)) == [1, 1]

    async def test_child_task_shares_the_parent_ledger(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(_step()):

            async def child() -> None:
                assert current_ai_run_envelope() is ledger
                reservation = await ledger.reserve()
                await ledger.settle(reservation, usage=LLMUsage(total_tokens=2))

            await asyncio.create_task(child())
        assert ledger.snapshot().requests_started == 1
        assert current_ai_run_envelope() is None


class TestManagedStepAttribution:
    async def test_managed_generate_attributes_the_request_to_the_step(self) -> None:
        ledger = _ledger()
        client = _FakeClient()
        with ai_run_scope(ledger):
            response = await run_managed_generate(
                client,
                LLMCallRequest(),
                step_name="writing.generate.primary",
                capability_id="writing.generate",
            )
        assert response.content == "ok"
        snapshot = ledger.snapshot()
        assert snapshot.requests_started == 1
        assert snapshot.requests_settled == 1
        assert snapshot.steps[0].step_capability_id == "writing.generate"
        assert snapshot.steps[0].call_kind is AIStepCallKind.generate
        assert snapshot.steps[0].profile_source == "project"
        assert snapshot.steps[0].profile_hash

    async def test_managed_generate_without_envelope_keeps_working(self) -> None:
        client = _FakeClient()
        response = await run_managed_generate(
            client, LLMCallRequest(), step_name="writing.generate.primary"
        )
        assert response.content == "ok"
        assert client.calls == 1
        assert current_ai_run_envelope() is None


class TestCompatibilityProjection:
    async def test_projection_keeps_v0_fields_and_v1_detail(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(_step()):
            reservation = await ledger.reserve()
            await ledger.settle(reservation, usage=LLMUsage(total_tokens=5))
        records = project_managed_llm_steps(ledger.snapshot())
        assert len(records) == 1
        record = records[0]
        assert record["step_name"] == "writing.generate.primary"
        assert record["novel_id"] == "novel-1"
        assert record["profile_hash"]
        detail = record[AI_RUN_STEP_DETAIL_KEY]
        assert detail["run_id"] == "run-1"
        assert len(detail["receipts"]) == 1
        assert detail["receipts"][0]["requests_started"] == 1
        assert detail["receipts"][0]["call_kind"] == "generate"

    async def test_one_row_per_v0_identity_keeps_every_purpose(self) -> None:
        ledger = _ledger(request_limit=4)
        with ai_run_scope(ledger), managed_step_scope(_step()):
            first = await ledger.reserve()
            await ledger.settle(first, usage=LLMUsage(total_tokens=1))
            second = await ledger.reserve(purpose=AIStepPurpose.schema_repair)
            await ledger.settle(
                second, outcome=AIRequestOutcome.unknown, error_kind="timeout"
            )
        records = project_managed_llm_steps(ledger.snapshot())
        assert len(records) == 1
        receipts = records[0][AI_RUN_STEP_DETAIL_KEY]["receipts"]
        assert sorted(receipt["purpose"] for receipt in receipts) == [
            "primary",
            "schema_repair",
        ]
        merged = merge_managed_llm_provenance(None, records)
        assert len(merged[MANAGED_LLM_PROVENANCE_KEY]) == 1

    async def test_merge_keeps_v1_detail_and_dedupes(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(_step()):
            reservation = await ledger.reserve()
            await ledger.settle(reservation, usage=LLMUsage(total_tokens=5))
        records = project_managed_llm_steps(ledger.snapshot())
        merged = merge_managed_llm_provenance({"status": "ok"}, records)
        merged = merge_managed_llm_provenance(merged, records)
        assert merged["status"] == "ok"
        assert len(merged[MANAGED_LLM_PROVENANCE_KEY]) == 1
        assert AI_RUN_STEP_DETAIL_KEY in merged[MANAGED_LLM_PROVENANCE_KEY][0]

    async def test_merge_still_accepts_legacy_v0_records(self) -> None:
        legacy = {
            "step_name": "outline.analyze",
            "novel_id": "novel-1",
            "profile_source": "account",
            "profile_summary": {"model": "m", "provider_id": "p"},
            "profile_hash": "abc",
        }
        merged = merge_managed_llm_provenance(None, [legacy])
        record = merged[MANAGED_LLM_PROVENANCE_KEY][0]
        assert AI_RUN_STEP_DETAIL_KEY not in record
        assert set(record) == {
            "step_name",
            "novel_id",
            "profile_source",
            "profile_summary",
            "profile_hash",
        }
        assert len(record["profile_hash"]) == 64

    async def test_projection_detail_rejects_unknown_keys(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(_step()):
            reservation = await ledger.reserve()
            await ledger.settle(reservation, usage=LLMUsage(total_tokens=5))
        records = project_managed_llm_steps(ledger.snapshot())
        records[0][AI_RUN_STEP_DETAIL_KEY]["receipts"][0]["api_key"] = "sk-live-secret"
        merged = merge_managed_llm_provenance(None, records)
        assert AI_RUN_STEP_DETAIL_KEY not in merged[MANAGED_LLM_PROVENANCE_KEY][0]


class TestEnvelopeSecrecy:
    async def test_receipts_drop_bodies_endpoints_and_credentials(self) -> None:
        ledger = _ledger()
        hostile = _step(
            step_name="step sk-live-abcdef123\napi_key=SECRET",
            profile_hash="hash",
        )
        with ai_run_scope(ledger), managed_step_scope(hostile):
            reservation = await ledger.reserve()
            await ledger.settle(
                reservation,
                usage=None,
                error_kind="Bearer abc.def.ghi https://api.example.com/v1?token=x",
            )
        serialized = json.dumps(ledger.snapshot().model_dump(mode="json"))
        assert "sk-live" not in serialized
        assert "SECRET" not in serialized
        assert "abc.def.ghi" not in serialized
        assert "api.example.com" not in serialized
        assert "\\n" not in serialized

    async def test_projection_never_carries_prompt_or_key_material(self) -> None:
        ledger = _ledger()
        with ai_run_scope(ledger), managed_step_scope(_step()):
            reservation = await ledger.reserve()
            await ledger.settle(reservation, usage=LLMUsage(total_tokens=5))
        serialized = json.dumps(project_managed_llm_steps(ledger.snapshot()))
        for forbidden in ("messages", "content", "reasoning", "api_key", "base_url"):
            assert forbidden not in serialized


def test_new_ai_run_envelope_freezes_started_at_and_limit() -> None:
    ledger = new_ai_run_envelope(
        operation_id="op",
        run_id="run",
        root_capability_id="writing.generate",
        novel_id="novel",
        request_limit=4,
        started_at=_STARTED_AT,
        legacy_untracked=True,
    )
    snapshot = ledger.snapshot()
    assert snapshot.started_at == _STARTED_AT
    assert snapshot.request_limit == 4
    assert snapshot.legacy_untracked is True
    assert snapshot.usage_complete is False
    assert snapshot.status is AIRunStatus.running
