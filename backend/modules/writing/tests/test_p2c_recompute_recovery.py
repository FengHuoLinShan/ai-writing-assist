"""P2-C 整改回归：执行基线门禁、操作回执回放、待重算状态跨会话恢复。

来源：2026-10-08 审查报告 S1 / S2 / F7（零 LLM、合成数据）。

- S1 执行必须携带可重验的预览基线，缺失失败关闭（不是客户端可选项）。
- S2 ``operation_id`` 既约束请求摘要（同编号异摘要拒绝），也在完成后
  提供可回放的原回执（来源变化后仍能查回原结果）。
- F7 保存落库的失效提示在离开/刷新后仍可回读；重算覆盖该章后消解。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from modules.evidence.indexing.models import RagIndexState
from modules.writing.facade import create_draft_only
from modules.writing.models import WritingInvalidationNotice
from modules.writing.recompute import WritingRecomputeService
from modules.writing.schemas import (
    WritingRecomputeAdoptRequest,
    WritingRecomputeRequest,
    WritingRecomputeTarget,
)
from modules.writing.tests.test_p2c_recompute import (
    CH1_V1,
    CH1_V2,
    CH1_V3,
    _scene,
    _working_draft,
)

pytestmark = pytest.mark.asyncio


def _adopt(
    novel_id: str,
    operation_id: str,
    *,
    target_chapter: int = 1,
    digest: str = "0" * 64,
) -> WritingRecomputeAdoptRequest:
    return WritingRecomputeAdoptRequest(
        novel_id=novel_id,
        operation_id=operation_id,
        scope="reload_evidence",
        targets=[WritingRecomputeTarget(chapter_index=target_chapter)],
        confirmed=True,
        expected_source_digest=digest,
    )


async def test_adopt_requires_preview_baseline(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """省略来源基线 = 失败关闭：执行不得落在没有预览过的来源上。"""
    db, nid = db_session, test_project_id
    await _working_draft(db, nid, 1, 1, CH1_V1)
    service = WritingRecomputeService()
    preview = await service.preview(
        db,
        WritingRecomputeRequest(
            novel_id=nid,
            operation_id=f"op-{uuid.uuid4()}",
            scope="reload_evidence",
            targets=[WritingRecomputeTarget(chapter_index=1)],
        ),
    )
    request = _adopt(nid, preview.operation_id, digest=preview.source_digest)
    request.expected_source_digest = ""  # 契约层允许空串，服务层仍须拒绝
    with pytest.raises(ValidationError) as excinfo:
        await service.adopt(db, request)
    assert excinfo.value.code == "recompute_preview_baseline_required"


async def test_same_operation_id_with_other_targets_is_rejected(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """同一 operation_id 换目标：不是同一次重算，拒绝（防预览/执行错配）。"""
    db, nid = db_session, test_project_id
    await _working_draft(db, nid, 1, 1, CH1_V1)
    await _working_draft(db, nid, 2, 1, "第二章正文。")
    service = WritingRecomputeService()
    operation_id = f"op-{uuid.uuid4()}"
    preview = await service.preview(
        db,
        WritingRecomputeRequest(
            novel_id=nid,
            operation_id=operation_id,
            scope="reload_evidence",
            targets=[WritingRecomputeTarget(chapter_index=1)],
        ),
    )
    first = await service.adopt(
        db, _adopt(nid, operation_id, digest=preview.source_digest)
    )
    assert first.domain_write_performed is True

    with pytest.raises(ConflictError) as excinfo:
        await service.adopt(
            db, _adopt(nid, operation_id, target_chapter=2, digest=preview.source_digest)
        )
    assert excinfo.value.code == "recompute_operation_conflict"
    assert excinfo.value.context["operation_id"] == operation_id


async def test_completed_operation_replays_receipt_after_source_drift(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """已完成的操作在来源变化后重放：回原回执，不报 drift、不重复写入。"""
    db, nid = db_session, test_project_id
    await _working_draft(db, nid, 1, 1, CH1_V1)
    await create_draft_only(db, nid, 1, "第1章", CH1_V2)
    service = WritingRecomputeService()
    operation_id = f"op-{uuid.uuid4()}"
    preview = await service.preview(
        db,
        WritingRecomputeRequest(
            novel_id=nid,
            operation_id=operation_id,
            scope="reload_evidence",
            targets=[WritingRecomputeTarget(chapter_index=1)],
        ),
    )
    request = _adopt(nid, operation_id, digest=preview.source_digest)
    first = await service.adopt(db, request)

    # 预览后作者又改了一版（来源漂移）。
    await create_draft_only(db, nid, 1, "第1章", CH1_V3)

    replayed = await service.adopt(db, request)
    assert replayed.replayed is True
    assert replayed.operation_id == first.operation_id
    assert replayed.request_hash == first.request_hash
    assert replayed.results == first.results
    assert replayed.domain_write_performed is False, "回放不得产生新的域写入"


async def test_invalidation_notice_survives_reload_and_resolves_after_recompute(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """保存 → 待重算提示可回读（跨会话）→ 重算覆盖该章后消解。"""
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, scene_index=0, chapter_index=1)
    await _working_draft(db, nid, 1, 1, CH1_V1)
    from modules.story.continuity.services import MemoryService

    await MemoryService().record_scene_events(
        db,
        nid,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": dimension,
                "event_type": f"{dimension}_changed",
                "source": "author_confirmation",
                "snapshot_after": {"new_value": "人工确认"},
            }
            for dimension in ("timeline", "causality")
        ],
    )
    service = WritingRecomputeService()

    await create_draft_only(db, nid, 1, "第1章", CH1_V2)
    pending = await service.list_pending_notices(db, nid)
    assert pending, "保存触发的失效提示必须落库，离开再回来仍查得到"
    assert pending[0]["receipt_id"]

    operation_id = f"op-{uuid.uuid4()}"
    preview = await service.preview(
        db,
        WritingRecomputeRequest(
            novel_id=nid,
            operation_id=operation_id,
            scope="reload_evidence",
            targets=[WritingRecomputeTarget(chapter_index=1)],
        ),
    )
    outcome = await service.adopt(
        db,
        _adopt(nid, operation_id, digest=preview.source_digest).model_copy(
            update={"baseline_receipt_digest": pending[0]["receipt_id"]}
        ),
    )
    assert outcome.domain_write_performed is True
    assert await service.list_pending_notices(db, nid), "提交索引任务不等于完成"
    row = (
        await db.execute(
            select(RagIndexState).where(
                RagIndexState.novel_id == uuid.UUID(nid),
                RagIndexState.content_mode == "working",
            )
        )
    ).scalar_one()
    row.status = "failed"
    await db.flush()
    assert await service.list_pending_notices(db, nid), "索引失败保留待处理提示"
    row.status = "succeeded"
    row.indexed_hash = row.requested_hash
    row.indexed_source_id = row.requested_source_id
    await db.flush()
    assert await service.list_pending_notices(db, nid), "仅重读不能清除未重建的场景"
    rebuild = WritingRecomputeRequest(
        novel_id=nid,
        operation_id=f"op-{uuid.uuid4()}",
        scope="rebuild_derived_state",
        targets=[WritingRecomputeTarget(chapter_index=1)],
        baseline_receipt_digest=pending[0]["receipt_id"],
    )
    rebuild_preview = await service.preview(db, rebuild)
    await service.adopt(
        db,
        WritingRecomputeAdoptRequest(
            **rebuild.model_dump(),
            confirmed=True,
            expected_source_digest=rebuild_preview.source_digest,
        ),
    )
    assert await service.list_pending_notices(db, nid) == [], "两个范围实际完成后提示消解"
    receipts = await service.list_receipts(db, nid)
    assert operation_id in [item["operation_id"] for item in receipts]
    assert any(item["scope"] == "reload_evidence" for item in receipts)


async def test_completed_notice_is_resolved_and_not_resurrected_by_later_edits(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """重算覆盖后提示在库中消解：status/resolved_at 落库，后续改稿不复活旧提示。

    回归：消解此前只在读取时临时过滤，提示行永远停在 open——每次打开
    章节都重扫全部历史提示，且已完成提示在新编辑改变指纹后会被误判回
    待处理。
    """
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, scene_index=0, chapter_index=1)
    await _working_draft(db, nid, 1, 1, CH1_V1)
    from modules.story.continuity.services import MemoryService

    await MemoryService().record_scene_events(
        db,
        nid,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": dimension,
                "event_type": f"{dimension}_changed",
                "source": "author_confirmation",
                "snapshot_after": {"new_value": "人工确认"},
            }
            for dimension in ("timeline", "causality")
        ],
    )
    service = WritingRecomputeService()
    await create_draft_only(db, nid, 1, "第1章", CH1_V2)
    pending = await service.list_pending_notices(db, nid)
    receipt_id = pending[0]["receipt_id"]

    operation_id = f"op-{uuid.uuid4()}"
    preview = await service.preview(
        db,
        WritingRecomputeRequest(
            novel_id=nid,
            operation_id=operation_id,
            scope="reload_evidence",
            targets=[WritingRecomputeTarget(chapter_index=1)],
        ),
    )
    await service.adopt(
        db,
        _adopt(nid, operation_id, digest=preview.source_digest).model_copy(
            update={"baseline_receipt_digest": receipt_id}
        ),
    )
    row = (
        await db.execute(
            select(RagIndexState).where(
                RagIndexState.novel_id == uuid.UUID(nid),
                RagIndexState.content_mode == "working",
            )
        )
    ).scalar_one()
    row.status = "succeeded"
    row.indexed_hash = row.requested_hash
    row.indexed_source_id = row.requested_source_id
    await db.flush()
    rebuild = WritingRecomputeRequest(
        novel_id=nid,
        operation_id=f"op-{uuid.uuid4()}",
        scope="rebuild_derived_state",
        targets=[WritingRecomputeTarget(chapter_index=1)],
        baseline_receipt_digest=receipt_id,
    )
    rebuild_preview = await service.preview(db, rebuild)
    await service.adopt(
        db,
        WritingRecomputeAdoptRequest(
            **rebuild.model_dump(),
            confirmed=True,
            expected_source_digest=rebuild_preview.source_digest,
        ),
    )

    stored = (
        await db.execute(
            select(WritingInvalidationNotice).where(
                WritingInvalidationNotice.novel_id == uuid.UUID(nid),
                WritingInvalidationNotice.receipt_id == receipt_id,
            )
        )
    ).scalar_one()
    assert stored.status == "resolved", "完成判定通过后行必须消解，不再进入待办扫描"
    assert stored.resolved_at is not None

    await create_draft_only(db, nid, 1, "第1章", CH1_V3)
    statuses = {
        item.receipt_id: item.status
        for item in (
            await db.execute(
                select(WritingInvalidationNotice).where(
                    WritingInvalidationNotice.novel_id == uuid.UUID(nid)
                )
            )
        ).scalars()
    }
    assert statuses[receipt_id] == "resolved", "后来的改稿不得把已消解的旧提示改回待处理"
    pending_after = await service.list_pending_notices(db, nid)
    assert receipt_id not in {item["receipt_id"] for item in pending_after}
    assert len(pending_after) == 1, "新改稿产生的新提示仍然待处理"


async def test_same_length_edits_have_distinct_pending_receipts(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    await _working_draft(db, nid, 1, 1, "甲持钥匙。")
    await create_draft_only(db, nid, 1, "第一章", "乙持钥匙。")
    first = await WritingRecomputeService().list_pending_notices(db, nid)
    await create_draft_only(db, nid, 1, "第一章", "丙持钥匙。")
    notices = await WritingRecomputeService().list_pending_notices(db, nid)
    assert len(notices) == 2
    assert len({item["receipt_id"] for item in notices}) == 2
    assert first[0]["receipt_id"] in {item["receipt_id"] for item in notices}


async def test_rebuild_preview_binds_inherited_chapters(db_session, test_project_id):
    db, nid = db_session, test_project_id
    await _scene(db, nid, scene_index=0, chapter_index=1)
    await _scene(db, nid, scene_index=1, chapter_index=2)
    await _working_draft(db, nid, 1, 1, CH1_V1)
    await _working_draft(db, nid, 2, 1, "第二章。")
    service = WritingRecomputeService()
    request = WritingRecomputeRequest(
        novel_id=nid,
        operation_id=f"op-{uuid.uuid4()}",
        scope="rebuild_derived_state",
        targets=[WritingRecomputeTarget(scene_index=1)],
    )
    preview = await service.preview(db, request)
    assert set(preview.source_state["chapters"]) == {"1", "2"}
    await create_draft_only(db, nid, 1, "第一章", CH1_V2)
    with pytest.raises(ConflictError) as exc:
        await service.adopt(
            db,
            WritingRecomputeAdoptRequest(
                **request.model_dump(),
                confirmed=True,
                expected_source_digest=preview.source_digest,
            ),
        )
    assert exc.value.code == "recompute_source_drift"


async def test_notice_checks_canonical_index_success(monkeypatch):
    import modules.writing.recompute as recompute

    async def fingerprint(db, novel_id, chapter_index, *, content_mode):
        return {
            "status": "succeeded" if content_mode == "working" else canonical_status,
            "indexed_hash": "hash",
            "indexed_source_id": "draft",
        }

    canonical_status = "failed"
    monkeypatch.setattr(recompute, "read_chapter_index_fingerprint", fingerprint)
    detail = {"requested_hash": "hash", "requested_source_id": "draft"}
    notice = {
        "chapter_index": 1,
        "affected": [],
        "invalidated": [
            {"consumer": "evidence_chapter_index"},
            {"consumer": "canonical_chapter_index", "detail": detail},
        ],
        "_recompute_progress": {"reload_evidence": {"chapter:1": detail}},
    }
    service = WritingRecomputeService()
    assert await service._notice_completed(None, "project", notice) is False
    canonical_status = "succeeded"
    assert await service._notice_completed(None, "project", notice) is True


async def test_notice_rechecks_scene_after_another_chapter_edit(
    db_session, test_project_id
):
    from modules.story.continuity.scene_projection import SceneMemoryProjectionService
    from modules.story.continuity.services import MemoryService

    db, nid = db_session, test_project_id
    first = await _scene(db, nid, scene_index=0, chapter_index=1)
    second = await _scene(db, nid, scene_index=1, chapter_index=2)
    await _working_draft(db, nid, 1, 1, CH1_V1)
    await _working_draft(db, nid, 2, 1, "第二章。")
    await MemoryService().record_scene_events(
        db,
        nid,
        scene_id=str(first.id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": dim,
                "event_type": f"{dim}_changed",
                "source": "author_confirmation",
                "snapshot_after": {"new_value": "确认"},
            }
            for dim in ("timeline", "causality")
        ],
    )
    await SceneMemoryProjectionService().ensure_scene(db, nid, str(second.id))
    notice = {
        "chapter_index": 1,
        "affected": [{"scene_index": index} for index in (0, 1)],
        "_recompute_progress": {
            "rebuild_derived_state": {
                str(scene.id): {
                    "scene_index": scene.scene_index,
                    "scene_id": str(scene.id),
                    "coverage_status": "ready",
                    "current_checkpoints": 6,
                }
                for scene in (first, second)
            }
        },
    }
    service = WritingRecomputeService()
    assert await service._notice_completed(db, nid, notice) is True
    await create_draft_only(db, nid, 2, "第二章", "第二章已修改。")
    assert await service._notice_completed(db, nid, notice) is False


async def test_receipt_failure_rolls_back_domain_actions(
    db_session, test_project_id, monkeypatch
):
    from modules.writing.tests.test_p2c_recompute import _task_count

    db, nid = db_session, test_project_id
    await _working_draft(db, nid, 1, 1, CH1_V1)
    service = WritingRecomputeService()
    request = WritingRecomputeRequest(
        novel_id=nid,
        operation_id=f"op-{uuid.uuid4()}",
        scope="reload_evidence",
        targets=[WritingRecomputeTarget(chapter_index=1)],
    )
    preview = await service.preview(db, request)
    baseline_count = await _task_count(db, nid)

    async def fail_receipt(*args, **kwargs):
        raise RuntimeError("receipt persistence failure")

    monkeypatch.setattr(service._operations, "save_operation", fail_receipt)
    with pytest.raises(RuntimeError, match="receipt persistence failure"):
        async with db.begin_nested():
            await service.adopt(
                db,
                WritingRecomputeAdoptRequest(
                    **request.model_dump(),
                    confirmed=True,
                    expected_source_digest=preview.source_digest,
                ),
            )
    assert await _task_count(db, nid) == baseline_count
    assert await service.list_receipts(db, nid) == []


async def test_notice_limit_is_applied_after_completion_filter(
    db_session, test_project_id, monkeypatch
):
    from modules.writing.repositories import WritingRecomputeRepository

    db, nid = db_session, test_project_id
    for receipt, complete in (("old-pending", False), ("new-complete", True)):
        await WritingRecomputeRepository.save_notice(
            db,
            novel_id=uuid.UUID(nid),
            receipt_id=receipt,
            chapter_index=1,
            notice={"receipt_id": receipt, "complete": complete},
        )
    service = WritingRecomputeService()

    async def completion(db, novel_id, notice):
        return notice["complete"]

    monkeypatch.setattr(service, "_notice_completed", completion)
    assert [
        item["receipt_id"]
        for item in await service.list_pending_notices(db, nid, limit=1)
    ] == ["old-pending"]
