"""E04 持久化与编排测试：run 注册表/冻结/回执落库、T07 前序屏障、
有限并行准入与 T21 预算原子预留。"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.commit import (
    ApplierResult,
    CommitConflictError,
    apply_frozen,
    freeze_attempt,
    new_attempt_id,
)
from modules.evolution.contracts import CommittedPrefix
from modules.evolution.orchestrator import (
    SceneTask,
    manifest_includes_committed_predecessor,
    plan_parallel_batches,
    prepare_scene_input,
)
from modules.evolution.store import (
    BudgetExhaustedError,
    PostgresAttemptStore,
)

NOVEL_RUN = "run-e04"


def _prefix(scene: int, revision: int = 1) -> CommittedPrefix:
    return CommittedPrefix(through_scene_index=scene, through_source_revision=revision)


async def _register(db: AsyncSession, novel_id: str, budget: int = 10) -> None:
    store = PostgresAttemptStore(db, novel_id)
    await store.register_run(NOVEL_RUN, mode="append", budget_total=budget)


async def _commit_attempt(
    db: AsyncSession,
    novel_id: str,
    *,
    prefix: CommittedPrefix,
    payload: dict | None = None,
    previous_receipt: str | None = None,
    previous_prefix: CommittedPrefix | None = None,
):
    store = PostgresAttemptStore(db, novel_id)
    attempt_id = new_attempt_id()
    frozen = await freeze_attempt(
        store,
        _frozen(
            novel_id,
            attempt_id,
            previous_receipt=previous_receipt,
            previous_prefix=previous_prefix,
            payload=payload or {},
        ),
    )
    receipt = await apply_frozen(
        db,
        frozen=frozen,
        store=store,
        applier=_noop_applier(prefix),
        source_verifier=_noop_verifier,
        owner_epoch_provider=store.owner_epoch_provider(NOVEL_RUN),
    )
    return store, receipt


def _frozen(
    novel_id: str,
    attempt_id: str,
    *,
    previous_receipt: str | None = None,
    previous_prefix: CommittedPrefix | None = None,
    payload: dict | None = None,
):
    from modules.evolution.commit import FrozenAttempt

    return FrozenAttempt(
        novel_id=novel_id,
        run_id=NOVEL_RUN,
        attempt_id=attempt_id,
        owner_epoch=1,
        producer_version="evolution/test",
        source_manifest_hash="a" * 64,
        previous_receipt=previous_receipt,
        previous_committed_prefix=previous_prefix,
        payload=payload or {},
    )


def _noop_applier(prefix: CommittedPrefix):
    async def _applier(db, frozen):
        return ApplierResult(committed_prefix=prefix)

    return _applier


async def _noop_verifier(db, frozen) -> None:
    return None


# ---------------------------------------------------------------------------
# run 注册表 / 冻结 / 回执落库
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_registry_and_novel_scope(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    await _register(db_session, evolution_project_id, budget=5)
    store = PostgresAttemptStore(db_session, evolution_project_id)
    run = await store.load_run(NOVEL_RUN)
    assert run is not None
    assert run.owner_epoch == 1
    assert run.budget_remaining == 5
    assert run.committed_scene_index == -1

    # novel_id 隔离：另一项目读不到本项目的 run。
    other = uuid.uuid4()
    other_store = PostgresAttemptStore(db_session, other)
    assert await other_store.load_run(NOVEL_RUN) is None

    # 重复注册幂等。
    again = await store.register_run(NOVEL_RUN, mode="append")
    assert again.id == run.id


@pytest.mark.asyncio
async def test_receipt_persist_advances_cursor_and_head(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    await _register(db_session, evolution_project_id)
    store, receipt = await _commit_attempt(
        db_session, evolution_project_id, prefix=_prefix(0)
    )

    run = await store.load_run(NOVEL_RUN)
    assert run.committed_scene_index == 0
    assert run.committed_source_revision == 1
    head = await store.load_head_receipt(NOVEL_RUN)
    assert head is not None and head.attempt_id == receipt.attempt_id

    # 回执不可改写（T11）：同 attempt 再次保存报冲突。
    with pytest.raises(CommitConflictError, match="receipt_exists"):
        await store.save_receipt(receipt)

    # 冻结负载 roundtrip 保持语义。
    frozen = await store.load_frozen(NOVEL_RUN, receipt.attempt_id)
    assert frozen is not None and frozen.owner_epoch == 1


# ---------------------------------------------------------------------------
# T07 前序屏障
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scene_input_includes_committed_predecessor_receipt(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """T07：Scene 1 的输入实际包含 Scene 0 的已提交回执身份。"""
    await _register(db_session, evolution_project_id)
    store, first = await _commit_attempt(
        db_session, evolution_project_id, prefix=_prefix(0)
    )

    manifest = await prepare_scene_input(
        store,
        run_key=NOVEL_RUN,
        scene_index=1,
        source_manifest_hash="a" * 64,
    )
    assert manifest.dependency_status == "committed"
    assert manifest.previous_scene_attempt_id == first.attempt_id
    assert manifest.previous_committed_prefix == _prefix(0)
    # 实际输入（序列化清单）里真的带着前序回执，而非碰巧相邻。
    assert first.attempt_id in manifest.model_dump_json()
    assert manifest_includes_committed_predecessor(manifest)


@pytest.mark.asyncio
async def test_scene_input_blocked_without_committed_predecessor(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """前序未提交：输入显式 blocked，不携带假的前序结论。"""
    await _register(db_session, evolution_project_id)
    store = PostgresAttemptStore(db_session, evolution_project_id)

    manifest = await prepare_scene_input(
        store,
        run_key=NOVEL_RUN,
        scene_index=1,
        source_manifest_hash="a" * 64,
    )
    assert manifest.dependency_status == "blocked"
    assert manifest.previous_scene_attempt_id is None
    assert manifest.previous_committed_prefix is None
    assert not manifest_includes_committed_predecessor(manifest)
    assert manifest.blocked_reason

    # Scene 0 无前序要求，不被屏障阻塞。
    bootstrap = await prepare_scene_input(
        store,
        run_key=NOVEL_RUN,
        scene_index=0,
        source_manifest_hash="a" * 64,
    )
    assert manifest_includes_committed_predecessor(bootstrap)


# ---------------------------------------------------------------------------
# 有限并行准入
# ---------------------------------------------------------------------------


def test_disjoint_tasks_within_scene_run_in_parallel() -> None:
    batches = plan_parallel_batches(
        [
            SceneTask(0, "observe-a", frozenset({"entity:A"})),
            SceneTask(0, "observe-b", frozenset({"entity:B"})),
        ]
    )
    assert len(batches) == 1
    assert {task.task_key for task in batches[0]} == {"observe-a", "observe-b"}


def test_overlapping_dependency_keys_serialize() -> None:
    batches = plan_parallel_batches(
        [
            SceneTask(0, "observe-a", frozenset({"entity:A"})),
            SceneTask(0, "verify-a", frozenset({"entity:A"})),
            SceneTask(0, "observe-b", frozenset({"entity:B"})),
        ]
    )
    assert len(batches) == 2
    assert {task.task_key for task in batches[0]} == {"observe-a", "observe-b"}
    assert [task.task_key for task in batches[1]] == ["verify-a"]


def test_narrative_order_barrier_forces_later_batches() -> None:
    """Scene N+1 依赖 N 的提交回执：即使键不相交也必须排在其后。"""
    batches = plan_parallel_batches(
        [
            SceneTask(0, "scene-0", frozenset({"k0"})),
            SceneTask(1, "scene-1", frozenset({"k1"})),
            SceneTask(2, "scene-2", frozenset({"k2"})),
        ]
    )
    assert [[task.task_key for task in batch] for batch in batches] == [
        ["scene-0"],
        ["scene-1"],
        ["scene-2"],
    ]


def test_scene_waits_for_all_tasks_of_predecessor_scene() -> None:
    batches = plan_parallel_batches(
        [
            SceneTask(0, "a", frozenset({"x"})),
            SceneTask(0, "b", frozenset({"x"})),  # 与 a 冲突 → 后批
            SceneTask(1, "c", frozenset()),
        ]
    )
    assert [[task.task_key for task in batch] for batch in batches] == [
        ["a"],
        ["b"],
        ["c"],
    ]


# ---------------------------------------------------------------------------
# T21 预算原子预留
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_reservation_never_overdraws(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    await _register(db_session, evolution_project_id, budget=3)
    store = PostgresAttemptStore(db_session, evolution_project_id)

    assert await store.reserve_budget(NOVEL_RUN, 2) == 1
    assert await store.reserve_budget(NOVEL_RUN, 1) == 0
    with pytest.raises(BudgetExhaustedError):
        await store.reserve_budget(NOVEL_RUN, 1)
    run = await store.load_run(NOVEL_RUN)
    assert run.budget_remaining == 0
    assert run.budget_total == 3


@pytest.mark.asyncio
async def test_concurrent_reservations_reserve_exactly_the_budget(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """T21：并发预留总额恰等于预算，绝不透支出额外请求额度。"""
    await _register(db_session, evolution_project_id, budget=4)
    store = PostgresAttemptStore(db_session, evolution_project_id)

    results = await asyncio.gather(
        store.reserve_budget(NOVEL_RUN, 2),
        store.reserve_budget(NOVEL_RUN, 2),
        store.reserve_budget(NOVEL_RUN, 2),
        return_exceptions=True,
    )
    succeeded = [value for value in results if not isinstance(value, BaseException)]
    exhausted = [value for value in results if isinstance(value, BudgetExhaustedError)]
    assert len(succeeded) == 2
    assert len(exhausted) == 1
    run = await store.load_run(NOVEL_RUN)
    assert run.budget_remaining == 0
