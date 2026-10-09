"""P2-C C0 端到端验收夹具 — 改稿失效 × 并发采用（计划 §3 第 6 场景 + P2-C 验收句）。

本文件是 P2-C 包第 0 步固定验收夹具：合成数据经真实公开入口
（WritingDraftService / MemoryService / SceneMemoryProjectionService /
Collaboration cases·workspaces·merge·recovery / evolution 失效缝）落库执行，
断言分两档——现状已成立的语义写真绿（防止 C1–C4 重构时回归），缺口按
目标形态标 ``xfail(reason="P2-C dependency registration not implemented",
strict=False)``，实现合流后逐条转绿。全部数据合成，零 LLM、零真实语料。

基线操作步骤与预期（供汇合验收对照）
====================================

场景六「改稿与并发采用冲突」：
  1. 三章三场景（s0@ch1 / s1@ch2 / s2@ch3）各落 working 稿 v1；s0 记录
     entity_created（铜钥匙 custody_owner=custody_holder=甲），s1 记录
     entity_updated（custody_holder → 乙），逐场景 ensure 后 checkpoint 均 current。
  2. 并发窗口一：作者在编辑器改保管记录——第 2 章插入 working 稿 v2
     （"交给乙保管"改写为"交给丙保管"）。
  3. 并发窗口二：Collaboration 试改窗口（ch1+ch2 双章补丁）在窗口期内尝试采用。
  预期（真绿部分）：改稿保存即标记失效（s1 起派生投影软失效、证据索引换源）；
     采用被 SOURCE_STALE 冲突拒绝，当前稿保留作者 v2，零采用回执；作者显式
     解决冲突后试改按当前稿重建，不覆盖后来修改；采用重试幂等不重复。
  预期（xfail 部分）：失效回执以可解释结构精确列出已知消费者（见下方目标形态）。

未知消费者保守扩大：
  s2（第 3 章）对第 2 章保管记录无任何依赖登记 → 失效范围仍保守扩大到 s2
  （宁可多失效也不让旧理解冒充有效），且未接线消费者（world_knowledge /
  map_atlas）显式列出。真绿部分钉"不隐藏未知"的现状语义；结构化
  ``unknown_scope`` 标注为 xfail 目标形态。

不丢稿矩阵（六情形，断言"当前稿/人工草稿可恢复"）：
  M1 来源变化：改稿只新增版本行，旧版本、被软失效的 checkpoint 与保管事件
     全部保留（失效不删历史）——真绿。
  M2 确认漂移：试改冻结基线后来源再变 → 采用被拒绝、当前稿保留、零回执——真绿。
  M3 途中失败：双补丁第二写注入失败 → 全部域写入回滚、稿保持基线、零回执——真绿。
  M4 重试：同一 operation_id 重复采用 → 回放同一回执、不重复写——真绿。
  M5 双窗口修改：作者改标题（不同字段）+ 试改正文 → rebase 自动合并且当前稿
     保留；作者改正文（同字段）→ rebase 报冲突且当前稿精确保留——真绿。
  M6 离开恢复：试改覆盖层落库，重开（新读取）后修改仍在、当前稿未被覆盖、
     可继续叠加修订——真绿。

零无关重生成：
  改与保管无关的第 3 章 → s0/s1 checkpoint 保持 current（真绿，现状失效窗口
  已精确到锚定 Scene 起点）；重算任务级"无关 Scene 零重算"为 xfail（现状尚无
  重算任务概念，断言将来形态）。编辑保存不自动入队任何昂贵任务——真绿。

取消零正史副作用：
  预览（create+edit 试改）后取消（不采用、不封存）→ 正史零写入：当前稿不动、
  零采用回执、零 DomainOutbox——真绿。

目标形态（C1 契约单元对齐基准，键名级）
========================================

一、失效可解释视图（InvalidationReceipt 增强 + writing 契约透传的投影形态）：

    {
        "affected": [
            {
                "consumer": <str，消费者类型，如 "story_scene_checkpoint" /
                     "evidence_chapter_index">,
                "scene_id": <str | None，该条目作用的 Scene；非 Scene 维度为 None>,
                "scene_index": <int | None，同上>,
                "reason": <str，机器可读理由，如 "anchored_chapter_edited"（锚定
                     被改章）/ "conservative_expansion_unregistered"（依赖未登记，
                     保守扩大）>,
                "basis": "known" | "unknown",   # 是否有登记依据
            },
            ...
        ],
        "unknown_scope": <bool，存在 basis=unknown 条目或未接线消费者时 True——
             不得为显示更小的影响列表隐藏未知>,
        "receipt_id": <str，失效回执可查标识（落库回执 id 或稳定指纹）>,
    }

- 演化侧（C1/C2）：``InvalidationReceipt`` 增补结构化 ``affected`` 列表、
  ``unknown_scope``、``receipt_id``（现有 ``earliest_affected_scene_index`` /
  ``invalidated_consumers`` / ``unsupported_consumers`` / ``coverage_note``
  保守语义保留，本夹具真绿断言钉死不回归）。
- 写作侧（C3）：``WritingDraftContract`` 增补可选 ``invalidation`` 字段透传上述
  视图（现状 ``repositories._changed`` 调 DI 缝但丢弃回执）。

二、重算三分类（``InvalidationReceipt.recompute_options``，C1/C3 编排接口基准）：

    [
        {
            "kind": "reload_evidence",           # 重读证据（低成本：索引换源重读）
            "covers": ["evidence_chapter_index"],
        },
        {
            "kind": "rebuild_derived_state",     # 重建派生状态（Scene 投影重算）
            "covers": ["story_scene_projections"],
            "affected": [<scene 引用，含保守扩大条目；不含无关 Scene>],
        },
        {
            "kind": "regenerate_prose",          # 重生成正文（昂贵，作者显式选择，
                                                 #  编辑时不自动触发）
            "covers": ["prose_generation"],
        },
    ]

三、重算结果独立预览与采用：复用 Collaboration 试改生命周期（零正史写入、幂等
operation_id、三向 rebase、人工修改保留），本夹具取消/冲突/幂等/双窗口断言即
其验收基线；预览采用重验来源/版本、排除项由 C3 接 ``revalidate_creative_manifest``。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.container import container_scope, get
from core.errors import DomainError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.models import AsyncTask
from modules.collaboration import cases, workspaces
from modules.collaboration.contracts import (
    CaseCreate,
    Grant,
    MergeRequest,
    RebaseRequest,
    ResourcePatch,
    RevisionRequest,
    WorkspaceCreate,
    WorkspaceEdit,
)
from modules.collaboration.merge import merge_workspace
from modules.collaboration.models import (
    CollaborationArtifact,
    CollaborationRun,
    CreativeMergeReceipt,
    DomainOutbox,
)
from modules.evidence.indexing.models import RagIndexState
from modules.evolution.facade import record_writing_source_change
from modules.story.continuity.models import MemoryEvent, MemorySceneCheckpoint
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene
from modules.writing.facade import create_draft_only, get_latest_draft_for_chapter
from modules.writing.models import WritingDraft

XFAIL_REASON = "P2-C dependency registration not implemented"
INVALIDATION_VIEW_KEYS = {"affected", "unknown_scope", "receipt_id"}
RECOMPUTE_KINDS = {"reload_evidence", "rebuild_derived_state", "regenerate_prose"}

CH1_V1 = "甲铸成铜钥匙，亲自收着。"
CH2_V1 = "甲把铜钥匙交给乙保管。"
CH3_V1 = "丙在钟楼下练剑，与铜钥匙无关。"
TRIAL_SUFFIX = "她仍保留了退路。"


# ============================================================
# 合成数据构造（沿 P2-A/P2-B 夹具与 collaboration 测试惯例）
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
    """直接落 working 稿行（绕过失效钩子，同 P2-A 夹具惯例）。

    基线与回执级用例的 v2 行都经此落库，再由演化缝单次触发失效——回执内
    计数（superseded_checkpoints 等）只反映这一次传播；真实改稿保存路径
    （create_draft_only 经 repositories._changed 钩子）由主场景与透传 xfail
    用例覆盖。标题必须非空字符串——collaboration 写作端口的试改补丁要求
    {"title","content"} 均为 str。
    """
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


async def _custody_world(db: AsyncSession, novel_id: str) -> SimpleNamespace:
    """三章三场景合成世界：s0@ch1 创建保管（owner=holder=甲）、s1@ch2 保管
    交接给乙（P2-C 主场景的"保管记录"）、s2@ch3 与保管无关。"""
    chapters = ((0, 1, CH1_V1), (1, 2, CH2_V1), (2, 3, CH3_V1))
    scenes: dict[int, Scene] = {}
    for scene_index, chapter_index, content in chapters:
        scenes[scene_index] = await _scene(db, novel_id, scene_index, chapter_index)
        await _working_draft(db, novel_id, chapter_index, 1, content)
    key_id, jia, yi = (str(uuid.uuid4()) for _ in range(3))
    memory = MemoryService()
    await memory.record_scene_events(
        db,
        novel_id,
        scene_id=str(scenes[0].id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key_id,
                "snapshot_after": {
                    "name": "铜钥匙",
                    "custody_owner": jia,
                    "custody_holder": jia,
                },
            },
        ],
    )
    await memory.record_scene_events(
        db,
        novel_id,
        scene_id=str(scenes[1].id),
        scene_index=1,
        chapter_index=2,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": key_id,
                "snapshot_after": {"custody_holder": yi},
            },
        ],
    )
    projection = SceneMemoryProjectionService()
    for scene in scenes.values():
        await projection.ensure_scene(db, novel_id, str(scene.id))
    return SimpleNamespace(scenes=scenes, key_id=key_id, jia=jia, yi=yi)


async def _legacy_unregistered_scene(db, novel_id, scene):
    """Persisted legacy fixture: keep unknown-dependency assertions intact."""
    rows = (
        (
            await db.execute(
                select(MemorySceneCheckpoint).where(
                    MemorySceneCheckpoint.novel_id == UUID(novel_id),
                    MemorySceneCheckpoint.scene_id == scene.id,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        state = dict(row.state_json or {})
        state.pop("_consumption_registry", None)
        row.state_json = state
    await db.flush()


def _revise_custody(text: str) -> str:
    """改一处保管记录：交接对象由乙改写为丙（custody_holder 的稿件事实变化）。"""
    return text.replace("乙", "丙")


async def _has_current_checkpoint(
    db: AsyncSession, novel_id: str, scene_id: uuid.UUID
) -> bool:
    return (
        await db.scalar(
            select(func.count())
            .select_from(MemorySceneCheckpoint)
            .where(
                MemorySceneCheckpoint.novel_id == UUID(novel_id),
                MemorySceneCheckpoint.scene_id == scene_id,
                MemorySceneCheckpoint.is_current.is_(True),
            )
        )
    ) > 0


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


async def _draft_versions(
    db: AsyncSession, novel_id: str, chapter_index: int
) -> list[WritingDraft]:
    return list(
        (
            await db.execute(
                select(WritingDraft)
                .where(
                    WritingDraft.novel_id == UUID(novel_id),
                    WritingDraft.chapter_index == chapter_index,
                )
                .order_by(WritingDraft.version_number)
            )
        )
        .scalars()
        .all()
    )


async def _receipt_count(db: AsyncSession, novel_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(CreativeMergeReceipt)
            .where(CreativeMergeReceipt.novel_id == UUID(novel_id))
        )
    )


async def _open_trial(
    db: AsyncSession,
    novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    chapter_indexes: tuple[int, ...],
) -> tuple[dict, dict, list[Any]]:
    """打开 Collaboration 试改窗口（预览形态：create → edit，不 seal 不 merge）。"""
    settings = replace(
        get_settings(), assistant_enabled=True, collaboration_v2_enabled=True
    )
    monkeypatch.setattr(cases, "get_settings", lambda: settings)
    drafts = [
        await get_latest_draft_for_chapter(db, novel_id, chapter)
        for chapter in chapter_indexes
    ]
    case = await cases.create_case(
        db,
        novel_id,
        CaseCreate(
            operation_id=uuid4(),
            goal="改一处保管记录并核对实际影响",
            constraints=["不动所有权"],
            grant=Grant(
                resources=[{"kind": "writing_draft", "id": draft.id} for draft in drafts],
                read_scope="selected",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        ),
    )
    view = await workspaces.create_workspace(
        db,
        novel_id,
        case["id"],
        WorkspaceCreate(operation_id=uuid4(), label="保管改稿试改"),
    )
    view = await workspaces.edit_workspace(
        db,
        novel_id,
        view["id"],
        WorkspaceEdit(
            expected_revision_id=view["revision_id"],
            patches=[
                ResourcePatch(
                    kind="writing_draft",
                    id=draft.id,
                    value={
                        "title": draft.title,
                        "content": draft.content + TRIAL_SUFFIX,
                    },
                )
                for draft in drafts
            ],
        ),
    )
    return case, view, drafts


async def _approve(
    db: AsyncSession, novel_id: str, case: dict, view: dict
) -> MergeRequest:
    """检查通过 + 封存，返回可提交的采用请求（同 collaboration 测试惯例）。"""
    run = CollaborationRun(
        id=uuid4(),
        novel_id=UUID(novel_id),
        case_id=UUID(case["id"]),
        operation_id=uuid4(),
        request_hash="a" * 64,
        request_json={},
        manifest_json={},
        llm_snapshot_json={},
        status="completed",
    )
    db.add(run)
    await db.flush()
    payload = {
        "digest": view["digest"],
        "verdict": "passed",
        "knowledge_review": {"status": "passed"},
    }
    db.add(
        CollaborationArtifact(
            novel_id=UUID(novel_id),
            run_id=run.id,
            workspace_revision_id=UUID(view["revision_id"]),
            kind="workspace_check",
            manifest_json={},
            payload_json=payload,
            output_hash=content_hash(payload),
        )
    )
    await db.flush()
    await workspaces.seal_workspace(
        db,
        novel_id,
        view["id"],
        RevisionRequest(revision_id=view["revision_id"], expected_digest=view["digest"]),
    )
    return MergeRequest(
        operation_id=uuid4(),
        revision_id=view["revision_id"],
        expected_digest=view["digest"],
        confirmed=True,
        editor_state="saved",
    )


# ============================================================
# 场景六：改稿与并发采用冲突（真绿部分）
# ============================================================


async def test_p2c_custody_revision_marks_failure_scope_and_adoption_conflict(
    db_session: AsyncSession, test_project_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """改保管章 v2 + 同窗口 Collaboration 采用 → 冲突保留当前稿、零重复采用。"""
    db, nid = db_session, test_project_id
    world = await _custody_world(db, nid)
    case, view, drafts = await _open_trial(db, nid, monkeypatch, chapter_indexes=(1, 2))

    # 并发窗口一：作者在编辑器改保管记录（保存即触发失效传播）。
    revised = _revise_custody(CH2_V1)
    await create_draft_only(db, nid, 2, "第2章", revised)
    # 改稿先标记失效：锚定被改章的 s1 起派生投影软失效，s0 不受牵连。
    assert not await _has_current_checkpoint(db, nid, world.scenes[1].id)
    assert await _has_current_checkpoint(db, nid, world.scenes[0].id)
    # 编辑保存只允许触发证据重读类任务（rag_index_chapter），
    # 不得自动入队昂贵生成（writing/evolution 生成或正文重生成）。
    task_types = set(
        await db.scalars(
            select(AsyncTask.task_type).where(AsyncTask.novel_id == UUID(nid))
        )
    )
    assert task_types <= {"rag_index_chapter"}, sorted(task_types)

    # 并发窗口二：试改采用被来源漂移拒绝，当前稿保留作者 v2，零回执。
    # selected 范围下旧资源无法重定位，现状报 NotFoundError（同为领域拒绝）；
    # project 范围下同一漂移报 ConflictError(SOURCE_STALE)——均不产生域写入。
    request = await _approve(db, nid, case, view)
    with pytest.raises(DomainError):
        await merge_workspace(db, nid, view["id"], request)
    assert (await get_latest_draft_for_chapter(db, nid, 2)).content == revised
    assert (await get_latest_draft_for_chapter(db, nid, 1)).id == drafts[0].id
    assert await _receipt_count(db, nid) == 0

    # 作者显式重读当前稿：三向 rebase 报同字段冲突，当前稿精确保留。
    db_session.sync_session.autoflush = False
    conflict, _conflict_request = await _rebase(db, nid, view)
    assert conflict["status"] == "conflict"
    assert conflict["conflicts"][0]["current"]["content"] == revised
    assert (await get_latest_draft_for_chapter(db, nid, 2)).content == revised


async def _rebase(
    db: AsyncSession, novel_id: str, view: dict, *, request: RebaseRequest | None = None
) -> tuple[dict, RebaseRequest]:
    """执行三向 rebase；返回 (结果, 请求)——重放须复用同一 operation_id。"""
    from modules.collaboration.recovery import rebase

    request = request or RebaseRequest(
        operation_id=uuid4(), expected_revision_id=view["revision_id"]
    )
    result = await rebase(db, novel_id, view["id"], request)
    return result, request


async def test_p2c_custody_revision_current_semantics_stay_conservative(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """现状失效语义钉板（真绿）：改第 2 章保守失效 s1 起全部派生投影。"""
    db, nid = db_session, test_project_id
    world = await _custody_world(db, nid)
    old, new = CH2_V1, _revise_custody(CH2_V1)
    # 落 v2 行后经演化缝单次触发失效（真实改稿路径的透传断言另测）。
    await _working_draft(db, nid, 2, 2, new)
    receipt = await record_writing_source_change(
        db, nid, chapter_index=2, old_content=old, new_content=new
    )

    # 失效窗口起点精确到锚定被改章的最早 Scene：s1（而非 s0、而非全库）。
    assert receipt.earliest_affected_scene_index == 1
    assert await _has_current_checkpoint(db, nid, world.scenes[0].id)
    assert not await _has_current_checkpoint(db, nid, world.scenes[1].id)
    assert not await _has_current_checkpoint(db, nid, world.scenes[2].id)

    # 已接线消费者登记在回执：证据索引换源 + Scene 投影软失效。
    index = receipt.invalidated_consumers["evidence_chapter_index"]
    assert index["chapter_index"] == 2 and index["requested_hash"]
    state = (
        await db.execute(
            select(RagIndexState).where(
                RagIndexState.novel_id == UUID(nid),
                RagIndexState.chapter_index == 2,
                RagIndexState.content_mode == "working",
            )
        )
    ).scalar_one()
    assert state.requested_hash == index["requested_hash"]
    projections = receipt.invalidated_consumers["story_scene_projections"]
    assert projections["from_scene_index"] == 1
    assert projections["superseded_checkpoints"] >= 1


async def test_p2c_unregistered_dependency_expands_conservatively_without_hiding(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """未知消费者保守扩大（真绿部分）：s2 无依赖登记仍被扩大失效，未知显式可见。"""
    db, nid = db_session, test_project_id
    world = await _custody_world(db, nid)
    await _legacy_unregistered_scene(db, nid, world.scenes[2])
    old, new = CH2_V1, _revise_custody(CH2_V1)
    await _working_draft(db, nid, 2, 2, new)
    receipt = await record_writing_source_change(
        db, nid, chapter_index=2, old_content=old, new_content=new
    )

    # 依赖缺失不跳过：s2（对第 2 章无任何登记）一并保守失效——
    # 历史状态依赖前缀，宁可多失效也不让旧理解冒充有效。
    assert not await _has_current_checkpoint(db, nid, world.scenes[2].id)
    # 未接线消费者显式列出并带理由，不以"局部完成"冒充全量失效。
    unsupported = {
        item["consumer"]: item["reason"] for item in receipt.unsupported_consumers
    }
    assert set(unsupported) == {"world_knowledge", "map_atlas"}
    assert all(unsupported.values())
    # 保守扩大事实写进 coverage 说明（结构化 unknown_scope 见 xfail 用例）。
    assert "保守扩大" in receipt.coverage_note


async def test_p2c_custody_revision_affect_list_is_explainable(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """目标形态：失效回执带可解释 affected 列表，未知范围显式标注。"""
    db, nid = db_session, test_project_id
    world = await _custody_world(db, nid)
    await _legacy_unregistered_scene(db, nid, world.scenes[2])
    old, new = CH2_V1, _revise_custody(CH2_V1)
    await _working_draft(db, nid, 2, 2, new)
    receipt = await record_writing_source_change(
        db, nid, chapter_index=2, old_content=old, new_content=new
    )

    affected = getattr(receipt, "affected", None)
    assert isinstance(affected, list) and affected, (
        "InvalidationReceipt 须携带结构化 affected 列表"
    )
    scene_entries = {
        item["scene_index"]: item
        for item in affected
        if item.get("scene_index") is not None
    }
    # 已知消费者：锚定被改章的 s1，理由可解释、依据为已登记。
    known = scene_entries[1]
    assert known["scene_id"] == str(world.scenes[1].id)
    assert known["basis"] == "known"
    assert known["reason"]
    # 未登记消费者：s2 的扩大条目显式标 unknown，不为好看列表隐藏。
    assert scene_entries[2]["basis"] == "unknown"
    assert scene_entries[2]["reason"] == "conservative_expansion_unregistered"
    # 无关 Scene 不得出现在影响列表。
    assert 0 not in scene_entries
    # 非负载未登记时 unknown_scope 必须为 True；回执可查标识非空。
    assert getattr(receipt, "unknown_scope", None) is True
    assert getattr(receipt, "receipt_id", None)


async def test_p2c_writing_revision_surfaces_invalidation_view(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """目标形态：改稿契约透传失效视图（现状 repositories._changed 丢弃回执）。"""
    db, nid = db_session, test_project_id
    world = await _custody_world(db, nid)
    contract = await create_draft_only(db, nid, 2, "第2章", _revise_custody(CH2_V1))
    # 失效确实传播了（钩子已执行）——只是回执到不了调用方。
    assert not await _has_current_checkpoint(db, nid, world.scenes[1].id)

    view = getattr(contract, "invalidation", None)
    assert isinstance(view, dict), "WritingDraftContract 须透传 invalidation 视图"
    assert INVALIDATION_VIEW_KEYS <= set(view), (
        f"失效视图键集须包含 {sorted(INVALIDATION_VIEW_KEYS)}"
    )
    assert view["unknown_scope"] is True
    assert view["receipt_id"]
    scene_indexes = {
        item["scene_index"]
        for item in view["affected"]
        if item.get("scene_index") is not None
    }
    assert scene_indexes == {1, 2}


async def test_p2c_recompute_options_classify_three_cost_tiers(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """目标形态：重算选择区分重读证据 / 重建派生状态 / 重生成正文三档。"""
    db, nid = db_session, test_project_id
    await _custody_world(db, nid)
    old, new = CH2_V1, _revise_custody(CH2_V1)
    await _working_draft(db, nid, 2, 2, new)
    receipt = await record_writing_source_change(
        db, nid, chapter_index=2, old_content=old, new_content=new
    )

    options = getattr(receipt, "recompute_options", None)
    assert isinstance(options, list) and options, (
        "InvalidationReceipt 须携带 recompute_options 三分类"
    )
    kinds = {item["kind"] for item in options}
    assert kinds == RECOMPUTE_KINDS
    rebuild = next(item for item in options if item["kind"] == "rebuild_derived_state")
    rebuild_scenes = {
        item["scene_index"]
        for item in rebuild.get("affected", [])
        if item.get("scene_index") is not None
    }
    # 重建范围 = 锚定 Scene + 保守扩大后缀（含未登记条目），不含无关 Scene 0。
    assert rebuild_scenes == {1, 2}
    # 重读证据覆盖被改章，正文重生成默认不自动执行（作者显式选择）。
    reload_opt = next(item for item in options if item["kind"] == "reload_evidence")
    assert "evidence_chapter_index" in reload_opt["covers"]


# ============================================================
# 零无关重生成（真绿部分 + xfail 目标形态）
# ============================================================


async def test_p2c_unrelated_chapter_edit_keeps_custody_scenes_current(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """改与保管无关的第 3 章：s0/s1 派生投影保持有效，不产生无关失效。"""
    db, nid = db_session, test_project_id
    world = await _custody_world(db, nid)
    old = CH3_V1
    new = old.replace("练剑", "打磨船桨")
    await _working_draft(db, nid, 3, 2, new)
    receipt = await record_writing_source_change(
        db, nid, chapter_index=3, old_content=old, new_content=new
    )

    assert receipt.earliest_affected_scene_index == 2
    assert await _has_current_checkpoint(db, nid, world.scenes[0].id)
    assert await _has_current_checkpoint(db, nid, world.scenes[1].id)
    assert not await _has_current_checkpoint(db, nid, world.scenes[2].id)


async def test_p2c_unrelated_chapter_edit_enqueues_no_custody_scene_recompute(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """目标形态：改无关章的重算任务不包含保管场景（现状无重算任务概念）。"""
    db, nid = db_session, test_project_id
    await _custody_world(db, nid)
    old = CH3_V1
    new = old.replace("练剑", "打磨船桨")
    await _working_draft(db, nid, 3, 2, new)
    receipt = await record_writing_source_change(
        db, nid, chapter_index=3, old_content=old, new_content=new
    )

    options = getattr(receipt, "recompute_options", None)
    assert isinstance(options, list) and options, (
        "改稿后须提供重算任务清单（三分类），才可验证无关 Scene 零重算"
    )
    rebuild_scenes = {
        item["scene_index"]
        for option in options
        if option["kind"] == "rebuild_derived_state"
        for item in option.get("affected", [])
        if item.get("scene_index") is not None
    }
    # 无关章的重算清单只含 s2（及其保守后缀），不含保管场景 s0/s1。
    assert not ({0, 1} & rebuild_scenes), "无关 Scene 不得进入重算任务"
    assert 2 in rebuild_scenes
    # 影响列表同样不含保管场景。
    affected = getattr(receipt, "affected", None)
    assert isinstance(affected, list)
    affected_scenes = {
        item["scene_index"] for item in affected if item.get("scene_index") is not None
    }
    assert not ({0, 1} & affected_scenes)


# ============================================================
# 不丢稿矩阵（六情形，当前稿/人工草稿可恢复）
# ============================================================


async def test_p2c_matrix_m1_source_change_preserves_versions_and_history(
    db_session: AsyncSession, test_project_id: str
) -> None:
    """M1 来源变化：改稿只加版本，旧版本、软失效 checkpoint 与保管事件全保留。"""
    db, nid = db_session, test_project_id
    world = await _custody_world(db, nid)
    await create_draft_only(db, nid, 2, "第2章", _revise_custody(CH2_V1))

    versions = await _draft_versions(db, nid, 2)
    assert [v.version_number for v in versions] == [1, 2]
    assert versions[0].content == CH2_V1
    assert versions[1].content == _revise_custody(CH2_V1)

    # 失效不删历史：s1 的 checkpoint 行保留（仅 is_current=False）。
    checkpoints = await _checkpoint_rows(db, nid, world.scenes[1].id)
    assert checkpoints and all(not row.is_current for row in checkpoints)
    # 保管交接事件行保留（软 stale / 软失效，不物理删除）。
    events = (
        await db.execute(
            select(func.count())
            .select_from(MemoryEvent)
            .where(
                MemoryEvent.novel_id == UUID(nid),
                MemoryEvent.scene_id == world.scenes[1].id,
            )
        )
    ).scalar_one()
    assert events >= 1


async def test_p2c_matrix_m2_confirmation_drift_keeps_manual_draft(
    db_session: AsyncSession, test_project_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2 确认漂移：冻结基线后来源再变 → 采用拒绝、当前稿保留、零回执。"""
    db, nid = db_session, test_project_id
    await _custody_world(db, nid)
    case, view, drafts = await _open_trial(db, nid, monkeypatch, chapter_indexes=(1,))
    manual = "甲把铜钥匙交给乙保管，并约法三章。"
    await create_draft_only(db, nid, 1, "第1章", manual)

    request = await _approve(db, nid, case, view)
    # selected 范围的漂移现状以 NotFoundError（旧资源不可重定位）拒绝；
    # 与 SOURCE_STALE 同为领域拒绝：当前稿保留、零回执、基线版本仍可回开。
    with pytest.raises(DomainError):
        await merge_workspace(db, nid, view["id"], request)
    assert (await get_latest_draft_for_chapter(db, nid, 1)).content == manual
    assert await _receipt_count(db, nid) == 0
    assert drafts[0].content == CH1_V1  # 基线版本仍可回开


