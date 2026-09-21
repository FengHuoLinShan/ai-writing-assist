"""AttemptStore 的关系数据库实现与 run 注册表操作（V4 E04）。

生产部署在 PostgreSQL；单元测试在 SQLite 上运行同一实现（与仓库其他
store 的方言中立约定一致）。store 绑定单个会话与 ``novel_id``——冻结、
回执与 head 查询都在该作用域内，跨项目读不到。冻结尝试与回执的写入
遵守窄提交协议：

- ``save_receipt`` 在同一事务内推进 run 游标与 head 指针——游标只在
  回执落库后前进；
- 已存在的回执不可改写（重放语义，T11）；
- ``reserve_budget`` 用条件 UPDATE 原子预留（T21）：预算不足时预留失败，
  调用方不得发出对应请求。
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.commit import CommitConflictError, FrozenAttempt
from modules.evolution.contracts import CommittedPrefix, EvolutionReceipt
from modules.evolution.models import (
    EvolutionFrozenAttempt,
    EvolutionReceiptRecord,
    EvolutionRun,
)


class BudgetExhaustedError(Exception):
    """根预算不足以完成本次预留；调用方不得发出对应请求（T21）。"""


def _parse_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class PostgresAttemptStore:
    """``AttemptStore`` 的 SQLAlchemy 实现（PG 生产 / SQLite 测试）。

    绑定 ``(db, novel_id)`` 作用域：每个短事务/会话各建一个实例。
    """

    def __init__(self, db: AsyncSession, novel_id: str | uuid.UUID) -> None:
        self._db = db
        self._novel_id = _parse_uuid(novel_id)

    @property
    def novel_id(self) -> uuid.UUID:
        return self._novel_id

    # ------------------------------------------------------------------
    # run 注册表
    # ------------------------------------------------------------------

    async def register_run(
        self,
        run_key: str,
        *,
        mode: str,
        budget_total: int = 0,
        owner_epoch: int = 1,
        execution_mode: str = "live",
    ) -> EvolutionRun:
        existing = await self.load_run(run_key)
        if existing is not None:
            return existing
        if execution_mode == "live":
            # E07.c 单写者门禁：同项目同时只有一个 live 写入 run；
            # shadow run 只读来源、产物隔离，不占写入位。
            await self._assert_single_live_writer(exclude_run_key=run_key)
        run = EvolutionRun(
            novel_id=self._novel_id,
            run_key=run_key,
            mode=mode,
            owner_epoch=owner_epoch,
            execution_mode=execution_mode,
            budget_total=budget_total,
            budget_remaining=budget_total,
        )
        self._db.add(run)
        await self._db.flush()
        return run

    async def load_run(self, run_key: str) -> EvolutionRun | None:
        return (
            await self._db.execute(
                select(EvolutionRun).where(
                    EvolutionRun.novel_id == self._novel_id,
                    EvolutionRun.run_key == run_key,
                )
            )
        ).scalar_one_or_none()

    async def advance_owner_epoch(self, run_key: str) -> int:
        run = await self.load_run(run_key)
        if run is None:
            raise CommitConflictError(
                "run_missing", f"evolution run {run_key} not registered"
            )
        run.owner_epoch += 1
        await self._db.flush()
        return run.owner_epoch

    def owner_epoch_provider(self, run_key: str):
        """装配 E03c ``apply_frozen`` 的 epoch provider。"""

        async def _provider(db: AsyncSession) -> int:
            run = await self.load_run(run_key)
            if run is None:
                raise CommitConflictError(
                    "run_missing", f"evolution run {run_key} not registered"
                )
            return run.owner_epoch

        return _provider

    async def _assert_single_live_writer(self, *, exclude_run_key: str) -> None:
        from sqlalchemy import func

        count = (
            await self._db.execute(
                select(func.count(EvolutionRun.id)).where(
                    EvolutionRun.novel_id == self._novel_id,
                    EvolutionRun.run_key != exclude_run_key,
                    EvolutionRun.execution_mode == "live",
                    EvolutionRun.status == "active",
                )
            )
        ).scalar_one()
        if count:
            raise CommitConflictError(
                "single_writer_violation",
                f"novel already has {count} active live evolution run(s); "
                "drain or stop them before registering a new writer",
            )

    async def switch_project_engine(
        self,
        run_key: str,
        *,
        to_engine: str,
    ) -> EvolutionRun:
        """E07.c 项目级切换：排空旧 owner 并推进 epoch（fence 在途旧 worker）。

        只改变本 run 的引擎归属与代际，不删除任何历史回执；排空后旧
        epoch 的 worker 即使恢复也在持久化边界被拒（E06 fencing）。
        """
        run = await self.load_run(run_key)
        if run is None:
            raise CommitConflictError(
                "run_missing", f"evolution run {run_key} not registered"
            )
        run.status = "drained"
        run.owner_epoch += 1
        run.active_engine = to_engine
        await self._db.flush()
        return run

    async def reserve_budget(self, run_key: str, units: int) -> int:
        """原子预留根预算（T21）：剩余不足即失败，绝不透支。"""
        if units <= 0:
            raise ValueError("budget reservation must be positive")
        result = await self._db.execute(
            update(EvolutionRun)
            .where(
                EvolutionRun.novel_id == self._novel_id,
                EvolutionRun.run_key == run_key,
                EvolutionRun.budget_remaining >= units,
            )
            .values(budget_remaining=EvolutionRun.budget_remaining - units)
        )
        if result.rowcount != 1:
            raise BudgetExhaustedError(
                f"budget exhausted: cannot reserve {units} for run {run_key}"
            )
        await self._db.flush()
        run = await self.load_run(run_key)
        return int(run.budget_remaining) if run else 0

    # ------------------------------------------------------------------
    # AttemptStore 协议
    # ------------------------------------------------------------------

    async def save_frozen(self, attempt: FrozenAttempt) -> None:
        existing = await self.load_frozen(attempt.run_id, attempt.attempt_id)
        if existing is not None:
            if existing.source_manifest_hash != attempt.source_manifest_hash:
                raise CommitConflictError(
                    "frozen_exists",
                    "attempt already frozen with a different manifest",
                )
            return
        self._db.add(
            EvolutionFrozenAttempt(
                novel_id=self._novel_id,
                run_key=attempt.run_id,
                attempt_key=attempt.attempt_id,
                owner_epoch=attempt.owner_epoch,
                producer_version=attempt.producer_version,
                source_manifest_hash=attempt.source_manifest_hash,
                previous_receipt=attempt.previous_receipt,
                previous_prefix_json=(
                    attempt.previous_committed_prefix.model_dump()
                    if attempt.previous_committed_prefix
                    else None
                ),
                payload_json=attempt.payload,
            )
        )
        await self._db.flush()

    async def load_frozen(self, run_id: str, attempt_id: str) -> FrozenAttempt | None:
        row = (
            await self._db.execute(
                select(EvolutionFrozenAttempt).where(
                    EvolutionFrozenAttempt.novel_id == self._novel_id,
                    EvolutionFrozenAttempt.run_key == run_id,
                    EvolutionFrozenAttempt.attempt_key == attempt_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return FrozenAttempt(
            novel_id=str(row.novel_id),
            run_id=row.run_key,
            attempt_id=row.attempt_key,
            owner_epoch=row.owner_epoch,
            producer_version=row.producer_version,
            source_manifest_hash=row.source_manifest_hash,
            previous_receipt=row.previous_receipt,
            previous_committed_prefix=(
                CommittedPrefix.model_validate(row.previous_prefix_json)
                if row.previous_prefix_json
                else None
            ),
            payload=row.payload_json or {},
        )

    async def save_receipt(self, receipt: EvolutionReceipt) -> None:
        existing = await self.load_receipt(receipt.run_id, receipt.attempt_id)
        if existing is not None:
            raise CommitConflictError(
                "receipt_exists", "receipt is immutable once persisted"
            )
        frozen = await self.load_frozen(receipt.run_id, receipt.attempt_id)
        if frozen is None:
            raise CommitConflictError(
                "frozen_missing",
                "receipt requires its frozen attempt to exist first",
            )
        record = EvolutionReceiptRecord(
            novel_id=self._novel_id,
            run_key=receipt.run_id,
            attempt_key=receipt.attempt_id,
            execution_status=receipt.execution_status,
            committed_scene_index=receipt.committed_prefix.through_scene_index,
            committed_source_revision=(receipt.committed_prefix.through_source_revision),
            receipt_json=receipt.model_dump(mode="json"),
        )
        # T12 完整 fencing：游标推进以 owner_epoch 匹配为条件——即使旧
        # worker 在 epoch 推进前通过了 apply 起点的检查，持久化边界也会
        # 拒绝其回执，run 游标与 head 不被旧代际移动。
        fenced = await self._db.execute(
            update(EvolutionRun)
            .where(
                EvolutionRun.novel_id == self._novel_id,
                EvolutionRun.run_key == receipt.run_id,
                EvolutionRun.owner_epoch == receipt.owner_epoch,
            )
            .values(
                committed_scene_index=receipt.committed_prefix.through_scene_index,
                committed_source_revision=(
                    receipt.committed_prefix.through_source_revision
                ),
                head_attempt_id=record.id,
            )
        )
        if fenced.rowcount != 1:
            run = await self.load_run(receipt.run_id)
            from modules.evolution.commit import StaleOwnerError

            raise StaleOwnerError(
                f"receipt fenced at persistence boundary: run epoch is "
                f"{run.owner_epoch if run else 'missing'}, receipt froze "
                f"{receipt.owner_epoch}"
            )
        # fencing 通过后才落回执记录并把冻结尝试标记 applied（同事务）。
        self._db.add(record)
        await self._db.execute(
            update(EvolutionFrozenAttempt)
            .where(
                EvolutionFrozenAttempt.novel_id == self._novel_id,
                EvolutionFrozenAttempt.run_key == receipt.run_id,
                EvolutionFrozenAttempt.attempt_key == receipt.attempt_id,
            )
            .values(status="applied")
        )
        await self._db.flush()

    async def load_receipt(self, run_id: str, attempt_id: str) -> EvolutionReceipt | None:
        row = (
            await self._db.execute(
                select(EvolutionReceiptRecord).where(
                    EvolutionReceiptRecord.novel_id == self._novel_id,
                    EvolutionReceiptRecord.run_key == run_id,
                    EvolutionReceiptRecord.attempt_key == attempt_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return EvolutionReceipt.model_validate(row.receipt_json)

    async def load_head_receipt(self, run_id: str) -> EvolutionReceipt | None:
        row = (
            await self._db.execute(
                select(EvolutionReceiptRecord)
                .where(
                    EvolutionReceiptRecord.novel_id == self._novel_id,
                    EvolutionReceiptRecord.run_key == run_id,
                )
                .order_by(
                    EvolutionReceiptRecord.committed_scene_index.desc(),
                    EvolutionReceiptRecord.committed_source_revision.desc(),
                    EvolutionReceiptRecord.created_at.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return EvolutionReceipt.model_validate(row.receipt_json)

    async def page_receipts(
        self,
        run_id: str,
        *,
        after: tuple[int, str] | None = None,
        limit: int,
    ) -> list[EvolutionReceipt]:
        """按 (committed_scene_index, attempt_key) 键集分页读取回执。"""
        conditions = [
            EvolutionReceiptRecord.novel_id == self._novel_id,
            EvolutionReceiptRecord.run_key == run_id,
        ]
        if after is not None:
            after_scene, after_attempt = after
            conditions.append(
                or_(
                    EvolutionReceiptRecord.committed_scene_index > after_scene,
                    and_(
                        EvolutionReceiptRecord.committed_scene_index == after_scene,
                        EvolutionReceiptRecord.attempt_key > after_attempt,
                    ),
                )
            )
        rows = (
            (
                await self._db.execute(
                    select(EvolutionReceiptRecord)
                    .where(*conditions)
                    .order_by(
                        EvolutionReceiptRecord.committed_scene_index,
                        EvolutionReceiptRecord.attempt_key,
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [EvolutionReceipt.model_validate(row.receipt_json) for row in rows]
