"""E07 迁移切换测试：影子隔离、单写者/排空、在途兼容、任务挂接与适配层。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.commit import (
    ApplierResult,
    CommitConflictError,
    StaleOwnerError,
    apply_frozen,
)
from modules.evolution.compat import classify_legacy_checkpoint
from modules.evolution.contracts import CommittedPrefix
from modules.evolution.legacy_adapter import (
    DEPRECATION_NOTICE,
    LegacyDeepImportRequest,
    adapt_deep_import_start,
)
from modules.evolution.sampler import (
    SamplerNotWiredError,
    register_scene_sampler,
)
from modules.evolution.store import PostgresAttemptStore
from modules.story.continuity.models import MemoryEvent
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene

RUN = "run-e07"


@dataclass
class _Sampler:
    def sample(self, *, scene_text: str, input_manifest: dict[str, Any]) -> dict:
        return {
            "scene_events": [
                {
                    "dimension": "entities",
                    "event_type": "manual_correction",
                    "snapshot_after": {"summary": scene_text[:24]},
                }
            ],
            "observations": [],
        }


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


def _live_applier(novel_id: str, scene_id: str):
    async def applier(db, frozen) -> ApplierResult:
        events = [
            {**event, "source": "evolution"} for event in frozen.payload["scene_events"]
        ]
        await MemoryService().record_scene_events(
            db,
            novel_id,
            scene_id=scene_id,
            scene_index=0,
            chapter_index=1,
            events=events,
            producer_family="evolution",
        )
        return ApplierResult(
            committed_prefix=CommittedPrefix(
                through_scene_index=0, through_source_revision=1
            )
        )

    return applier


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


@pytest.mark.asyncio
async def test_shadow_run_writes_no_production_facts(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """E07.b：影子运行读同一来源，产物隔离——不写正式 World/Story。"""
    from modules.evolution.pipeline import run_scene_step

    db, nid = db_session, test_project_id
    scene = await _scene(db, nid)
    await db.commit()
    store = PostgresAttemptStore(db, nid)
    await store.register_run(RUN, mode="append", budget_total=5)

    # 影子 run：即使传入会写正式表的 live applier 也被强制隔离。
    await store.register_run(
        "run-shadow", mode="append", budget_total=5, execution_mode="shadow"
    )
    result = await run_scene_step(
        db,
        store,
        run_key="run-shadow",
        scene_index=0,
        scene_text="林舟与青竹在白石城重逢。",
        sampler=_Sampler(),
        applier=_live_applier(nid, str(scene.id)),
    )
    assert result.receipt_attempt_id
    assert await _evolution_events(db, nid) == []  # 未产生第二套有效事实
    head = await store.load_head_receipt("run-shadow")
    assert head is not None  # 影子回执留在 evolution 自己的表里供对比

    # live run 照常写入。
    await run_scene_step(
        db,
        store,
        run_key=RUN,
        scene_index=0,
        scene_text="林舟与青竹在白石城重逢。",
        sampler=_Sampler(),
        applier=_live_applier(nid, str(scene.id)),
    )
    assert len(await _evolution_events(db, nid)) == 1


@pytest.mark.asyncio
async def test_single_live_writer_and_drain_fences_old_owner(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """E07.c：同项目单 live 写入者；切换排空后旧 epoch 无提交权。"""
    db, nid = db_session, test_project_id
    store = PostgresAttemptStore(db, nid)
    await store.register_run(RUN, mode="append", budget_total=5)

    with pytest.raises(CommitConflictError, match="single_writer"):
        await store.register_run("run-second", mode="append", budget_total=5)

    drained = await store.switch_project_engine(RUN, to_engine="evolution")
    assert drained.status == "drained"
    assert drained.owner_epoch == 2

    # 排空后旧 epoch 的冻结尝试在持久化边界被拒（E06 fencing 复验）。
    from modules.evolution.commit import FrozenAttempt

    stale = FrozenAttempt(
        novel_id=nid,
        run_id=RUN,
        attempt_id=uuid.uuid4().hex,
        owner_epoch=1,
        producer_version="evolution/test",
        source_manifest_hash="a" * 64,
        payload={},
    )
    await store.save_frozen(stale)

    async def applier(db, frozen):
        return ApplierResult(
            committed_prefix=CommittedPrefix(
                through_scene_index=0, through_source_revision=1
            )
        )

    async def verifier(db, frozen):
        return None

    with pytest.raises(StaleOwnerError):
        await apply_frozen(
            db,
            frozen=stale,
            store=store,
            applier=applier,
            source_verifier=verifier,
            owner_epoch_provider=store.owner_epoch_provider(RUN),
        )

    # 排空释放写入位：新 live run 可注册。
    await store.register_run("run-second", mode="append", budget_total=5)


def test_legacy_checkpoint_classification() -> None:
    """E07.d：冻结契约分类——兼容续接 / 保留费用从可验证批次继续。"""
    compatible = classify_legacy_checkpoint(
        {
            "contract_version": "deep_import.v2",
            "workflow_id": "wf-1",
            "phase": "extract",
            "source_chapter_index": 3,
            "sources": [{"chapter": 3}],
        }
    )
    assert compatible.verdict == "continue_compatible"
    assert "续接" in compatible.resume_hint

    unknown = classify_legacy_checkpoint(
        {"contract_version": "deep_import.v0", "workflow_id": "wf-2"}
    )
    assert unknown.verdict == "incompatible"
    assert unknown.preserve_costs is True
    assert "可验证批次" in unknown.resume_hint
    assert set(unknown.missing_fields) == {"phase", "source_chapter_index", "sources"}

    assert classify_legacy_checkpoint(None).verdict == "incompatible"


@pytest.mark.asyncio
async def test_task_handler_runs_real_path_with_wired_sampler(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """E07.e：evolution_scene_step 走真实路径；采样器未接线 fail-closed。"""
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid)
    await db.commit()

    @dataclass
    class _Task:
        meta: dict

    request = {
        "novel_id": nid,
        "run_key": "run-task",
        "scene_index": 0,
        "scene_text": "青竹把铜钥匙收进包袱。",
        "scene_id": str(scene.id),
        "chapter_index": 1,
        "budget_total": 5,
        "sampler_provider": "test-echo",
    }

    # 未接线：拒绝伪造观察。
    with pytest.raises(SamplerNotWiredError):
        await __import__(
            "modules.evolution.tasks", fromlist=["handle_evolution_scene_step"]
        ).handle_evolution_scene_step(db, _Task(meta=request))

    register_scene_sampler("test-echo", lambda db, novel_id: _Sampler())
    result = await __import__(
        "modules.evolution.tasks", fromlist=["handle_evolution_scene_step"]
    ).handle_evolution_scene_step(db, _Task(meta=request))
    assert result["attempt_id"]
    assert result["committed_prefix"]["through_scene_index"] == 0
    assert len(await _evolution_events(db, nid)) == 1


def test_deep_import_adapter_maps_and_deprecates() -> None:
    adapted = adapt_deep_import_start(
        LegacyDeepImportRequest(
            novel_id="0e0e0e0e-0e0e-4e0e-8e0e-0e0e0e0e0e0e",
            import_mode="append",
            chapter_indices=[1, 2, 3],
            requested_budget=2,
        )
    )
    assert adapted.deprecated is True
    assert adapted.deprecation_notice == DEPRECATION_NOTICE
    assert adapted.evolution_mode == "append"
    assert adapted.budget_total == 3  # max(请求预算, 章节数)
    assert [step["scene_index"] for step in adapted.scene_steps] == [1, 2, 3]
    assert all(
        step["task_type"] == "evolution_scene_step" for step in adapted.scene_steps
    )
