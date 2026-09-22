"""V4 审查（2026-09-22 修复包 1）管线级回归：A01 影子恢复隔离、A07 阶段化恢复。

A01 反例（审查复现）：影子采样成功并冻结 → 回执提交前故障 → 恢复直接执行
调用方传入的正式写入器。修复后执行模式进入冻结/提交协议：负载盖章、首次
与恢复同一写入策略解析、提交边界拒绝影子负载的正式领域写。

A07 反例：provider 最终抛错时回执构造不会执行（失败费用无迹可寻）；观察
构建/冻结持久化失败后无可恢复负载，恢复当作未发生而重新采样。修复后采样
按 ``sampling → sampled → compiled`` 阶段耐久化，失败固化回执，恢复按阶段
区分"结果已取回/费用未知"，费用未知进入待核对（unknown_billing），不自动
重采样。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.evolution.pipeline as pipeline_module
from modules.evolution.commit import (
    ApplierResult,
    CommitConflictError,
    FrozenAttempt,
    apply_frozen,
)
from modules.evolution.contracts import CommittedPrefix
from modules.evolution.pipeline import (
    SamplePendingReconciliationError,
    SceneSourceBinding,
    recover_scene_step,
    run_scene_step,
)
from modules.evolution.store import PostgresAttemptStore
from modules.story.continuity.models import MemoryEvent
from modules.story.outline_state.models import Scene
from modules.writing.facade import create_draft_only, get_latest_draft_for_chapter

SCENE_TEXT = "林舟与青竹在白石城重逢。青竹从袖中取出铜钥匙。"
LINZHOU = "11111111-1111-4111-8111-111111111111"


@dataclass
class _FixpackSampler:
    """带证据引用的确定性采样器；可配置最终抛错或硬崩溃。"""

    calls: int = 0
    final_error: Exception | None = None
    hard_crash: bool = False
    last_call_receipt: dict[str, Any] | None = field(default=None)

    async def sample(self, *, scene_text: str, input_manifest: dict[str, Any]) -> dict:
        self.calls += 1
        if self.hard_crash:
            raise KeyboardInterrupt("worker killed mid-request")
        if self.final_error is not None:
            # 模拟 ProjectLLMSampler 的 A07 行为：最终失败仍固化回执再抛。
            self.last_call_receipt = {
                "provider": "test",
                "schema": "evolution.scene_sample.v1",
                "outcome": "failed_final",
                "usage": {
                    "completion_tokens": 123,
                    "attempts": 1,
                    "unknown_attempts": 0,
                    "usage_complete": True,
                },
            }
            raise self.final_error
        return {
            "observations": [
                {
                    "predicate": "青竹在白石城取出铜钥匙",
                    "modality": "event_observed",
                    "quote": "青竹从袖中取出铜钥匙",
                    "mentions": [
                        {"surface": "林舟", "entity_type": "character"},
                        {"surface": "青竹", "entity_type": "character"},
                    ],
                }
            ],
            "scene_events": [
                {
                    "dimension": "locations",
                    "event_type": "entity_moved",
                    "snapshot_after": {"text_state": "白石城"},
                    "source_observation_indices": [0],
                }
            ],
            "paid_call_receipt": {
                "provider": "test",
                "schema": "evolution.scene_sample.v1",
                "outcome": "succeeded",
                "usage": {"completion_tokens": 7, "attempts": 1},
            },
        }


class _KnownCandidates:
    """林舟 已在 World 注册（精确名证据）。"""

    async def lookup(self, novel_id: str, surface: str) -> list:
        if surface != "林舟":
            return []

        @dataclass
        class _Suggestion:
            existing_entity_id: str
            existing_entity_name: str
            similarity_score: float
            match_method: str

        return [_Suggestion(LINZHOU, surface, 1.0, "exact_name")]


async def _seed(db: AsyncSession, novel_id: str) -> tuple[Scene, SceneSourceBinding]:
    scene = Scene(
        novel_id=uuid.UUID(novel_id),
        scene_index=0,
        title="重逢",
        chapter_ids=[1],
        scene_chunks=[{"chapter_index": 1}],
        status="draft",
    )
    db.add(scene)
    await db.flush()
    await create_draft_only(db, novel_id, 1, "重逢", SCENE_TEXT)
    await db.flush()
    draft = await get_latest_draft_for_chapter(db, novel_id, 1)
    assert draft is not None
    binding = SceneSourceBinding(
        draft_id=str(draft.id),
        chapter_index=1,
        content_hash=str(draft.content_hash),
    )
    return scene, binding


async def _evolution_events(db: AsyncSession, novel_id: str) -> list[MemoryEvent]:
    return list(
        (
            await db.execute(
                select(MemoryEvent).where(
                    MemoryEvent.novel_id == uuid.UUID(novel_id),
                    MemoryEvent.source == "evolution",
                )
            )
        )
        .scalars()
        .all()
    )


def _formal_applier(counter: dict[str, int]):
    """正式写入器哨兵：影子负载一旦经它执行立即失败并计数。"""

    async def applier(db, frozen) -> ApplierResult:
        counter["formal"] = counter.get("formal", 0) + 1
        raise AssertionError("formal applier must never run for a shadow attempt")

    return applier


# ---------------------------------------------------------------------------
# A01：影子冻结结果的恢复不得进入正式写入器
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_recovery_after_receipt_loss_stays_isolated(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """审查 A01 反例：影子冻结后、回执持久化前故障——恢复必须仍走隔离
    applier，正式写入器（即使再次传入）一次都不执行。"""
    db, nid = db_session, test_project_id
    _scene, binding = await _seed(db, nid)
    await db.commit()

    store = PostgresAttemptStore(db, nid)
    await store.register_run(
        "run-a01", mode="append", budget_total=3, execution_mode="shadow"
    )
    sampler = _FixpackSampler()
    counter: dict[str, int] = {}

    # 故障注入：影子领域操作完成后、回执持久化前丢失（第一次保存失败）。
    saves = {"n": 0}
    real_save = store.save_receipt

    async def crashing_save_receipt(receipt) -> None:
        saves["n"] += 1
        if saves["n"] == 1:
            raise RuntimeError("receipt persistence lost before commit")
        await real_save(receipt)

    monkeypatch.setattr(store, "save_receipt", crashing_save_receipt)

    with pytest.raises(RuntimeError, match="receipt persistence lost"):
        await run_scene_step(
            db,
            store,
            run_key="run-a01",
            scene_index=0,
            scene_text=SCENE_TEXT,
            source=binding,
            sampler=sampler,
            applier=_formal_applier(counter),
            identity_candidates=_KnownCandidates().lookup,
        )
    await db.rollback()

    # 冻结负载已盖章执行模式并完成编译（A01 协议内标记）。
    frozen = await store.load_pending_frozen("run-a01", 0)
    assert frozen is not None
    assert frozen.payload["execution_mode"] == "shadow"
    assert frozen.payload["stage"] == "compiled"

    # 恢复：调用方又传入正式写入器——统一写入策略解析必须换回隔离 applier。
    receipt = await recover_scene_step(
        db,
        store,
        run_key="run-a01",
        scene_index=0,
        applier=_formal_applier(counter),
        identity_candidates=_KnownCandidates().lookup,
    )
    assert counter.get("formal", 0) == 0
    assert receipt.committed_prefix.through_scene_index == 0
    assert sampler.calls == 1  # 恢复绝不重采样（T10）
    assert await _evolution_events(db, nid) == []  # 正式 Story 零写入
    assert await store.load_pending_frozen("run-a01", 0) is None


@pytest.mark.asyncio
async def test_commit_boundary_rejects_shadow_frozen_with_formal_applier(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """A01 纵深防御：提交边界本身拒绝影子负载经未标记的正式 applier 写入。"""
    db, nid = db_session, test_project_id
    await db.commit()
    store = PostgresAttemptStore(db, nid)
    await store.register_run(
        "run-a01b", mode="append", budget_total=3, execution_mode="shadow"
    )
    frozen = FrozenAttempt(
        novel_id=nid,
        run_id="run-a01b",
        attempt_id=uuid.uuid4().hex,
        owner_epoch=1,
        producer_version="evolution/test",
        source_manifest_hash="a" * 64,
        payload={"execution_mode": "shadow", "scene_index": 0},
    )
    await store.save_frozen(frozen)
    await db.commit()

    async def formal(db, frozen) -> ApplierResult:
        return ApplierResult(
            committed_prefix=CommittedPrefix(
                through_scene_index=0, through_source_revision=1
            )
        )

    async def verifier(db, frozen) -> None:
        return None

    with pytest.raises(CommitConflictError, match="shadow_write_rejected"):
        await apply_frozen(
            db,
            frozen=frozen,
            store=store,
            applier=formal,
            source_verifier=verifier,
            owner_epoch_provider=store.owner_epoch_provider("run-a01b"),
        )
    await db.rollback()


@pytest.mark.asyncio
async def test_legacy_unstamped_shadow_frozen_recovered_isolated(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """A01 兼容面：未盖章的既有冻结负载，恢复按 run 登记模式解析——
    影子 run 的正式写入器同样被替换。"""
    db, nid = db_session, test_project_id
    _scene, binding = await _seed(db, nid)
    await db.commit()

    store = PostgresAttemptStore(db, nid)
    await store.register_run(
        "run-a01c", mode="append", budget_total=3, execution_mode="shadow"
    )
    frozen = FrozenAttempt(
        novel_id=nid,
        run_id="run-a01c",
        attempt_id=uuid.uuid4().hex,
        owner_epoch=1,
        producer_version="evolution/test-legacy",
        source_manifest_hash="b" * 64,
        payload={
            "scene_index": 0,
            "source_binding": binding.model_dump(mode="json"),
            "compiled_observations": [
                {
                    "observation_id": "c" * 64,
                    "predicate": "p",
                    "modality": "event_observed",
                    "quote": "q",
                    "mentions": [],
                }
            ],
            "scene_events": [],
        },
    )
    await store.save_frozen(frozen)
    await db.commit()

    counter: dict[str, int] = {}
    receipt = await recover_scene_step(
        db,
        store,
        run_key="run-a01c",
        scene_index=0,
        applier=_formal_applier(counter),
    )
    assert counter.get("formal", 0) == 0
    assert receipt.committed_prefix.through_scene_index == 0
    assert await _evolution_events(db, nid) == []


# ---------------------------------------------------------------------------
# A07：采样阶段化持久化与费用待核对
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_final_sampler_failure_freezes_receipt_and_blocks_resample(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """A07：provider 最终抛错也固化失败回执；恢复进入待核对，不自动重采样。"""
    db, nid = db_session, test_project_id
    _scene, binding = await _seed(db, nid)
    await db.commit()

    store = PostgresAttemptStore(db, nid)
    await store.register_run("run-a07a", mode="append", budget_total=3)
    sampler = _FixpackSampler(
        final_error=RuntimeError("structured generation failed after repairs")
    )

    with pytest.raises(RuntimeError, match="structured generation failed"):
        await run_scene_step(
            db,
            store,
            run_key="run-a07a",
            scene_index=0,
            scene_text=SCENE_TEXT,
            source=binding,
            sampler=sampler,
            applier=_formal_applier({}),
        )
    await db.rollback()

    frozen = await store.load_pending_frozen("run-a07a", 0)
    assert frozen is not None
    assert frozen.payload["stage"] == "failed"
    assert frozen.payload["error"]
    # 失败回执（含真实用量）随冻结负载留档，可对账。
    assert frozen.payload["paid_call_receipt"]["outcome"] == "failed_final"
    assert frozen.payload["paid_call_receipt"]["usage"]["completion_tokens"] == 123

    with pytest.raises(SamplePendingReconciliationError) as excinfo:
        await recover_scene_step(
            db,
            store,
            run_key="run-a07a",
            scene_index=0,
            applier=_formal_applier({}),
        )
    assert excinfo.value.stage == "failed"
    assert sampler.calls == 1  # 待核对，绝不自动重采样


@pytest.mark.asyncio
async def test_crash_mid_request_enters_unknown_billing_state(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """A07：请求发出后进程崩溃（结果未取回）——恢复按 unknown_billing
    待核对，不当作未发生。"""
    db, nid = db_session, test_project_id
    _scene, binding = await _seed(db, nid)
    await db.commit()

    store = PostgresAttemptStore(db, nid)
    await store.register_run("run-a07b", mode="append", budget_total=3)
    sampler = _FixpackSampler(hard_crash=True)

    with pytest.raises(KeyboardInterrupt):
        await run_scene_step(
            db,
            store,
            run_key="run-a07b",
            scene_index=0,
            scene_text=SCENE_TEXT,
            source=binding,
            sampler=sampler,
            applier=_formal_applier({}),
        )
    await db.rollback()

    frozen = await store.load_pending_frozen("run-a07b", 0)
    assert frozen is not None
    assert frozen.payload["stage"] == "sampling"  # 请求前冻结在案
    with pytest.raises(SamplePendingReconciliationError) as excinfo:
        await recover_scene_step(
            db,
            store,
            run_key="run-a07b",
            scene_index=0,
            applier=_formal_applier({}),
        )
    assert excinfo.value.stage == "sampling"


@pytest.mark.asyncio
async def test_compile_crash_recovers_by_deterministic_recompilation(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A07：provider 结果耐久化后、观察编译崩溃——恢复确定性重编译并提交，
    provider 不被再次调用。"""
    db, nid = db_session, test_project_id
    _scene, binding = await _seed(db, nid)
    await db.commit()

    store = PostgresAttemptStore(db, nid)
    await store.register_run("run-a07c", mode="append", budget_total=3)
    sampler = _FixpackSampler()

    real_compile = pipeline_module._compile_sample_payload
    crashes = {"n": 0}

    async def flaky_compile(*args, **kwargs):
        crashes["n"] += 1
        if crashes["n"] == 1:
            raise RuntimeError("observation compilation crashed")
        return await real_compile(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "_compile_sample_payload", flaky_compile)

    counter: dict[str, int] = {}

    async def live_applier(db, frozen) -> ApplierResult:
        counter["applies"] = counter.get("applies", 0) + 1
        return ApplierResult(
            committed_prefix=CommittedPrefix(
                through_scene_index=0, through_source_revision=1
            )
        )

    with pytest.raises(RuntimeError, match="observation compilation crashed"):
        await run_scene_step(
            db,
            store,
            run_key="run-a07c",
            scene_index=0,
            scene_text=SCENE_TEXT,
            source=binding,
            sampler=sampler,
            applier=live_applier,
            identity_candidates=_KnownCandidates().lookup,
        )
    await db.rollback()

    frozen = await store.load_pending_frozen("run-a07c", 0)
    assert frozen is not None
    assert frozen.payload["stage"] == "sampled"  # provider 结果已耐久化
    assert "scene_text" in frozen.payload

    receipt = await recover_scene_step(
        db,
        store,
        run_key="run-a07c",
        scene_index=0,
        applier=live_applier,
        identity_candidates=_KnownCandidates().lookup,
    )
    assert receipt.committed_prefix.through_scene_index == 0
    assert sampler.calls == 1  # 免采样恢复
    assert crashes["n"] == 2  # 恢复重跑了确定性编译
    refrozen = await store.load_frozen("run-a07c", receipt.attempt_id)
    assert refrozen is not None
    assert refrozen.payload["stage"] == "compiled"
    assert refrozen.payload["identity_outcomes"] == {
        "reuse": 1,
        "new_candidate": 1,
    }
    # 编译后事件通过语义门（观察 0 为 event_observed 且被引用）。
    assert len(refrozen.payload["scene_events"]) == 1
    assert refrozen.payload["scene_events"][0]["source_observation_ids"]
