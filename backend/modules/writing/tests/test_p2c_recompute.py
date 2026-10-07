"""P2-C C3：writing 侧回执透传与重算编排测试（零 LLM、合成数据）。

覆盖四条链路：

1. **回执透传**：保存触发失效后，``repositories._changed`` 接住回执并经
   组合根注册的 DI 缝 ``EVOLUTION_INVALIDATION_RECEIPT_VIEW`` 投影为公共
   视图，随 ``WritingDraftContract`` / ``WritingDraftResponse.invalidation``
   透传（真实视图函数直连，无 DI 替身）。
2. **镜像契约对拍**：writing 侧三分类覆盖/成本表/请求内容指纹与 evolution
   消费登记契约（C1）逐位相等，防漂移（沿 P2-B 镜像先例；测试可跨模块
   导入实现）。
3. **重算预览零写入 + 取消零副作用**：预览纯读组装；预览后不采用 =
   取消，正史零写入（索引状态/任务/checkpoint/稿件全部不变）。
4. **执行**：确认门、regenerate_prose 显式 unsupported（不新增 LLM）、
   reload/rebuild 幂等重放不产生重复域写入、来源漂移 409 保留当前稿。
"""

from __future__ import annotations

import hashlib
import uuid
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from infrastructure.tasks.models import AsyncTask
from modules.evidence.indexing.models import RagIndexState
from modules.evolution.consumption import RECOMPUTE_SCOPE_COVERS as C1_COVERS
from modules.evolution.consumption import RECOMPUTE_SCOPE_EFFECTS as C1_EFFECTS
from modules.evolution.consumption import RecomputeRequest as C1RecomputeRequest
from modules.evolution.consumption import RecomputeTargetRef as C1TargetRef
from modules.evolution.consumption import recompute_request_hash as c1_request_hash
from modules.story.continuity.models import MemorySceneCheckpoint
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene
from modules.writing.facade import create_draft_only
from modules.writing.models import WritingDraft
from modules.writing.recompute import (
    RECOMPUTE_SCOPE_COVERS,
    RECOMPUTE_SCOPE_EFFECTS,
    WritingRecomputeService,
    recompute_request_hash,
)
from modules.writing.schemas import (
    WritingRecomputeAdoptRequest,
    WritingRecomputeRequest,
    WritingRecomputeTarget,
)

INVALIDATION_VIEW_KEYS = {"affected", "unknown_scope", "receipt_id"}

CH1_V1 = "甲铸成铜钥匙，亲自收着。"
CH1_V2 = "甲铸成铜钥匙，交给乙保管。"
CH1_V3 = "甲铸成铜钥匙，交给丙保管。"


# ============================================================
# 合成数据构造
# ============================================================


async def _scene(
    db: AsyncSession, novel_id: str, scene_index: int, chapter_index: int
) -> Scene:
    item = Scene(
        novel_id=UUID(novel_id),
        scene_index=scene_index,
        title=f"Scene {scene_index}",
        chapter_ids=[chapter_index],
        scene_chunks=[{"chapter_index": chapter_index}],
        status="draft",
    )
    db.add(item)
    await db.flush()
    return item


async def _working_draft(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    version_number: int,
    content: str,
) -> WritingDraft:
    """直接落 working 稿行（绕过保存失效钩子，沿 C0 夹具惯例）。"""
    draft = WritingDraft(
        id=uuid.uuid4(),
        novel_id=UUID(novel_id),
        chapter_index=chapter_index,
        title=f"第{chapter_index}章",
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        version_number=version_number,
        status="draft",
    )
    db.add(draft)
    await db.flush()
    return draft


async def _checkpoint_rows(
    db: AsyncSession, novel_id: str, scene_id: uuid.UUID
) -> list[MemorySceneCheckpoint]:
    return list(
        (
            await db.execute(
                select(MemorySceneCheckpoint).where(
                    MemorySceneCheckpoint.novel_id == UUID(novel_id),
                    MemorySceneCheckpoint.scene_id == scene_id,
                )
            )
        )
        .scalars()
        .all()
    )


async def _rag_rows(db: AsyncSession, novel_id: str) -> list[RagIndexState]:
    return list(
        (
            await db.execute(
                select(RagIndexState).where(
                    RagIndexState.novel_id == UUID(novel_id),
                    RagIndexState.content_mode == "working",
                )
            )
        )
        .scalars()
        .all()
    )


async def _task_count(db: AsyncSession, novel_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(AsyncTask)
            .where(AsyncTask.novel_id == UUID(novel_id))
        )
    )