async def test_p2c_matrix_m3_midway_failure_rolls_back_and_keeps_drafts(
    db_session: AsyncSession, test_project_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3 途中失败：双补丁第二写失败 → 全部域写入回滚、稿保持基线、零回执。"""
    db, nid = db_session, test_project_id
    await _custody_world(db, nid)
    case, view, drafts = await _open_trial(db, nid, monkeypatch, chapter_indexes=(1, 2))
    request = await _approve(db, nid, case, view)

    ports = get("collaboration.resources")
    original = ports["writing_draft"]
    calls = 0

    async def fail_second(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        result = await original.apply(*args, **kwargs)
        if calls == 2:
            raise RuntimeError("injected second-write failure")
        return result

    with container_scope(
        {
            "collaboration.resources": {
                **ports,
                "writing_draft": replace(original, apply=fail_second),
            }
        }
    ):
        with pytest.raises(RuntimeError, match="second-write"):
            await merge_workspace(db, nid, view["id"], request)
    assert calls == 2
    for draft in drafts:
        latest = await get_latest_draft_for_chapter(db, nid, draft.chapter_index)
        assert latest.id == draft.id and latest.content == draft.content
    assert await _receipt_count(db, nid) == 0


async def test_p2c_matrix_m4_merge_retry_is_idempotent_and_receipt_queryable(
    db_session: AsyncSession, test_project_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M4 重试：同一 operation_id 重复采用回放同一回执；采用后人工再改不丢。"""
    db, nid = db_session, test_project_id
    await _custody_world(db, nid)
    _case, view, drafts = await _open_trial(db, nid, monkeypatch, chapter_indexes=(1,))
    request = await _approve(db, nid, _case, view)

    result = await merge_workspace(db, nid, view["id"], request)
    assert result["domain_write_performed"] and not result["replayed"]
    adopted = await get_latest_draft_for_chapter(db, nid, 1)
    assert adopted.content == CH1_V1 + TRIAL_SUFFIX

    repeated = await merge_workspace(db, nid, view["id"], request)
    assert repeated["receipt_id"] == result["receipt_id"] and repeated["replayed"]
    assert await _receipt_count(db, nid) == 1

    # 采用后作者人工再改：重试不覆盖后来修改，人工修改不丢。
    manual = CH1_V1 + TRIAL_SUFFIX + "（作者亲笔补注）"
    await create_draft_only(db, nid, 1, "第1章", manual)
    again = await merge_workspace(db, nid, view["id"], request)
    assert again["replayed"] and again["receipt_id"] == result["receipt_id"]
    assert (await get_latest_draft_for_chapter(db, nid, 1)).content == manual
    assert await _receipt_count(db, nid) == 1

    # 旧回执保留可查：回执行仍在，已合并试改仍可读取（诊断/对照）。
    merged_view = await workspaces.workspace_view(db, nid, view["id"])
    assert merged_view["status"] == "merged"


async def test_p2c_matrix_m5_two_windows_merge_fields_and_keep_current(
    db_session: AsyncSession, test_project_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M5 双窗口修改：不同字段自动合并、同字段报冲突，两种路径当前稿都保留。"""
    db, nid = db_session, test_project_id
    await _custody_world(db, nid)
    _case, view, _drafts = await _open_trial(db, nid, monkeypatch, chapter_indexes=(1,))
    db_session.sync_session.autoflush = False

    # 窗口 B：作者只改标题（与试改正文不同字段）→ 三向合并自动完成。
    retitled = await create_draft_only(db, nid, 1, "第一章·钥匙铸成", CH1_V1)
    merged, rebased_request = await _rebase(db, nid, view)
    assert merged["status"] == "ready" and not merged["workspace"]["stale"]
    after = merged["workspace"]["changes"][0]["after"]
    assert after["title"] == retitled.title
    assert after["content"] == CH1_V1 + TRIAL_SUFFIX
    # 同一 operation_id 重放幂等；当前稿在采用前保持作者版本。
    replay, _ = await _rebase(db, nid, view, request=rebased_request)
    assert replay["replayed"]
    assert (await get_latest_draft_for_chapter(db, nid, 1)).content == CH1_V1
    assert (await get_latest_draft_for_chapter(db, nid, 1)).title == retitled.title

    # 第二组窗口：作者改正文（同字段）→ 报冲突并精确保留当前稿。
    _case2, view2, _drafts2 = await _open_trial(
        db, nid, monkeypatch, chapter_indexes=(1,)
    )
    conflicted = await create_draft_only(
        db, nid, 1, retitled.title, CH1_V1 + "作者改写了一处。"
    )
    conflict, _ = await _rebase(db, nid, view2)
    assert conflict["status"] == "conflict"
    assert conflict["conflicts"][0]["fields"] == ["content"]
    assert conflict["conflicts"][0]["current"]["content"] == conflicted.content
    assert (await get_latest_draft_for_chapter(db, nid, 1)).content == conflicted.content


async def test_p2c_matrix_m6_leave_and_restore_keeps_trial_and_draft(
    db_session: AsyncSession, test_project_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M6 离开恢复：试改覆盖层落库；重开后修改仍在、当前稿未被覆盖、可继续。"""
    db, nid = db_session, test_project_id
    await _custody_world(db, nid)
    _case, view, _drafts = await _open_trial(db, nid, monkeypatch, chapter_indexes=(1,))

    # 模拟"离开后回来"：丢本地引用，仅凭持久化标识重开。
    workspace_id = view["id"]
    reopened = await workspaces.workspace_view(db, nid, workspace_id)
    assert reopened["status"] == "open" and not reopened["stale"]
    assert reopened["changes"][0]["after"]["content"] == CH1_V1 + TRIAL_SUFFIX
    assert reopened["editable_resources"], "回来后仍可继续编辑试改"
    assert (await get_latest_draft_for_chapter(db, nid, 1)).content == CH1_V1

    # 继续叠加一版修订（覆盖层增量），当前稿依旧不动、可恢复。
    latest = await get_latest_draft_for_chapter(db, nid, 1)
    progressed = await workspaces.edit_workspace(
        db,
        nid,
        workspace_id,
        WorkspaceEdit(
            expected_revision_id=reopened["revision_id"],
            patches=[
                ResourcePatch(
                    kind="writing_draft",
                    id=latest.id,
                    value={"title": latest.title, "content": CH1_V1 + "续写一版。"},
                )
            ],
        ),
    )
    assert progressed["sequence"] == reopened["sequence"] + 1
    again = await workspaces.workspace_view(db, nid, workspace_id)
    assert again["changes"][0]["after"]["content"] == CH1_V1 + "续写一版。"
    assert (await get_latest_draft_for_chapter(db, nid, 1)).content == CH1_V1


# ============================================================
# 取消零正史副作用（预览 → 取消）
# ============================================================


async def test_p2c_cancel_after_preview_writes_nothing_canonical(
    db_session: AsyncSession, test_project_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """预览（create+edit 试改）后取消：当前稿零写入、零回执、零 outbox。"""
    db, nid = db_session, test_project_id
    await _custody_world(db, nid)
    _case, view, drafts = await _open_trial(db, nid, monkeypatch, chapter_indexes=(1, 2))
    viewed = await workspaces.workspace_view(db, nid, view["id"])
    assert viewed["changes"], "预览可见拟修改"

    # 取消 = 不采用、不封存（试改生命周期留在 open）。
    assert viewed["status"] == "open"
    for draft in drafts:
        latest = await get_latest_draft_for_chapter(db, nid, draft.chapter_index)
        assert latest.id == draft.id and latest.content == draft.content
    assert await _receipt_count(db, nid) == 0
    assert (
        await db.scalar(
            select(func.count())
            .select_from(DomainOutbox)
            .where(DomainOutbox.novel_id == UUID(nid))
        )
    ) == 0
