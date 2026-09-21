"""演化窄提交协调器（V4 E03c，对应 01-EVOLUTION §5 / 验收 T10–T12）。

协议分两段，provider I/O 永不进入 apply 的数据库事务：

1. **freeze（prepare 阶段）**：模型已返回后，先把冻结负载存入 AttemptStore。
   之后任何持久化失败都以冻结负载恢复重试，绝不重新采样模型（T10）。
2. **apply（短事务）**：调用方持有事务，协调器在事务内依次执行
   锁定 → 重验 owner epoch → 重验来源 manifest → 重验父回执 →
   领域写入（注入的 applier）→ 保存回执并推进游标。任一重验失败抛
   :class:`CommitConflictError`，本批次作废、必须带新 manifest 重新准备；
   领域提交未完成的任何失败都不产生回执——游标只在回执持久化后推进。

回执幂等重放（T11）：领域已提交且回执已保存后，即使响应/投影丢失，
再次 apply 同一 attempt 直接返回原回执，不重复执行领域写入、不重复
消耗预算。

owner epoch（T12 前置）：epoch 不匹配即拒绝提交——切换或重建后的旧
worker 即使恢复也无权写入。

本模块是协议与内核，不接触具体 ORM；生产存储在 E04/E07 接线时以
PostgreSQL 实现 :class:`AttemptStore` 并复用同一协调器。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.contracts import (
    CommittedPrefix,
    CoverageContract,
    EvolutionReceipt,
    ObservationDisposition,
    OutcomeStatus,
)

Applier = Callable[[AsyncSession, "FrozenAttempt"], Awaitable["ApplierResult"]]
SourceVerifier = Callable[[AsyncSession, "FrozenAttempt"], Awaitable[None]]
OwnerEpochProvider = Callable[[AsyncSession], Awaitable[int]]


class CommitConflictError(Exception):
    """短事务重验失败：本批次必须作废并带新输入重新准备。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


class StaleOwnerError(CommitConflictError):
    """owner epoch 已推进，旧 worker 无提交权（V4 T12 前置）。"""

    def __init__(self, detail: str) -> None:
        super().__init__("stale_owner", detail)


class FrozenAttempt(BaseModel):
    """prepare 阶段冻结的一个窄批次：模型返回后的完整待提交内容。"""

    model_config = ConfigDict(extra="forbid")

    novel_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1, max_length=120)
    attempt_id: str = Field(min_length=1, max_length=120)
    owner_epoch: int = Field(ge=1)
    producer_version: str = Field(min_length=1, max_length=64)
    source_manifest_hash: str = Field(min_length=32, max_length=64)
    previous_receipt: str | None = Field(default=None, min_length=32, max_length=64)
    previous_committed_prefix: CommittedPrefix | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ApplierResult(BaseModel):
    """applier 在短事务内完成的领域写入摘要，用于组装回执。"""

    model_config = ConfigDict(extra="forbid")

    committed_prefix: CommittedPrefix
    outcome_status: OutcomeStatus = "committed"
    world_result_refs: list[dict[str, str]] = Field(default_factory=list)
    story_result_refs: list[dict[str, str]] = Field(default_factory=list)
    evidence_result_refs: list[dict[str, str]] = Field(default_factory=list)
    pending_decisions: list[str] = Field(default_factory=list, max_length=64)
    coverage: CoverageContract = Field(default_factory=CoverageContract)
    observation_dispositions: dict[ObservationDisposition, int] = Field(
        default_factory=dict
    )
    paid_call_receipts: list[dict[str, str]] = Field(default_factory=list)


class AttemptStore(Protocol):
    """冻结负载与回执的持久化 port；生产实现须与 apply 同处短事务。"""

    async def save_frozen(self, attempt: FrozenAttempt) -> None: ...

    async def load_frozen(self, run_id: str, attempt_id: str) -> FrozenAttempt | None: ...

    async def save_receipt(self, receipt: EvolutionReceipt) -> None: ...

    async def load_receipt(
        self, run_id: str, attempt_id: str
    ) -> EvolutionReceipt | None: ...

    async def load_head_receipt(self, run_id: str) -> EvolutionReceipt | None: ...


class InMemoryAttemptStore:
    """测试与协议验证用的内存实现；不承担生产持久化。"""

    def __init__(self) -> None:
        self._frozen: dict[tuple[str, str], FrozenAttempt] = {}
        self._receipts: dict[tuple[str, str], EvolutionReceipt] = {}
        self._heads: dict[str, EvolutionReceipt] = {}

    async def save_frozen(self, attempt: FrozenAttempt) -> None:
        self._frozen[(attempt.run_id, attempt.attempt_id)] = attempt

    async def load_frozen(self, run_id: str, attempt_id: str) -> FrozenAttempt | None:
        return self._frozen.get((run_id, attempt_id))

    async def save_receipt(self, receipt: EvolutionReceipt) -> None:
        key = (receipt.run_id, receipt.attempt_id)
        if key in self._receipts:
            raise CommitConflictError(
                "receipt_exists", "receipt is immutable once persisted"
            )
        self._receipts[key] = receipt
        self._heads[receipt.run_id] = receipt

    async def load_receipt(self, run_id: str, attempt_id: str) -> EvolutionReceipt | None:
        return self._receipts.get((run_id, attempt_id))

    async def load_head_receipt(self, run_id: str) -> EvolutionReceipt | None:
        return self._heads.get(run_id)