def _reload_request(novel_id: str) -> WritingRecomputeRequest:
    return WritingRecomputeRequest(
        novel_id=novel_id,
        operation_id=f"op-{uuid.uuid4()}",
        scope="reload_evidence",
        targets=[WritingRecomputeTarget(chapter_index=1)],
    )


# ============================================================
# 镜像契约对拍（防漂移）
# ============================================================


def test_recompute_mirror_matches_evolution_contract() -> None:
    """writing 侧三分类枚举/覆盖/成本表与 C1 契约逐位相等。"""
    assert dict(RECOMPUTE_SCOPE_COVERS) == dict(C1_COVERS)
    assert dict(RECOMPUTE_SCOPE_EFFECTS) == dict(C1_EFFECTS)


def test_recompute_request_hash_matches_evolution_contract() -> None:
    """请求内容指纹口径一致：同一逻辑请求跨层同 operation 标识。"""
    c1_request = C1RecomputeRequest(
        novel_id="n",
        operation_id="op-1",
        scope="rebuild_derived_state",
        targets=[C1TargetRef(scene_index=1, dimension="entities")],
        baseline_receipt_digest="digest-1",
    )
    writing_request = WritingRecomputeRequest(
        novel_id="n",
        operation_id="op-1",
        scope="rebuild_derived_state",
        targets=[WritingRecomputeTarget(scene_index=1, dimension="entities")],
        baseline_receipt_digest="digest-1",
    )
    assert recompute_request_hash(writing_request) == c1_request_hash(c1_request)


# ============================================================
# 回执透传
# ============================================================


