"""E06 恢复与 fencing 测试（V4 T12 完整语义 / 计划 §7.1、§9）。

- T12 完整：apply 起点检查通过后 epoch 才推进——旧 worker 的回执在
  **持久化边界**被 fence，游标不被旧代际移动。
- 链缺口 fail-closed；run 游标与 head 漂移 fail-closed。
- 分页有界；检查点锚点命中时回放只扫描增量页。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.commit import (
    ApplierResult,
    apply_frozen,
    freeze_attempt,
    new_attempt_id,
)
from modules.evolution.contracts import CommittedPrefix
from modules.evolution.recovery import (
    ChainGapError,
    CheckpointDriftError,
    replay_committed_prefix,
    verify_run_checkpoint,
)
from modules.evolution.store import PostgresAttemptStore

RUN = "run-e06"


def _prefix(scene: int, revision: int = 1) -> CommittedPrefix:
    return CommittedPrefix(through_scene_index=scene, through_source_revision=revision)


def _frozen(
    novel_id: str, attempt_id: str, *, epoch: int = 1, previous=None, prefix=None
):
    from modules.evolution.commit import FrozenAttempt

    return FrozenAttempt(
        novel_id=novel_id,
        run_id=RUN,
        attempt_id=attempt_id,
        owner_epoch=epoch,
        producer_version="evolution/test",
        source_manifest_hash="a" * 64,
        previous_receipt=previous,
        previous_committed_prefix=prefix,
        payload={},
    )


def _applier(prefix: CommittedPrefix, hook=None):
    async def applier(db, frozen):
        if hook is not None:
            await hook(db, frozen)
        return ApplierResult(committed_prefix=prefix)

    return applier


async def _noop_verifier(db, frozen) -> None:
    return None


async def _commit(
    db: AsyncSession,
    store: PostgresAttemptStore,
    novel_id: str,
    *,
    scene: int,
    epoch: int = 1,
    hook=None,
):
    head = await store.load_head_receipt(RUN)
    attempt_id = new_attempt_id()
    frozen = await freeze_attempt(
        store,
        _frozen(
            novel_id,
            attempt_id,
            epoch=epoch,
            previous=head.attempt_id if head else None,
            prefix=head.committed_prefix if head else None,
        ),
    )
    receipt = await apply_frozen(
        db,
        frozen=frozen,
        store=store,
        applier=_applier(_prefix(scene), hook=hook),
        source_verifier=_noop_verifier,
        owner_epoch_provider=store.owner_epoch_provider(RUN),
    )
    return receipt


@pytest.mark.asyncio
async def test_t12_midflight_epoch_switch_fences_at_persistence(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """apply 起点检查通过后 owner 才切换：回执在持久化边界被拒（T12 完整）。"""
    db, nid = db_session, evolution_project_id
    store = PostgresAttemptStore(db, nid)
    await store.register_run(RUN, mode="append", budget_total=10)

    async def switch_owner_midflight(db, frozen):
        # 模拟领域写入期间并发切换 owner：epoch 推进。
        await store.advance_owner_epoch(RUN)

    from modules.evolution.commit import StaleOwnerError

    with pytest.raises(StaleOwnerError, match="fenced at persistence"):
        await _commit(db, store, nid, scene=0, hook=switch_owner_midflight)

    run = await store.load_run(RUN)
    assert run.committed_scene_index == -1  # 游标未被旧代际移动
    assert await store.load_head_receipt(RUN) is None
    frozen_row = None
    from sqlalchemy import select

    from modules.evolution.models import EvolutionFrozenAttempt

    frozen_row = (
        await db.execute(
            select(EvolutionFrozenAttempt).where(EvolutionFrozenAttempt.run_key == RUN)
        )
    ).scalar_one_or_none()
    assert frozen_row is not None and frozen_row.status == "frozen"

    # 新代际的尝试可以正常提交。
    await _commit(db, store, nid, scene=0, epoch=2)
    run = await store.load_run(RUN)
    assert run.committed_scene_index == 0
    assert run.owner_epoch == 2


@pytest.mark.asyncio
async def test_recovery_fence_rejects_stale_epoch(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    from modules.evolution.commit import StaleOwnerError

    db, nid = db_session, evolution_project_id
    store = PostgresAttemptStore(db, nid)
    await store.register_run(RUN, mode="append")
    await _commit(db, store, nid, scene=3)
    await store.advance_owner_epoch(RUN)
    with pytest.raises(StaleOwnerError):
        await verify_run_checkpoint(db, store, RUN, expect_epoch=1)


@pytest.mark.asyncio
async def test_chain_gap_fails_closed(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """链缺口：fail-closed 并指出断点，不跳过、不猜。"""
    db, nid = db_session, evolution_project_id
    store = PostgresAttemptStore(db, nid)
    await store.register_run(RUN, mode="append")
    first = await _commit(db, store, nid, scene=0)
    middle = await _commit(db, store, nid, scene=1)
    await _commit(db, store, nid, scene=2)

    # 人为制造缺口：删除中间一笔回执（模拟历史损毁）。head 与游标仍
    # 一致（drift 校验通过），但从头重放必须暴露断链并 fail-closed。
    from sqlalchemy import delete

    from modules.evolution.models import EvolutionReceiptRecord

    await db.execute(
        delete(EvolutionReceiptRecord).where(
            EvolutionReceiptRecord.attempt_key == middle.attempt_id
        )
    )
    await verify_run_checkpoint(db, store, RUN)  # head/cursor 一致
    with pytest.raises(ChainGapError, match=first.attempt_id):
        await replay_committed_prefix(db, store, RUN)

    # 删除 head 则触发检查点漂移（cursor 指向已不存在的提交）。
    head = await store.load_head_receipt(RUN)
    await db.execute(
        delete(EvolutionReceiptRecord).where(
            EvolutionReceiptRecord.attempt_key == head.attempt_id
        )
    )
    with pytest.raises(CheckpointDriftError):
        await verify_run_checkpoint(db, store, RUN)


@pytest.mark.asyncio
async def test_paged_replay_is_bounded_and_checkpoint_anchor_hits(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """分页有界；检查点锚点命中时只扫描增量页（计划 §9 的语义基础）。"""
    db, nid = db_session, evolution_project_id
    store = PostgresAttemptStore(db, nid)
    await store.register_run(RUN, mode="append")
    for scene in range(6):
        await _commit(db, store, nid, scene=scene)

    full = await replay_committed_prefix(db, store, RUN, page_size=2, max_pages=10)
    assert full.receipt_count == 6
    assert full.pages_read == 3
    assert full.committed_prefix == _prefix(5)
    assert full.attempt_ids[0] is not None and len(set(full.attempt_ids)) == 6

    # 有界约束：max_pages 不够时拒绝无界扫描。
    with pytest.raises(Exception):
        await replay_committed_prefix(db, store, RUN, page_size=2, max_pages=2)

    # 检查点锚点：从 scene 4 起回放，只扫 2 笔回执（1 页）。
    prefix, _head = await verify_run_checkpoint(db, store, RUN)
    assert prefix == _prefix(5)
    incremental = await replay_committed_prefix(
        db, store, RUN, from_scene_index=4, page_size=2
    )
    assert incremental.receipt_count == 2
    assert incremental.pages_read == 1
    assert incremental.committed_prefix == _prefix(5)
