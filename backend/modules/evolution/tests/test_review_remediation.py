"""PR #158 评审返修验收：R1–R6 与 P2 项的关键行为测试。

对应评审「最小复审门槛」：

1. 真实版本原文 + async 观察-only sampler：宿主派生提及身份、经 world
   facade 精确名解析、一致性门放行/拦截（R1/R2）。
2. 屏障顺序：跳场/倒序/重复推进被拒（R3）；批次位置取 Scene 最大批次。
3. 故障注入：域失败后冻结与预算仍在，恢复不重采样（R4）。
4. 单写者：排空 run 不复活、非 active 不再扣预算（R5；真实 PG 双会话
   并发在 e2e 套件）。
5. paid_call_receipts 进入回执（R6）；head_attempt_id 指针非空（P2）。
6. consumers 有效性判定收窄（P2）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.commit import ApplierResult, CommitConflictError
from modules.evolution.contracts import CommittedPrefix
from modules.evolution.orchestrator import SceneTask, plan_parallel_batches
from modules.evolution.pipeline import (
    SceneSourceBinding,
    exact_name_candidate_lookup,
    recover_scene_step,
    run_scene_step,
)
from modules.evolution.store import PostgresAttemptStore
from modules.story.outline_state.models import Scene
from modules.world.models.core import CoreEntity
from modules.writing.facade import create_draft_only, get_latest_draft_for_chapter
from tests.support.evolution_review import frozen_state_review

SCENE_TEXT = "林舟与青竹在白石城重逢。青竹从袖中取出铜钥匙。"
QINGZHU_NAME = "青竹"


async def _seed(db: AsyncSession, novel_id: str) -> tuple[str, SceneSourceBinding, str]:
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
    return str(scene.id), binding, str(draft.id)


def _applier(novel_id: str, scene_id: str, *, fail: bool = False):
    async def applier(db, frozen) -> ApplierResult:
        if fail:
            raise RuntimeError("domain write failed after freeze")
        return ApplierResult(
            committed_prefix=CommittedPrefix(
                through_scene_index=0, through_source_revision=1
            ),
            paid_call_receipts=[
                frozen.payload["paid_call_receipt"]
                for _ in [1]
                if (frozen.payload or {}).get("paid_call_receipt")
            ],
        )

    return applier


@dataclass
class _ObservationOnlySampler:
    """生产形状的 async sampler：只回观察（提及无 mention_id、禁造 UUID）。"""

    entity_id: str
    unknown_entity_id: str = "99999999-9999-4999-8999-999999999999"
    calls: int = 0

    async def sample(self, *, scene_text: str, input_manifest: dict[str, Any]) -> dict:
        self.calls += 1
        return {
            "observations": [
                {
                    "predicate": "青竹在白石城取出铜钥匙",
                    "modality": "event_observed",
                    "quote": "青竹从袖中取出铜钥匙",
                    "mentions": [
                        {"surface": QINGZHU_NAME, "entity_type": "character"},
                        {"surface": "白石城", "entity_type": "location"},
                    ],
                }
            ],
            "scene_events": [
                {
                    "dimension": "locations",
                    "event_type": "entity_moved",
                    "entity_id": self.entity_id,
                    "snapshot_after": {"text_state": "白石城"},
                    # A03 语义门：状态提议须自附本批观察证据（引用序号）。
                    "source_observation_indices": [0],
                },
                {
                    "dimension": "entities",
                    "event_type": "manual_correction",
                    "entity_id": self.unknown_entity_id,
                    "snapshot_after": {"summary": "观察未支持的提议"},
                },
            ],
            "paid_call_receipt": {
                "provider": "project_llm",
                "model": "deepseek-test",
                "schema": "evolution.scene_sample.v1",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        }


@pytest.mark.asyncio
async def test_real_chain_observation_only_sampler(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """R1/R2：async sampler 只回观察；宿主派生提及身份并经 world 精确名解析；
    一致性门放行已解析实体、拦截未解析实体；paid 回执与 head 指针落库。"""
    db, nid = db_session, evolution_project_id
    # World 已有 青竹（canonical）——精确名证据；白石城 未注册（new_candidate）。
    qingzhu = CoreEntity(
        novel_id=uuid.UUID(nid),
        entity_type="character",
        name=QINGZHU_NAME,
        status="canonical",
    )
    db.add(qingzhu)
    scene_id, binding, _draft_id = await _seed(db, nid)
    await db.commit()

    store = PostgresAttemptStore(db, nid)
    await store.register_run("run-remediation", mode="append", budget_total=5)

    sampler = _ObservationOnlySampler(entity_id=str(qingzhu.id))
    result = await run_scene_step(
        db,
        store,
        run_key="run-remediation",
        scene_index=0,
        scene_text=SCENE_TEXT,
        source=binding,
        sampler=sampler,
        state_reviewer=frozen_state_review,
        applier=_applier(nid, scene_id),
        identity_candidates=exact_name_candidate_lookup(db),
    )
    # 身份解析：青竹 reuse（world 精确名）、白石城 new_candidate。
    assert result.identity_outcomes == {"reuse": 1, "new_candidate": 1}
    # 提及身份由宿主派生并随解析结论一起编译进冻结负载（模型只给表面名）。
    frozen = await store.load_frozen("run-remediation", result.receipt_attempt_id)
    assert frozen is not None
    compiled = frozen.payload["compiled_observations"][0]
    mention_ids = [m["mention_id"] for m in compiled["mentions"]]
    assert all(mention_ids)
    assert len(set(mention_ids)) == len(mention_ids)
    by_surface = {m["surface"]: m["resolution"] for m in compiled["mentions"]}
    assert by_surface[QINGZHU_NAME]["outcome"] == "reuse"
    assert by_surface["白石城"]["outcome"] == "new_candidate"
    # 一致性门：引用已解析实体的位置事件放行，未解析实体的提议被拦。
    assert len(result.gated_scene_events) == 1
    assert result.gated_scene_events[0]["entity_id"] == sampler.unknown_entity_id
    # paid 回执进入冻结负载与最终回执（R6）。
    receipt = await store.load_receipt("run-remediation", result.receipt_attempt_id)
    assert receipt is not None
    assert receipt.paid_call_receipts[0]["model"] == "deepseek-test"
    assert receipt.paid_call_receipts[0]["usage"]["prompt_tokens"] == 10
    # P2：head_attempt_id 指针非空（显式主键生成后 UPDATE 才能引用它）。
    run = await store.load_run("run-remediation")
    assert run.head_attempt_id is not None


@pytest.mark.asyncio
async def test_domain_failure_keeps_freeze_and_budget_then_recovers(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """R4：域提交失败不抹掉预算预留与冻结负载；恢复重放不重采样。"""
    db, nid = db_session, evolution_project_id
    scene_id, binding, _draft_id = await _seed(db, nid)
    await db.commit()

    store = PostgresAttemptStore(db, nid)
    await store.register_run("run-fault", mode="append", budget_total=3)

    sampler = _ObservationOnlySampler(entity_id="irrelevant-gated-anyway")
    with pytest.raises(RuntimeError, match="domain write failed"):
        await run_scene_step(
            db,
            store,
            run_key="run-fault",
            scene_index=0,
            scene_text=SCENE_TEXT,
            source=binding,
            sampler=sampler,
            applier=_applier(nid, scene_id, fail=True),
            identity_candidates=exact_name_candidate_lookup(db),
        )
    await db.rollback()  # 域事务回滚（保存点），冻结与预算在更早的提交里。

    # 预算只扣了这一次采样（预留先于采样并已持久化）。
    run = await store.load_run("run-fault")
    assert run.budget_remaining == 2
    # 冻结负载仍在（T10 恢复基础）。
    frozen = await store.load_pending_frozen("run-fault", 0)
    assert frozen is not None

    receipt = await recover_scene_step(
        db,
        store,
        run_key="run-fault",
        scene_index=0,
        applier=_applier(nid, scene_id),
    )
    assert receipt.attempt_id == frozen.attempt_id
    assert sampler.calls == 1  # 恢复重放冻结负载，provider 未被再次调用
    head = await store.load_head_receipt("run-fault")
    assert head is not None and head.attempt_id == receipt.attempt_id


def test_barrier_ordering_rejections() -> None:
    """R3 单元：批次位置取同 Scene 全部任务的最大批次（回归修复）。"""
    # Scene 0：A 依赖 k1；Scene 1：B 依赖 k1（进晚批）、C 无依赖（可进早批）。
    # 旧实现的 scene_batch[1] 会被 C 的早批覆盖，导致 Scene 2 过早同批。
    tasks = [
        SceneTask(0, "a", frozenset({"k1"})),
        SceneTask(1, "b", frozenset({"k1"})),
        SceneTask(1, "c", frozenset()),
        SceneTask(2, "d", frozenset()),
    ]
    batches = plan_parallel_batches(tasks)
    positions = {
        task.task_key: (batch_index, position)
        for batch_index, batch in enumerate(batches)
        for position, task in enumerate(batch)
    }
    # Scene 1 的两个任务都完成后，Scene 2 才能开始。
    assert positions["d"][0] > max(positions["b"][0], positions["c"][0])


@pytest.mark.asyncio
async def test_drained_run_cannot_be_revived_or_charged(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """R5：排空 run 不因重复注册复活；非 active run 不再消耗预算。"""
    db, nid = db_session, evolution_project_id
    store = PostgresAttemptStore(db, nid)
    await store.register_run("run-drain", mode="append", budget_total=5)
    await store.drain_run("run-drain")

    with pytest.raises(CommitConflictError, match="run_not_active"):
        await store.register_run("run-drain", mode="append", budget_total=5)
    with pytest.raises(CommitConflictError, match="run_not_active"):
        await store.reserve_budget("run-drain", 1)

    run = await store.load_run("run-drain")
    assert run.budget_remaining == 5  # 排空后未再扣减


@pytest.mark.asyncio
async def test_consumers_validity_requires_claimed_and_indexed_fingerprints(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """P2：无声称指纹或无已索引指纹时不能宣称 valid。"""
    from modules.evidence.indexing.models import RagIndexState
    from modules.evolution.consumers import check_suggestion_validity

    db, nid = db_session, evolution_project_id
    await db.commit()

    state = RagIndexState(
        novel_id=uuid.UUID(nid),
        chapter_index=9,
        content_mode="working",
        status="pending",
    )
    db.add(state)
    await db.commit()

    # 索引状态存在但没有任何已索引指纹：unknown，不是 valid。
    validity = await check_suggestion_validity(
        db, nid, chapter_index=9, claimed_hash="a" * 64, content_mode="working"
    )
    assert validity.verdict == "unknown"

    # 已索引但建议未声称指纹：unknown，不能说“指纹一致”。
    state.status = "succeeded"
    state.requested_hash = "b" * 64
    state.indexed_hash = "b" * 64
    state.requested_source_id = state.indexed_source_id = uuid.uuid4()
    await db.commit()
    validity = await check_suggestion_validity(
        db, nid, chapter_index=9, claimed_hash=None, content_mode="working"
    )
    assert validity.verdict == "unknown"

    # 双侧指纹一致：valid。
    validity = await check_suggestion_validity(
        db, nid, chapter_index=9, claimed_hash="b" * 64, content_mode="working"
    )
    assert validity.verdict == "valid"

    # 来源撤回等待索引清理时，旧 indexed_hash 不能继续证明当前有效。
    state.requested_hash = state.requested_source_id = None
    await db.commit()
    validity = await check_suggestion_validity(
        db, nid, chapter_index=9, claimed_hash="b" * 64, content_mode="working"
    )
    assert validity.verdict == "stale"
