from uuid import uuid4

import pytest

from core.errors import ConflictError
from modules.collaboration import assistant_tools, author_operations_api


def test_collaboration_operation_catalog_is_complete_and_risked():
    from app.assistant_operation_registry import _materialize

    built = _materialize(assistant_tools.OPERATIONS_SPEC)
    assert set(built) == set(assistant_tools.OPERATIONS_SPEC)
    for operation in built.values():
        assert operation.trace_rule.parameter_fields == tuple(
            operation.schema.model_fields
        )
        assert operation.transaction_mode in {"single_transaction", "multi_stage"}
        assert operation.fee_category in {"free", "possible_model_charge"}
    assert built["collaboration.workspace.check"].risk_level == "R4"
    assert built["collaboration.workspace.check"].fee_category == "possible_model_charge"
    assert built["collaboration.workspace.check"].transaction_mode == "multi_stage"
    assert built["collaboration.workspace.atomic_adopt"].risk_level == "R3"
    assert built["collaboration.workspace.atomic_adopt"].fee_category == "free"


def test_collaboration_http_bindings_match_operation_schema_fields():
    operations_by_id = {}
    for route in author_operations_api.router.routes:
        extra = route.openapi_extra or {}
        op_id = extra.get("x-novelcraft-operation-id")
        if not op_id:
            continue
        operations_by_id.setdefault(op_id, []).append(extra)
        assert set(extra.get("x-novelcraft-operation-trace-fields") or {}) == set(
            assistant_tools.OPERATIONS_SPEC[op_id]["schema"].model_fields
        )
    assert set(operations_by_id) == set(assistant_tools.OPERATIONS_SPEC)
    assert any(
        extra.get("x-novelcraft-operation-phase") == "prepare"
        for extra in operations_by_id["collaboration.workspace.check"]
    )
    assert any(
        extra.get("x-novelcraft-operation-phase") == "prepare"
        for extra in operations_by_id["collaboration.workspace.atomic_adopt"]
    )


@pytest.mark.asyncio
async def test_atomic_adoption_requires_explicit_confirmation_before_database_access():
    args = assistant_tools.AtomicAdoptionArgs(
        workspace_id=uuid4(),
        revision_id=uuid4(),
        expected_digest="a" * 64,
        operation_id=uuid4(),
        editor_state="saved",
    )
    with pytest.raises(ConflictError) as error:
        await assistant_tools._atomic_apply(object(), "project", args, None, context=None)
    assert error.value.code == "CONFIRMATION_REQUIRED"


@pytest.mark.asyncio
async def test_atomic_adoption_rejects_changed_preview_before_merge(monkeypatch):
    novel_id = uuid4()
    args = assistant_tools.AtomicAdoptionArgs(
        workspace_id=uuid4(),
        revision_id=uuid4(),
        expected_digest="a" * 64,
        operation_id=uuid4(),
        editor_state="saved",
        expected_preview_hash="c" * 64,
        confirmed=True,
    )
    current = {"preview_hash": "b" * 64}

    class EmptyReceiptDb:
        async def scalar(self, _statement):
            return None

    async def prepare(*_args, **_kwargs):
        return current

    async def merge(*_args, **_kwargs):
        pytest.fail("a changed author preview must not call merge_workspace")

    monkeypatch.setattr(assistant_tools, "_atomic_prepare", prepare)
    monkeypatch.setattr(assistant_tools, "merge_workspace", merge)
    with pytest.raises(ConflictError) as error:
        await assistant_tools._atomic_apply(
            EmptyReceiptDb(),
            str(novel_id),
            args,
            current,
            context=None,
        )
    assert error.value.code == "PREVIEW_STALE"