async def test_save_draft_surfaces_invalidation_public_view(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """保存接住回执并透传公共视图（经组合根注册的真实视图缝，无测试替身）。"""
    db, nid = db_session, test_project_id
    await _scene(db, nid, scene_index=0, chapter_index=1)
    await _working_draft(db, nid, 1, 1, CH1_V1)

    contract = await create_draft_only(db, nid, 1, "第1章", CH1_V2)

    view = contract.invalidation
    assert isinstance(view, dict), "保存契约须透传 invalidation 公共视图"
    assert INVALIDATION_VIEW_KEYS <= set(view)
    assert view["receipt_id"]
    assert view["changed"] is True and view["nothing_to_do"] is False
    assert any(item["basis"] == "known" for item in view["affected"])
    assert view["recompute_options"], "失效后须提供三分类重算选项"
    # 透传不落库：视图片段挂在瞬态属性上，WritingDraft 无同名映射列。
    mapper_keys = {column.key for column in sa_inspect(WritingDraft).mapper.column_attrs}
    assert "invalidation" not in mapper_keys


async def test_autosave_api_response_carries_invalidation_view(
    async_client, db_session: AsyncSession, test_project_id: str
) -> None:
    """编辑保存链路（autosave API）的响应契约增量携带 invalidation。"""
    nid = test_project_id
    await _working_draft(db_session, nid, 1, 1, CH1_V1)

    resp = await async_client.post(
        "/api/writing/drafts/autosave",
        json={
            "novel_id": nid,
            "chapter_index": 1,
            "title": "第1章",
            "content": CH1_V2,
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert INVALIDATION_VIEW_KEYS <= set(body["invalidation"])
    assert body["invalidation"]["receipt_id"]


# ============================================================
# 预览零写入 / 取消零副作用
# ============================================================


async def test_preview_is_zero_write_and_cancel_is_side_effect_free(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """预览纯读组装；预览后不采用（取消/过期）正史零写入。"""
    db, nid = db_session, test_project_id
    await _scene(db, nid, scene_index=0, chapter_index=1)
    await _working_draft(db, nid, 1, 1, CH1_V1)
    await create_draft_only(db, nid, 1, "第1章", CH1_V2)  # 触发真实失效

    rag_before = await _rag_rows(db, nid)
    tasks_before = await _task_count(db, nid)
    drafts_before = len(
        list(
            await db.scalars(
                select(WritingDraft.id).where(WritingDraft.novel_id == UUID(nid))
            )
        )
    )

    preview = await WritingRecomputeService().preview(db, _reload_request(nid))

    assert preview.domain_write_performed is False, "预览结构上零正史写入"
    assert preview.executable is True
    assert preview.covers == ["evidence_chapter_index"]
    assert preview.cost and preview.write_effect
    assert [item.action for item in preview.actions] == ["reload_evidence"]
    assert preview.source_state["chapters"]["1"]["version_number"] == 2

    # 取消 = 不 adopt：索引状态/任务数/稿件数与预览前逐位一致。
    assert await _rag_rows(db, nid) == rag_before
    assert await _task_count(db, nid) == tasks_before
    after = len(
        list(
            await db.scalars(
                select(WritingDraft.id).where(WritingDraft.novel_id == UUID(nid))
            )
        )
    )
    assert after == drafts_before


# ============================================================
# 执行：确认门 / unsupported / 幂等 / 冲突保留
# ============================================================


async def test_adopt_requires_confirmation_and_regenerate_prose_unsupported(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """执行须显式确认；regenerate_prose 无白名单支撑显式拒绝（零 LLM）。"""
    db, nid = db_session, test_project_id
    await _working_draft(db, nid, 1, 1, CH1_V1)
    service = WritingRecomputeService()

    unconfirmed = WritingRecomputeAdoptRequest(
        novel_id=nid,
        operation_id=f"op-{uuid.uuid4()}",
        scope="reload_evidence",
        targets=[WritingRecomputeTarget(chapter_index=1)],
    )
    with pytest.raises(ValidationError) as excinfo:
        await service.adopt(db, unconfirmed)
    assert excinfo.value.code == "recompute_confirmation_required"

    regenerate = WritingRecomputeAdoptRequest(
        novel_id=nid,
        operation_id=f"op-{uuid.uuid4()}",
        scope="regenerate_prose",
        targets=[WritingRecomputeTarget(chapter_index=1)],
        confirmed=True,
    )
    with pytest.raises(ConflictError) as excinfo:
        await service.adopt(db, regenerate)
    assert excinfo.value.code == "recompute_scope_unsupported"

    # unsupported 分支零域写入：无任务入队。
    assert await _task_count(db, nid) == 0


async def test_adopt_reload_evidence_is_idempotent(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """同一 operation_id+指纹重复执行：复用同一索引任务，零重复域写入。"""
    db, nid = db_session, test_project_id
    await _working_draft(db, nid, 1, 1, CH1_V1)
    await create_draft_only(db, nid, 1, "第1章", CH1_V2)

    service = WritingRecomputeService()
    request = WritingRecomputeAdoptRequest(
        novel_id=nid,
        operation_id=f"op-{uuid.uuid4()}",
        scope="reload_evidence",
        targets=[WritingRecomputeTarget(chapter_index=1)],
        confirmed=True,
        expected_source_digest=(
            await service.preview(db, _reload_request(nid))
        ).source_digest,
    )

    first = await service.adopt(db, request)
    tasks_after_first = await _task_count(db, nid)
    rag_after_first = await _rag_rows(db, nid)

    second = await service.adopt(db, request)

    assert second.request_hash == first.request_hash
    assert second.results == first.results
    assert await _task_count(db, nid) == tasks_after_first, "重放不得新增任务"
    assert await _rag_rows(db, nid) == rag_after_first, "重放不得新增索引状态行"
    task_types = set(
        await db.scalars(
            select(AsyncTask.task_type).where(AsyncTask.novel_id == UUID(nid))
        )
    )
    assert task_types <= {"rag_index_chapter"}, "只允许证据重读类白名单任务"


async def test_adopt_source_drift_conflict_keeps_current_draft(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """预览后来源再变：执行拒绝并返回可比较数据，当前稿保留。"""
    db, nid = db_session, test_project_id
    await _working_draft(db, nid, 1, 1, CH1_V1)
    await create_draft_only(db, nid, 1, "第1章", CH1_V2)

    service = WritingRecomputeService()
    preview = await service.preview(db, _reload_request(nid))

    # 预览后作者又保存了一版（来源漂移）。
    later = await create_draft_only(db, nid, 1, "第1章", CH1_V3)
    tasks_before_adopt = await _task_count(db, nid)

    request = WritingRecomputeAdoptRequest(
        novel_id=nid,
        operation_id=preview.operation_id,
        scope="reload_evidence",
        targets=[WritingRecomputeTarget(chapter_index=1)],
        confirmed=True,
        expected_source_digest=preview.source_digest,
    )
    try:
        await service.adopt(db, request)
        raise AssertionError("来源漂移须被拒绝")
    except ConflictError as error:
        assert error.code == "recompute_source_drift"
        assert error.context["keep_current_draft"] is True
        assert error.context["current"]["1"]["version_number"] == 3
        assert error.context["current"]["1"]["content_hash"] == later.content_hash

    latest = (
        await db.execute(
            select(WritingDraft)
            .where(
                WritingDraft.novel_id == UUID(nid),
                WritingDraft.chapter_index == 1,
            )
            .order_by(WritingDraft.version_number.desc())
            .limit(1)
        )
    ).scalar_one()
    assert latest.content == CH1_V3, "当前稿保留，不被过期重算覆盖"
    assert await _task_count(db, nid) == tasks_before_adopt, "拒绝路径零新任务"


async def test_adopt_rebuild_derived_state_restores_checkpoints_idempotently(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """重建派生状态：软失效的 checkpoint 恢复 current，重放不增行。"""
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid, scene_index=0, chapter_index=1)
    await _working_draft(db, nid, 1, 1, CH1_V1)
    key_id = str(uuid.uuid4())
    memory = MemoryService()
    await memory.record_scene_events(
        db,
        nid,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key_id,
                "snapshot_after": {"name": "铜钥匙"},
            },
        ],
    )
    projection = SceneMemoryProjectionService()
    await projection.ensure_scene(db, nid, str(scene.id))
    assert all(row.is_current for row in await _checkpoint_rows(db, nid, scene.id))

    # 改稿保存 → 派生投影软失效（历史行保留）。
    await create_draft_only(db, nid, 1, "第1章", CH1_V2)
    stale_rows = await _checkpoint_rows(db, nid, scene.id)
    assert stale_rows and all(not row.is_current for row in stale_rows)

    service = WritingRecomputeService()
    request = WritingRecomputeAdoptRequest(
        novel_id=nid,
        operation_id=f"op-{uuid.uuid4()}",
        scope="rebuild_derived_state",
        targets=[WritingRecomputeTarget(scene_index=0)],
        confirmed=True,
    )
    first = await service.adopt(db, request)
    assert first.domain_write_performed is True

    restored = await _checkpoint_rows(db, nid, scene.id)
    assert any(row.is_current for row in restored), "重算后场景派生状态恢复 current"
    assert len(restored) > len(stale_rows), "重建生成新行（旧行保留为历史）"

    second = await service.adopt(db, request)
    assert second.request_hash == first.request_hash
    replayed = await _checkpoint_rows(db, nid, scene.id)
    assert len(replayed) == len(restored), "重放不产生重复 checkpoint 行"
    assert any(row.is_current for row in replayed)


# ============================================================
# API 出口
# ============================================================


async def test_recompute_endpoints_http_contract(
    async_client, db_session: AsyncSession, test_project_id: str
) -> None:
    """POST /api/writing/recompute（预览）与 /{operation_id}/adopt（执行）。"""
    nid = test_project_id
    await _working_draft(db_session, nid, 1, 1, CH1_V1)
    await create_draft_only(db_session, nid, 1, "第1章", CH1_V2)

    operation_id = f"op-{uuid.uuid4()}"
    preview_resp = await async_client.post(
        "/api/writing/recompute",
        json={
            "novel_id": nid,
            "operation_id": operation_id,
            "scope": "reload_evidence",
            "targets": [{"chapter_index": 1}],
        },
    )
    assert preview_resp.status_code == 200, preview_resp.text
    preview = preview_resp.json()
    assert preview["domain_write_performed"] is False
    assert preview["source_digest"]

    adopt_resp = await async_client.post(
        f"/api/writing/recompute/{operation_id}/adopt",
        json={
            "novel_id": nid,
            "operation_id": operation_id,
            "scope": "reload_evidence",
            "targets": [{"chapter_index": 1}],
            "confirmed": True,
            "expected_source_digest": preview["source_digest"],
        },
    )
    assert adopt_resp.status_code == 200, adopt_resp.text
    outcome = adopt_resp.json()
    assert outcome["domain_write_performed"] is True
    assert outcome["request_hash"] == preview["request_hash"]

    mismatched = await async_client.post(
        f"/api/writing/recompute/{operation_id}-other/adopt",
        json={
            "novel_id": nid,
            "operation_id": operation_id,
            "scope": "reload_evidence",
            "targets": [{"chapter_index": 1}],
            "confirmed": True,
        },
    )
    assert mismatched.status_code == 400

    drift = await async_client.post(
        f"/api/writing/recompute/{operation_id}-drift/adopt",
        json={
            "novel_id": nid,
            "operation_id": f"{operation_id}-drift",
            "scope": "reload_evidence",
            "targets": [{"chapter_index": 1}],
            "confirmed": True,
            "expected_source_digest": "0" * 64,
        },
    )
    assert drift.status_code == 409
    assert drift.json()["error"] == "recompute_source_drift"
    assert drift.json()["context"]["keep_current_draft"] is True
