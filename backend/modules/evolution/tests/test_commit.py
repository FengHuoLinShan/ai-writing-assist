"""E03c 窄提交协议故障注入测试（V4 T10/T11/T12 前置 / 01-EVOLUTION §5）。

- T10：provider 已返回、持久化失败 → 复用冻结负载重验重提交，不重新采样。
- T11：领域提交后响应丢失 → 按尝试 ID 返回原回执，不重复领域写入。
- 游标纪律：失败不产生回执、不推进 committed_prefix。
- 冲突：来源漂移 / 父回执被并发推进 / owner epoch 过期均拒绝提交。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.collaboration import content_hash
from modules.evolution.commit import (
    ApplierResult,
    CommitConflictError,
    FrozenAttempt,
    InMemoryAttemptStore,
    StaleOwnerError,
    apply_frozen,
    freeze_attempt,
    new_attempt_id,
    recover_attempt,
)
from modules.evolution.contracts import CommittedPrefix
from modules.story.continuity.models import MemoryEvent
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene


class _Sampler:
    """扮演 provider：每次调用计一次费；恢复路径绝不触碰。"""

    def __init__(self) -> None:
        self.calls = 0

    def sample(self, text: str) -> dict[str, Any]:
        self.calls += 1
        return {"events": [{"summary": text, "dimension": "entities"}]}


async def _scene(db: AsyncSession, novel_id: str) -> Scene:
    item = Scene(
        novel_id=uuid.UUID(novel_id),
        scene_index=0,
        title="Scene 0",
        chapter_ids=[1],
        scene_chunks=[{"chapter_index": 1}],
        status="draft",
    )
    db.add(item)
    await db.flush()
    return item


def _manifest(sources: dict[str, str]) -> str:
    return content_hash(sources)


def _attempt(
    novel_id: str,
    *,
    run_id: str,
    attempt_id: str,
    manifest: str,
    previous_receipt: str | None = None,
    previous_committed_prefix: CommittedPrefix | None = None,
    owner_epoch: int = 1,
    payload: dict[str, Any] | None = None,
) -> FrozenAttempt:
    return FrozenAttempt(
        novel_id=novel_id,
        run_id=run_id,
        attempt_id=attempt_id,
        owner_epoch=owner_epoch,
        producer_version="evolution/test",
        source_manifest_hash=manifest,
        previous_receipt=previous_receipt,
        previous_committed_prefix=previous_committed_prefix,
        payload=payload or {},
    )


def _applier_result(prefix: CommittedPrefix) -> ApplierResult:
    return ApplierResult(committed_prefix=prefix)


class _Harness:
    def __init__(self, db: AsyncSession, novel_id: str, scene: Scene) -> None:
        self.db = db
        self.novel_id = novel_id
        # rollback 会过期 ORM 属性；固化普通字符串避免异步会话外的惰性加载。
        self.scene_id = str(scene.id)
        self.store = InMemoryAttemptStore()
        self.sources = {"chapter-1": "林舟推门而入。"}
        self.owner_epoch = 1
        self.apply_calls = 0

    def manifest(self) -> str:
        return _manifest(self.sources)

    async def applier(self, db: AsyncSession, frozen: FrozenAttempt) -> ApplierResult:
        self.apply_calls += 1
        events = [
            {**event, "source": "evolution_test"} for event in frozen.payload["events"]
        ]
        await MemoryService().record_scene_events(
            db,
            self.novel_id,
            scene_id=self.scene_id,
            scene_index=0,
            chapter_index=1,
            events=events,
            producer_family="evolution_test",
        )
        return _applier_result(
            CommittedPrefix(through_scene_index=0, through_source_revision=1)
        )

    async def source_verifier(self, db: AsyncSession, frozen: FrozenAttempt) -> None:
        if self.manifest() != frozen.source_manifest_hash:
            raise CommitConflictError(
                "source_changed", "frozen manifest no longer matches sources"
            )

    async def epoch_provider(self, db: AsyncSession) -> int:
        return self.owner_epoch

    async def scene_events(self) -> list[MemoryEvent]:
        return list(
            (
                await self.db.execute(
                    select(MemoryEvent).where(
                        MemoryEvent.novel_id == uuid.UUID(self.novel_id),
                        MemoryEvent.scene_id == uuid.UUID(self.scene_id),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def apply(self, frozen: FrozenAttempt):
        return await apply_frozen(
            self.db,
            frozen=frozen,
            store=self.store,
            applier=self.applier,
            source_verifier=self.source_verifier,
            owner_epoch_provider=self.epoch_provider,
        )

    async def recover(self, run_id: str, attempt_id: str):
        return await recover_attempt(
            self.db,
            run_id=run_id,
            attempt_id=attempt_id,
            store=self.store,
            applier=self.applier,
            source_verifier=self.source_verifier,
            owner_epoch_provider=self.epoch_provider,
        )


async def _harness(db: AsyncSession, evolution_project_id: str) -> _Harness:
    scene = await _scene(db, evolution_project_id)
    # 场景是"既有已提交数据"：先封存，使故障注入后的 rollback 只回滚
    # 窄事务内的写入（与生产语义一致——正文/场景不在演化提交事务里创建）。
    await db.commit()
    return _Harness(db, evolution_project_id, scene)


@pytest.mark.asyncio
async def test_t10_persistence_failure_resumes_frozen_without_resampling(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """T10：持久化失败后复用冻结返回，provider 只采样一次、领域只写一次。"""
    harness = await _harness(db_session, evolution_project_id)
    sampler = _Sampler()
    run_id, attempt_id = "run-1", new_attempt_id()
    frozen = _attempt(
        evolution_project_id,
        run_id=run_id,
        attempt_id=attempt_id,
        manifest=harness.manifest(),
        payload=sampler.sample("青竹取出铜钥匙"),
    )
    await freeze_attempt(harness.store, frozen)

    class _PersistFailureError(Exception):
        pass

    original_applier = harness.applier

    async def failing_applier(db, frozen_attempt):
        await original_applier(db, frozen_attempt)
        raise _PersistFailureError("持久化阶段失败")

    with pytest.raises(_PersistFailureError):
        await apply_frozen(
            db_session,
            frozen=frozen,
            store=harness.store,
            applier=failing_applier,
            source_verifier=harness.source_verifier,
            owner_epoch_provider=harness.epoch_provider,
        )
    await db_session.rollback()

    receipt = await harness.recover(run_id, attempt_id)

    assert sampler.calls == 1  # 从未重新采样（T10 核心）
    # 首次领域写入随 rollback 未落库；恢复重放一次成功——最终恰一笔持久化。
    events = await harness.scene_events()
    assert len(events) == 1
    assert events[0].source == "evolution_test"
    assert receipt.execution_status == "succeeded"
    assert receipt.committed_prefix == CommittedPrefix(
        through_scene_index=0, through_source_revision=1
    )


@pytest.mark.asyncio
async def test_t11_response_loss_replays_original_receipt(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """T11：领域提交后响应丢失，按尝试 ID 重放原回执，不重复写入。"""
    harness = await _harness(db_session, evolution_project_id)
    run_id, attempt_id = "run-1", new_attempt_id()
    frozen = _attempt(
        evolution_project_id,
        run_id=run_id,
        attempt_id=attempt_id,
        manifest=harness.manifest(),
        payload={"events": [{"summary": "钟声响起", "dimension": "entities"}]},
    )
    await freeze_attempt(harness.store, frozen)

    first = await harness.apply(frozen)
    assert harness.apply_calls == 1

    # 模拟响应/投影丢失：结果没送到调用方。
    del first
    replayed = await harness.recover(run_id, attempt_id)

    assert harness.apply_calls == 1  # 未重复执行领域写入
    assert replayed.attempt_id == attempt_id
    assert replayed.committed_prefix == CommittedPrefix(
        through_scene_index=0, through_source_revision=1
    )
    assert len(await harness.scene_events()) == 1
    head = await harness.store.load_head_receipt(run_id)
    assert head is not None and head.attempt_id == replayed.attempt_id


@pytest.mark.asyncio
async def test_failure_leaves_no_receipt_and_cursor_unchanged(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    harness = await _harness(db_session, evolution_project_id)
    frozen = _attempt(
        evolution_project_id,
        run_id="run-1",
        attempt_id=new_attempt_id(),
        manifest=harness.manifest(),
    )
    await freeze_attempt(harness.store, frozen)

    with pytest.raises(RuntimeError):
        await apply_frozen(
            db_session,
            frozen=frozen,
            store=harness.store,
            applier=self_raising_applier(),
            source_verifier=harness.source_verifier,
            owner_epoch_provider=harness.epoch_provider,
        )

    assert await harness.store.load_head_receipt("run-1") is None


def self_raising_applier():
    async def _applier(db, frozen):
        raise RuntimeError("domain stage failed")

    return _applier


@pytest.mark.asyncio
async def test_source_drift_conflicts_and_requires_new_attempt(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    harness = await _harness(db_session, evolution_project_id)
    frozen = _attempt(
        evolution_project_id,
        run_id="run-1",
        attempt_id=new_attempt_id(),
        manifest=harness.manifest(),
    )
    await freeze_attempt(harness.store, frozen)

    harness.sources["chapter-1"] = "林舟推门而入，屋内烛火摇曳。"  # 正文修改
    with pytest.raises(CommitConflictError, match="source_changed"):
        await harness.apply(frozen)
    assert harness.apply_calls == 0
    assert await harness.scene_events() == []

    # 新 manifest 的新尝试可以提交。
    fresh = _attempt(
        evolution_project_id,
        run_id="run-1",
        attempt_id=new_attempt_id(),
        manifest=harness.manifest(),
        payload={"events": [{"summary": "烛火摇曳", "dimension": "entities"}]},
    )
    await freeze_attempt(harness.store, fresh)
    receipt = await harness.apply(fresh)
    assert receipt.execution_status == "succeeded"


@pytest.mark.asyncio
async def test_parent_advanced_conflict_rejects_stale_attempt(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    harness = await _harness(db_session, evolution_project_id)
    run_id = "run-1"
    first = _attempt(
        evolution_project_id,
        run_id=run_id,
        attempt_id=new_attempt_id(),
        manifest=harness.manifest(),
        payload={"events": [{"summary": "首个批次", "dimension": "entities"}]},
    )
    await freeze_attempt(harness.store, first)
    first_receipt = await harness.apply(first)

    second = _attempt(
        evolution_project_id,
        run_id=run_id,
        attempt_id=new_attempt_id(),
        manifest=harness.manifest(),
        previous_receipt=first_receipt.attempt_id,
        previous_committed_prefix=first_receipt.committed_prefix,
    )
    await freeze_attempt(harness.store, second)

    # 另一个批次抢先在同一 run 上提交，head 前移。
    winner = _attempt(
        evolution_project_id,
        run_id=run_id,
        attempt_id=new_attempt_id(),
        manifest=harness.manifest(),
        previous_receipt=first_receipt.attempt_id,
        previous_committed_prefix=first_receipt.committed_prefix,
        payload={"events": [{"summary": "抢先批次", "dimension": "entities"}]},
    )
    await freeze_attempt(harness.store, winner)
    await harness.apply(winner)

    with pytest.raises(CommitConflictError, match="parent_advanced"):
        await harness.apply(second)
    assert harness.apply_calls == 2  # first + winner；second 未执行


@pytest.mark.asyncio
async def test_stale_owner_epoch_cannot_commit(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """T12 前置：切换/重建后的旧 worker 恢复也无提交权。"""
    harness = await _harness(db_session, evolution_project_id)
    frozen = _attempt(
        evolution_project_id,
        run_id="run-1",
        attempt_id=new_attempt_id(),
        manifest=harness.manifest(),
    )
    await freeze_attempt(harness.store, frozen)

    harness.owner_epoch = 2  # owner 切换，epoch 推进
    with pytest.raises(StaleOwnerError):
        await harness.apply(frozen)
    assert harness.apply_calls == 0
    assert await harness.store.load_head_receipt("run-1") is None