def new_attempt_id() -> str:
    return uuid4().hex


async def freeze_attempt(
    store: AttemptStore,
    attempt: FrozenAttempt,
) -> FrozenAttempt:
    """prepare 阶段：模型返回后先冻结待提交内容（T10 恢复基础）。"""
    await store.save_frozen(attempt)
    return attempt


async def apply_frozen(
    db: AsyncSession,
    *,
    frozen: FrozenAttempt,
    store: AttemptStore,
    applier: Applier,
    source_verifier: SourceVerifier,
    owner_epoch_provider: OwnerEpochProvider,
) -> EvolutionReceipt:
    """短事务窄提交：重验 → 领域写入 → 回执持久化 → 游标推进。

    调用方负责 BEGIN/COMMIT；任一步抛错时回滚即回到未提交状态，
    冻结负载仍在 store 中，可用 :func:`recover_attempt` 免采样恢复。
    """
    replayed = await store.load_receipt(frozen.run_id, frozen.attempt_id)
    if replayed is not None:
        # T11：领域已提交、回执已保存——直接返回原回执，不重复写入。
        return replayed

    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"evolution_commit:{frozen.novel_id}:{frozen.run_id}"},
        )

    current_epoch = await owner_epoch_provider(db)
    if current_epoch != frozen.owner_epoch:
        raise StaleOwnerError(
            f"owner epoch moved to {current_epoch}, attempt froze {frozen.owner_epoch}"
        )

    await source_verifier(db, frozen)

    head = await store.load_head_receipt(frozen.run_id)
    if frozen.previous_receipt is None:
        if head is not None:
            raise CommitConflictError(
                "parent_advanced",
                f"run already committed receipt {head.attempt_id}; "
                "bootstrap attempt expects no parent",
            )
    else:
        if head is None:
            raise CommitConflictError(
                "parent_missing",
                "attempt expects a parent receipt but the run head is empty",
            )
        # 父身份 = 冻结时看到的 run head（父 attempt 及其已提交前缀）；
        # 任何漂移都意味着并发推进，本批次作废重准备。
        if (
            head.attempt_id != frozen.previous_receipt
            or head.committed_prefix != frozen.previous_committed_prefix
        ):
            raise CommitConflictError(
                "parent_advanced",
                "run head moved beyond the parent this attempt prepared on",
            )

    result = await applier(db, frozen)

    receipt = EvolutionReceipt(
        run_id=frozen.run_id,
        attempt_id=frozen.attempt_id,
        owner_epoch=frozen.owner_epoch,
        producer_version=frozen.producer_version,
        source_manifest_hash=frozen.source_manifest_hash,
        input_state_receipt=frozen.source_manifest_hash,
        previous_receipt=frozen.previous_receipt,
        previous_committed_prefix=frozen.previous_committed_prefix,
        observation_dispositions=result.observation_dispositions,
        world_result_refs=result.world_result_refs,
        story_result_refs=result.story_result_refs,
        evidence_result_refs=result.evidence_result_refs,
        pending_decisions=result.pending_decisions,
        coverage=result.coverage,
        committed_prefix=result.committed_prefix,
        paid_call_receipts=result.paid_call_receipts,
        execution_status="succeeded",
        outcome_status=result.outcome_status,
    )
    await store.save_receipt(receipt)
    return receipt


async def recover_attempt(
    db: AsyncSession,
    *,
    run_id: str,
    attempt_id: str,
    store: AttemptStore,
    applier: Applier,
    source_verifier: SourceVerifier,
    owner_epoch_provider: OwnerEpochProvider,
) -> EvolutionReceipt:
    """故障恢复入口：复用冻结负载重验重提交，全程不接触 provider（T10）。

    领域提交后响应丢失的场景（T11）由 ``apply_frozen`` 开头的回执重放
    分支覆盖——本函数同样先走该分支。
    """
    frozen = await store.load_frozen(run_id, attempt_id)
    if frozen is None:
        raise CommitConflictError(
            "frozen_missing", f"no frozen attempt {attempt_id} for run {run_id}"
        )
    return await apply_frozen(
        db,
        frozen=frozen,
        store=store,
        applier=applier,
        source_verifier=source_verifier,
        owner_epoch_provider=owner_epoch_provider,
    )
