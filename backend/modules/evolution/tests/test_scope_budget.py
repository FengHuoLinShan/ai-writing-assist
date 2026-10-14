"""Scope/null budget is explicit, owner fenced, and model restricted."""

import pytest

from core.errors import ConflictError
from infrastructure.llm.tests.test_luna_context_scope import luna_snapshot
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.workflow import ReadingRequest, _budget_mode


async def test_scope_budget_never_decrements_and_inactive_fails(
    db_session, evolution_project_id
):
    store = PostgresAttemptStore(db_session, evolution_project_id)
    run = await store.register_run(
        "scope", mode="bootstrap", budget_total=None, llm_snapshot=luna_snapshot()
    )
    run.reading_plan_json = {"budget_mode": "confirmed_scope"}
    for _ in range(21):
        assert await store.reserve_budget("scope", 1) is None
    assert run.budget_total is None and run.budget_remaining is None
    run.status = "stopped"
    await db_session.flush()
    with pytest.raises(Exception, match="no longer active"):
        await store.reserve_budget("scope", 1)


async def test_empty_quota_cannot_authorize_ds(db_session, evolution_project_id):
    store = PostgresAttemptStore(db_session, evolution_project_id)
    with pytest.raises(ValueError):
        await store.register_run(
            "ds",
            mode="bootstrap",
            budget_total=None,
            llm_snapshot={
                "profile": {"provider_id": "deepseek", "model": "deepseek-flash"}
            },
        )


def test_old_finite_run_and_append_inherit_policy():
    from uuid import uuid4

    request = ReadingRequest(operation_id=uuid4(), end_chapter=1, request_limit=20)
    assert _budget_mode(request, luna_snapshot(), {"world_version": 2}) == "bounded"
    assert (
        _budget_mode(request.model_copy(update={"request_limit": None}), luna_snapshot())
        == "confirmed_scope"
    )
    with pytest.raises(ConflictError):
        _budget_mode(
            request.model_copy(update={"request_limit": None}),
            luna_snapshot(),
            {"world_version": 2},
        )
