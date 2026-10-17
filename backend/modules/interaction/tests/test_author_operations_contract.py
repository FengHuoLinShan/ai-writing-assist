from uuid import uuid4

import pytest

from core.errors import ConflictError
from modules.interaction import author_api, author_operations


def test_author_operation_catalog_has_complete_metadata_and_trace_schemas():
    from app.assistant_operation_registry import _materialize

    built = _materialize(author_operations.OPERATIONS_SPEC)
    assert set(built) == set(author_operations.OPERATIONS_SPEC)
    for operation in built.values():
        assert operation.trace_rule.parameter_fields == tuple(
            operation.schema.model_fields
        )
        assert operation.risk_level in {"R0", "R2", "R4"}
        assert operation.transaction_mode in {"single_transaction", "multi_stage"}
    assert built["interaction.summary.refresh"].risk_level == "R4"
    assert built["interaction.summary.refresh"].fee_category == "possible_model_charge"
    assert built["interaction.summary.refresh"].transaction_mode == "multi_stage"


def test_author_http_routes_bind_exact_operation_schemas():
    by_operation = {}
    for route in author_api.router.routes:
        extra = route.openapi_extra or {}
        op_id = extra.get("x-novelcraft-operation-id")
        if not op_id:
            continue
        by_operation.setdefault(op_id, []).append(extra)
        assert set(extra.get("x-novelcraft-operation-trace-fields") or {}) == set(
            author_operations.OPERATIONS_SPEC[op_id]["schema"].model_fields
        )
    assert set(by_operation) == set(author_operations.OPERATIONS_SPEC)
    assert by_operation["interaction.summary.refresh"]


@pytest.mark.asyncio
async def test_summary_confirm_fails_closed_before_enqueue_when_unknown_stop_is_missing(
    monkeypatch,
):
    args = author_operations.SummaryRefreshArgs(
        author_project_id=uuid4(),
        journey_id=uuid4(),
        operation_id=None,
        expected_preview_hash="a" * 64,
        confirmed=True,
    )
    preview = {
        "preview_hash": "a" * 64,
        "unknown_charge_stop_available": False,
        "consumer_project_id": str(uuid4()),
    }

    async def prepared(*_args, **_kwargs):
        return preview

    async def enqueue(*_args, **_kwargs):
        pytest.fail(
            "summary preparation must not enqueue while unknown-stop is unavailable"
        )

    async def lock_journey(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(author_operations, "_summary_preview", prepared)
    monkeypatch.setattr(author_operations, "enqueue_operation_task", enqueue)
    monkeypatch.setattr(author_operations._service, "_owned_journey", lock_journey)
    with pytest.raises(ConflictError) as error:
        await author_operations._summary_apply(
            object(),
            str(args.author_project_id),
            args,
            preview,
            context=None,
        )
    assert error.value.code == "ROOT_BUDGET_ADAPTER_UNAVAILABLE"
