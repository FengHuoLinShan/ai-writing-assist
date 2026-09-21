"""演化恢复：分页回放、链连续性校验与有界检查点（V4 E06）。

崩溃或切换后的恢复不以“任务进度 100%”为准，而是重放**已提交回执链**：

- **分页回放**：按 ``(committed_scene_index, attempt_key)`` 键集分页，
  每页有界；总页数受 ``max_pages`` 约束——长书不逐次全书扫描。
- **链连续性**：每笔回执的 ``previous_receipt`` 必须精确链接前一笔回执；
  缺口即 :class:`ChainGapError`——fail-closed，明确要求人工续接，
  不无条件跳过（计划 §7.1 旧 checkpoint 处理规则）。
- **检查点信任锚**：``from_scene_index`` 之前的页不扫描（有界增量），
  锚点与 head 回执的一致性先经 :func:`verify_run_checkpoint` 校验。
- **owner fence**：恢复期间 epoch 已推进的 run 拒绝继续（复用 E03c
  ``StaleOwnerError``；持久化边界的完整 fencing 见 ``store.save_receipt``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.commit import CommitConflictError, StaleOwnerError
from modules.evolution.contracts import CommittedPrefix, EvolutionReceipt
from modules.evolution.store import PostgresAttemptStore

DEFAULT_PAGE_SIZE = 200
DEFAULT_MAX_PAGES = 100_000


class ChainGapError(Exception):
    """回执链不连续：fail-closed，需人工续接，不跳过缺口。"""


class CheckpointDriftError(Exception):
    """run 游标与 head 回执不一致：检查点不可信，先修复再恢复。"""


class ReplayBoundExceededError(Exception):
    """回放超出有界约束：拒绝无界全书扫描。"""


@dataclass
class RecoveryState:
    """一次恢复重放的结果摘要。"""

    run_key: str
    committed_prefix: CommittedPrefix | None = None
    receipt_count: int = 0
    pages_read: int = 0
    rows_scanned: int = 0
    from_scene_index: int = 0
    attempt_ids: list[str] = field(default_factory=list)


def _links_to(receipt: EvolutionReceipt, expected_previous: str | None) -> bool:
    return receipt.previous_receipt == expected_previous


async def verify_run_checkpoint(
    db: AsyncSession,
    store: PostgresAttemptStore,
    run_key: str,
    *,
    expect_epoch: int | None = None,
) -> tuple[CommittedPrefix | None, EvolutionReceipt | None]:
    """校验 run 游标与 head 回执一致（检查点完整性 + owner fence）。"""
    run = await store.load_run(run_key)
    if run is None:
        raise CommitConflictError(
            "run_missing", f"evolution run {run_key} not registered"
        )
    if expect_epoch is not None and run.owner_epoch != expect_epoch:
        raise StaleOwnerError(
            f"recovery fence: run epoch is {run.owner_epoch}, expected {expect_epoch}"
        )
    head = await store.load_head_receipt(run_key)
    if run.committed_scene_index < 0:
        return None, head
    if head is None:
        raise CheckpointDriftError(
            f"run {run_key} cursor at scene {run.committed_scene_index} "
            "but no head receipt exists"
        )
    if (
        head.committed_prefix.through_scene_index != run.committed_scene_index
        or head.committed_prefix.through_source_revision != run.committed_source_revision
    ):
        raise CheckpointDriftError(
            f"run {run_key} cursor "
            f"({run.committed_scene_index}/{run.committed_source_revision}) "
            "drifts from head receipt "
            f"({head.committed_prefix.through_scene_index}/"
            f"{head.committed_prefix.through_source_revision})"
        )
    return head.committed_prefix, head


async def replay_committed_prefix(
    db: AsyncSession,
    store: PostgresAttemptStore,
    run_key: str,
    *,
    from_scene_index: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> RecoveryState:
    """分页重放已提交回执链，返回恢复状态摘要。

    ``from_scene_index`` 是检查点信任锚：其之前的页不扫描（有界增量），
    链校验从锚点之后继续——锚之前的链由持久化检查点担保。
    """
    state = RecoveryState(run_key=run_key, from_scene_index=from_scene_index)
    after: tuple[int, str] | None = None
    if from_scene_index > 0:
        # 跳到锚点 Scene 的第一笔回执（attempt_key 上界保证命中该 Scene 起点）。
        after = (from_scene_index - 1, "f" * 120)
    previous_attempt: str | None = None
    checked_any = False
    while True:
        if state.pages_read >= max_pages:
            raise ReplayBoundExceededError(
                f"replay exceeded max_pages={max_pages} for run {run_key}"
            )
        page = await store.page_receipts(run_key, after=after, limit=page_size)
        if not page:
            break
        state.pages_read += 1
        state.rows_scanned += len(page)
        for receipt in page:
            if not checked_any:
                if from_scene_index == 0 and receipt.previous_receipt is not None:
                    raise ChainGapError(
                        f"chain head {receipt.attempt_id} unexpectedly links "
                        f"to {receipt.previous_receipt}"
                    )
                checked_any = True
            elif not _links_to(receipt, previous_attempt):
                raise ChainGapError(
                    f"receipt {receipt.attempt_id} links to "
                    f"{receipt.previous_receipt}, expected {previous_attempt}"
                )
            previous_attempt = receipt.attempt_id
            state.receipt_count += 1
            state.attempt_ids.append(receipt.attempt_id)
            state.committed_prefix = receipt.committed_prefix
        last = page[-1]
        after = (last.committed_prefix.through_scene_index, last.attempt_id)
        if len(page) < page_size:
            break
    return state
