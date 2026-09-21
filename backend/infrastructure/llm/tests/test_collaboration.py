"""Collaboration safety and recovery without provider IO."""

import asyncio
from copy import deepcopy
from itertools import permutations

import pytest

from infrastructure.llm.agent_runtime import (
    AgentAllocation,
    AgentBudgetError,
    AgentRunBudget,
    agent_allocation,
)
from infrastructure.llm.collaboration import (
    MemberFailureError,
    WorkItem,
    content_hash,
    run_work_items,
)
from infrastructure.llm.workflow_budget import workflow_budget


def item(key, **kw):
    return WorkItem(key=key, role="reader", input_hash="a" * 64, **kw)


async def test_parallel_last_reservation_and_final_reserve():
    budget = AgentRunBudget(policy_version="team_v1", requests=23)
    sent = []

    async def checkpoint(_):
        await asyncio.sleep(0)

    async def call(key):
        with agent_allocation(AgentAllocation(key, final_reserve=6)):
            with workflow_budget(budget, checkpoint) as meter:
                try:
                    await meter.before_request()
                except AgentBudgetError:
                    return
                sent.append(key)

    await asyncio.gather(*(call(str(i)) for i in range(3)))
    assert len(sent) == 1
    assert budget.requests == 24
    assert AgentRunBudget().limits == (12, 32, 4)


async def test_checkpoint_failure_refunds_unissued_member_request():
    budget = AgentRunBudget(policy_version="team_v1")
    allocation = AgentAllocation("facts")

    async def broken(_):
        raise RuntimeError("lease lost")

    with agent_allocation(allocation), workflow_budget(budget, broken) as meter:
        with pytest.raises(RuntimeError):
            await meter.before_request()
    assert budget.requests == allocation.requests == 0


async def test_recovery_keeps_success_and_blocks_failed_dependencies():
    calls, receipts = [], []
    finished = item(
        "done",
        status="succeeded",
        output={"value": 1},
        output_hash=content_hash({"value": 1}),
    )

    async def execute(work):
        calls.append(work.key)
        if work.key == "bad":
            raise MemberFailureError("provider")
        return {"value": 2}

    async def save(values):
        receipts.append(deepcopy(values))

    items = [
        finished,
        item("bad"),
        item("independent"),
        item("dependent", depends_on=["bad"]),
    ]
    await run_work_items(items, roles={"reader"}, execute=execute, checkpoint=save)
    assert set(calls) == {"bad", "independent"}
    assert [work.status for work in items] == [
        "succeeded",
        "failed",
        "succeeded",
        "blocked",
    ]
    assert receipts[-1][0]["output"] == {"value": 1}


@pytest.mark.parametrize("order", list(permutations(("root", "child", "leaf"))))
async def test_failure_propagates_to_all_descendants_in_any_input_order(order):
    work = {
        "root": item("root"),
        "child": item("child", depends_on=["root"]),
        "leaf": item("leaf", depends_on=["child"]),
    }
    saved = []

    async def execute(current):
        assert current.key == "root"
        raise MemberFailureError("provider")

    async def checkpoint(values):
        saved.append(deepcopy(values))

    await run_work_items(
        [work[key] for key in order],
        roles={"reader"},
        execute=execute,
        checkpoint=checkpoint,
    )
    assert work["root"].status == "failed"
    assert work["child"].status == work["leaf"].status == "blocked"
    assert all(value["status"] != "pending" for value in saved[-1])


async def test_system_failure_cancels_sibling_without_publishing_late_output():
    started, stopped = asyncio.Event(), asyncio.Event()
    saved = []

    async def execute(work):
        if work.key == "lease":
            await started.wait()
            raise RuntimeError("lease revoked")
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def checkpoint(values):
        saved.append(deepcopy(values))

    with pytest.raises(RuntimeError, match="lease revoked"):
        await run_work_items(
            [item("lease"), item("sibling")],
            roles={"reader"},
            execute=execute,
            checkpoint=checkpoint,
        )
    assert stopped.is_set()
    assert all(work["status"] != "succeeded" for work in saved[-1])


@pytest.mark.parametrize(
    "items",
    [
        [item("a", depends_on=["b"]), item("b", depends_on=["a"])],
        [item("a", depends_on=["outside"])],
        [item("a"), item("a")],
        [item("a", status="succeeded", output={"spoofed": True}, output_hash="f" * 64)],
    ],
)
async def test_invalid_dag_or_receipt_never_starts(items):
    async def unused(_):
        pytest.fail("invalid graph must not execute or checkpoint")

    with pytest.raises(ValueError):
        await run_work_items(items, roles={"reader"}, execute=unused, checkpoint=unused)
