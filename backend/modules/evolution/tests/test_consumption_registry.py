"""P2-C C1 消费登记契约测试（结构校验/纯函数/影响计算对拍/旧数据兼容）。

文件名刻意避开 C0 夹具的 ``p2c_`` 前缀（并行约定：C0 钉端到端形态，
本文件钉契约与纯函数；C2 追加"登记写入 → 失效 → 精确列表"端到端）。

对拍口径（与 ``invalidation.apply_source_invalidation`` 的保守行为）：

1. 无登记：评估的 ``from_scene_index`` == 真实回执的
   ``earliest_affected_scene_index``，且真实库中从该 Scene（含）起全部
   checkpoint 被软失效、之前的保持 current——评估窗口与现状完全一致。
2. 有登记：评估输出是保守行为的细化（受影响集合 ⊆ 现状失效集合），
   登记区间与变更窗口不相交可判无关（零无关重生成的证明材料），
   覆盖不到的窗口显式进 ``unknown_scope``，不隐藏。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.consumption import (
    CONSUMER_LABELS,
    CONSUMPTION_REGISTRY_STATE_KEY,
    RECOMPUTE_SCOPE_EFFECTS,
    AssetDigest,
    BasisAnchor,
    ChapterConsumption,
    ConsumerImpact,
    ConsumerKind,
    ConsumerRef,
    ConsumerVerdict,
    ConsumptionRecord,
    ImpactReason,
    OffsetRange,
    RecomputeRequest,
    RecomputeScope,
    RecomputeTargetRef,
    SourceBinding,
    UnknownScope,
    assess_source_impact,
    build_recompute_preview,
    derive_recompute_options,
    read_consumption_records,
    receipt_fingerprint,
    receipt_public_view,
    recompute_request_hash,
)
from modules.evolution.impact import (
    ANCHORED_SCENE_IMPLICIT_METHOD_VERSION,
    anchored_registrations,
    receipt_view,
)
from modules.evolution.invalidation import (
    UNSUPPORTED_CONSUMERS,
    InvalidationReceipt,
    SourceChange,
    apply_source_invalidation,
    compute_source_change,
)
from modules.evolution.registration import (
    register_consumption,
    scene_checkpoint_registration,
)
from modules.story.continuity.models import MemorySceneCheckpoint
from modules.story.outline_state.models import Scene
from modules.writing.facade import create_draft_only
from modules.writing.models import WritingDraft

# ---------------------------------------------------------------------------
# 构造 helper
# ---------------------------------------------------------------------------


def _chapter(
    chapter_index: int, ranges: tuple[OffsetRange, ...] = ()
) -> ChapterConsumption:
    return ChapterConsumption(
        chapter_index=chapter_index,
        draft_id=f"draft-{chapter_index}",
        version_number=1,
        source_hash=f"hash-{chapter_index}",
        ranges=ranges,
    )


def _record(
    novel_id: str,
    *,
    kind: ConsumerKind = ConsumerKind.story_scene_checkpoint,
    scene_index: int | None = 0,
    chapter_index: int = 2,
    ranges: tuple[OffsetRange, ...] = (),
    content_mode: str = "working",
) -> ConsumptionRecord:
    if kind is ConsumerKind.evidence_chapter_index:
        consumer = ConsumerRef(
            kind=kind,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
    else:
        consumer = ConsumerRef(
            kind=kind,
            scene_id=f"scene-{scene_index}",
            scene_index=scene_index,
            dimension="entities",
        )
    return ConsumptionRecord(
        novel_id=novel_id,
        consumer=consumer,
        binding=SourceBinding(
            content_mode=content_mode,  # type: ignore[arg-type]
            chapters=(_chapter(chapter_index, ranges),),
        ),
        basis=BasisAnchor(anchor_kind="scene_checkpoint", ref_id=f"ckpt-{scene_index}")
        if kind is ConsumerKind.story_scene_checkpoint
        else None,
        selected_assets=(
            AssetDigest(asset_kind="writing_draft", asset_id=f"draft-{chapter_index}"),
        ),
        excluded_assets=(),
        method_version="scene-projection-v1",
        registered_at=datetime(2026, 10, 7, tzinfo=UTC),
    )


def _changed_at_tail(total: int = 1000) -> tuple[str, str]:
    old = "山" * (total - 12) + "青竹取出铜钥匙，递给林舟。"
    new = old.replace("铜钥匙", "铁哨子")
    return old, new


# ---------------------------------------------------------------------------
# 结构校验
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "missing"),
    [
        (ConsumerKind.story_scene_checkpoint, ("dimension",)),
        (ConsumerKind.evidence_chapter_index, ("chapter_index", "content_mode")),
        (ConsumerKind.scene_lens, ("scene_id",)),
    ],
)
def test_consumer_ref_requires_locator_keys(
    kind: ConsumerKind, missing: tuple[str, ...]
) -> None:
    payload = {"kind": kind}
    if kind is ConsumerKind.evidence_chapter_index:
        payload["chapter_index"] = 3
        payload["content_mode"] = "working"
    else:
        payload["scene_id"] = "scene-1"
        payload["scene_index"] = 1
        payload["dimension"] = "entities"
    for key in missing:
        payload.pop(key)
    with pytest.raises(ValidationError, match="requires"):
        ConsumerRef.model_validate(payload)


def test_source_binding_rejects_duplicate_and_empty_chapters() -> None:
    with pytest.raises(ValidationError):
        SourceBinding(
            content_mode="working",
            chapters=(_chapter(1), _chapter(1)),
        )
    with pytest.raises(ValidationError):
        SourceBinding(content_mode="working", chapters=())


def test_offset_range_requires_end_ge_start() -> None:
    with pytest.raises(ValidationError):
        OffsetRange(start_offset=10, end_offset=5)


def test_consumption_record_is_frozen_and_json_roundtrip() -> None:
    record = _record("novel-1", scene_index=3, chapter_index=2)
    with pytest.raises(ValidationError):
        record.method_version = "another"  # type: ignore[misc]
    restored = ConsumptionRecord.model_validate(json.loads(record.model_dump_json()))
    assert restored == record


def test_read_consumption_records_legacy_payload_returns_empty() -> None:
    # 旧格式（无键）/非 dict 载荷：[] 不报错、不冒充覆盖（保守由调用方保留）。
    assert read_consumption_records(None) == []
    assert read_consumption_records({"state": {"entities": []}}) == []
    assert read_consumption_records([]) == []


def test_read_consumption_records_roundtrip_and_corruption_raises() -> None:
    records = [_record("novel-1"), _record("novel-1", scene_index=1)]
    payload = {
        CONSUMPTION_REGISTRY_STATE_KEY: [
            json.loads(record.model_dump_json()) for record in records
        ]
    }
    assert read_consumption_records(payload) == records
    corrupted = {CONSUMPTION_REGISTRY_STATE_KEY: [{"novel_id": "novel-1"}]}
    with pytest.raises(ValidationError):
        read_consumption_records(corrupted)


# ---------------------------------------------------------------------------
# 影响计算纯函数
# ---------------------------------------------------------------------------


def test_assess_no_change_is_noop() -> None:
    change = compute_source_change("舟", "舟")
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        earliest_affected_scene_index=1,
        scene_indexes=[0, 1],
    )
    assert assessment.nothing_to_do is True
    assert assessment.verdicts == ()
    assert assessment.from_scene_index is None
    assert assessment.refined is False


def test_assess_without_registration_keeps_conservative_window() -> None:
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        earliest_affected_scene_index=1,
        scene_indexes=[0, 1, 2],
    )
    # 无登记：行为与现状保守扩大完全一致，不细化。
    assert assessment.from_scene_index == 1
    assert assessment.conservative_from_scene_index == 1
    assert assessment.refined is False
    assert assessment.unknown_scope.chapter_registration_missing is True
    assert assessment.unknown_scope.scenes_without_registration == (1, 2)
    assert assessment.unknown_scope.unregistered_consumers == tuple(
        item["consumer"] for item in UNSUPPORTED_CONSUMERS
    )
    assert assessment.unknown_scope.conservative is True


def test_assess_scene_roster_unavailable_stays_conservative() -> None:
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    # 调用方未提供场景清单：即使变更章有登记，也无法证明后续场景覆盖。
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        records=[_record("novel-1", scene_index=1)],
        earliest_affected_scene_index=1,
        scene_indexes=None,
    )
    assert assessment.from_scene_index == 1
    assert assessment.unknown_scope.scene_roster_unavailable is True
    assert assessment.refined is False


def test_assess_full_chapter_binding_marks_affected() -> None:
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        records=[_record("novel-1", scene_index=1)],
        earliest_affected_scene_index=1,
        scene_indexes=[0, 1],
    )
    verdict = assessment.affected()[0]
    assert verdict.impact is ConsumerImpact.affected
    assert verdict.reason is ImpactReason.anchored_chapter_edited
    assert assessment.from_scene_index == 1
    assert assessment.refined is True
    # Scene 0/1 中仅 1 在保守窗口内且已登记：无 unknown 场景。
    assert assessment.unknown_scope.conservative is False


def test_assess_offset_window_miss_marks_unaffected_and_zero_projection() -> None:
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    assert change.first_offset is not None and change.first_offset >= 900
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        records=[
            # Scene 1 只消费章 2 的开头区间，与尾部变更窗口不相交。
            _record(
                "novel-1",
                scene_index=1,
                ranges=(OffsetRange(start_offset=0, end_offset=100),),
            ),
        ],
        earliest_affected_scene_index=1,
        scene_indexes=[0, 1],
    )
    assert assessment.verdicts[0].impact is ConsumerImpact.unaffected
    assert assessment.verdicts[0].reason is ImpactReason.offset_window_miss
    # 变更章已有登记（chapter_registration_missing 只看变更章本身）；
    # evidence 章索引是确定性消费者，由失效引擎无条件重建，不依赖登记。
    assert assessment.unknown_scope.chapter_registration_missing is False
    # 全部登记证明无关：零投影失效（零无关重生成的证明材料）。
    assert assessment.affected() == ()
    assert assessment.from_scene_index is None
    assert assessment.refined is True


def test_assess_offset_window_hit_marks_affected() -> None:
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    assert change.first_offset is not None
    hit_range = OffsetRange(
        start_offset=change.first_offset - 5, end_offset=change.first_offset + 5
    )
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        records=[_record("novel-1", scene_index=2, ranges=(hit_range,))],
        earliest_affected_scene_index=2,
        scene_indexes=[0, 1, 2],
    )
    verdict = assessment.affected()[0]
    assert verdict.reason is ImpactReason.offset_window_hit
    assert assessment.from_scene_index == 2


def test_assess_adjacent_range_is_not_overlap() -> None:
    # 相邻区间（end == 变更窗口 start）不算相交——细化判定的边界。
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    assert change.first_offset is not None
    adjacent = OffsetRange(start_offset=0, end_offset=change.first_offset)
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        records=[_record("novel-1", scene_index=1, ranges=(adjacent,))],
        earliest_affected_scene_index=1,
        scene_indexes=[0, 1],
    )
    assert assessment.verdicts[0].reason is ImpactReason.offset_window_miss


def test_assess_change_without_offsets_is_conservative() -> None:
    # changed=True 但未携带偏移窗口（手工构造）：按整章消费保守命中。
    change = SourceChange(changed=True, same_length=False, old_length=10, new_length=12)
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        records=[
            _record(
                "novel-1",
                scene_index=1,
                ranges=(OffsetRange(start_offset=0, end_offset=100),),
            )
        ],
        earliest_affected_scene_index=1,
        scene_indexes=[0, 1],
    )
    verdict = assessment.affected()[0]
    assert verdict.reason is ImpactReason.anchored_chapter_edited


def test_assess_content_mode_mismatch_marks_unaffected() -> None:
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        content_mode="working",
        records=[_record("novel-1", scene_index=1, content_mode="canonical")],
        earliest_affected_scene_index=1,
        scene_indexes=[0, 1],
    )
    verdict = assessment.verdicts[0]
    assert verdict.impact is ConsumerImpact.unaffected
    assert verdict.reason is ImpactReason.content_mode_mismatch


def test_assess_ignores_cross_novel_records() -> None:
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        records=[_record("novel-other", scene_index=1)],
        earliest_affected_scene_index=1,
        scene_indexes=[0, 1],
    )
    assert assessment.verdicts == ()
    assert assessment.unknown_scope.chapter_registration_missing is True
    assert assessment.from_scene_index == 1


def test_assess_partial_scene_registration_keeps_conservative() -> None:
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        records=[_record("novel-1", scene_index=1)],
        earliest_affected_scene_index=1,
        scene_indexes=[0, 1, 2, 3],
    )
    # Scene 2/3 无登记：显式 unknown，窗口不收窄。
    assert assessment.unknown_scope.scenes_without_registration == (2, 3)
    assert assessment.from_scene_index == 1
    assert assessment.refined is False


def test_assess_cross_chapter_scene_can_precede_conservative_anchor() -> None:
    # 跨章 Scene（Scene 0 同时消费章 1 与章 2）早于保守锚：登记命中的
    # 失效起点取更早者（登记修复保守扩大漏掉的跨章前缀）。
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    cross_scene_record = ConsumptionRecord(
        novel_id="novel-1",
        consumer=ConsumerRef(
            kind=ConsumerKind.story_scene_checkpoint,
            scene_id="scene-0",
            scene_index=0,
            dimension="entities",
        ),
        binding=SourceBinding(
            content_mode="working",
            chapters=(_chapter(1), _chapter(2)),
        ),
        method_version="scene-projection-v1",
        registered_at=datetime(2026, 10, 7, tzinfo=UTC),
    )
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        records=[cross_scene_record, _record("novel-1", scene_index=5)],
        earliest_affected_scene_index=5,
        scene_indexes=[0, 5],
    )
    assert assessment.from_scene_index == 0


def test_unsupported_consumers_are_always_listed_but_do_not_block_refinement() -> None:
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        records=[_record("novel-1", scene_index=1)],
        earliest_affected_scene_index=1,
        scene_indexes=[0, 1],
    )
    # P2-C 范围限定：world_knowledge/map_atlas 留在 UNSUPPORTED_CONSUMERS
    # 恒列出（缺口可见，对拍 invalidation.UNSUPPORTED_CONSUMERS，不扩），
    # 但它们对齐现状回执 unsupported_consumers 的角色：只展示、不参与
    # 投影窗口判定——登记覆盖完整时细化照常发生。
    assert assessment.unknown_scope.unregistered_consumers == (
        "world_knowledge",
        "map_atlas",
    )
    assert assessment.unknown_scope.conservative is False
    assert assessment.refined is True


# ---------------------------------------------------------------------------
# 与 apply_source_invalidation 的真库对拍（无登记行为不变 / 有登记仅细化）
# ---------------------------------------------------------------------------


async def _scene(
    db: AsyncSession, novel_id: str, scene_index: int, chapter_index: int
) -> Scene:
    item = Scene(
        novel_id=uuid.UUID(novel_id),
        scene_index=scene_index,
        title=f"Scene {scene_index}",
        chapter_ids=[chapter_index],
        scene_chunks=[{"chapter_index": chapter_index}],
        status="draft",
    )
    db.add(item)
    await db.flush()
    return item


async def _prepare_projections(db: AsyncSession, novel_id: str, scene: Scene) -> None:
    from modules.story.continuity.scene_projection import SceneMemoryProjectionService

    await SceneMemoryProjectionService().ensure_scene(db, novel_id, str(scene.id))


async def _current_scene_indexes(db: AsyncSession, novel_id: str) -> set[int]:
    rows = await db.execute(
        select(MemorySceneCheckpoint.scene_index).where(
            MemorySceneCheckpoint.novel_id == uuid.UUID(novel_id),
            MemorySceneCheckpoint.is_current.is_(True),
        )
    )
    return {int(row[0]) for row in rows.all()}


async def test_no_registration_assessment_matches_real_invalidation_receipt(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """无登记：评估窗口与真实失效传播完全一致（行为不变的对拍）。"""
    db, nid = db_session, evolution_project_id
    chapter1_old = "山" * 200 + "第一章结尾。"
    chapter2_old = "水" * 200 + "第二章：青竹取出铜钥匙，递给林舟。"
    await create_draft_only(db, nid, 1, "第一章", chapter1_old)
    await create_draft_only(db, nid, 2, "第二章", chapter2_old)
    scene0 = await _scene(db, nid, 0, 1)
    scene1 = await _scene(db, nid, 1, 2)
    await _prepare_projections(db, nid, scene0)
    await _prepare_projections(db, nid, scene1)

    chapter2_new = chapter2_old.replace("铜钥匙", "铁哨子")
    change = compute_source_change(chapter2_old, chapter2_new)
    await create_draft_only(db, nid, 2, "第二章", chapter2_new)
    receipt = await apply_source_invalidation(
        db, nid, chapter_index=2, change=change, content_mode="working"
    )

    # 现状保守行为：锚定章 2 的最早 Scene（=1，含）起全部投影失效。
    assert receipt.earliest_affected_scene_index == 1
    assert await _current_scene_indexes(db, nid) == {0}

    assessment = assess_source_impact(
        novel_id=nid,
        chapter_index=2,
        change=change,
        records=[],
        earliest_affected_scene_index=receipt.earliest_affected_scene_index,
        scene_indexes=[0, 1],
    )
    assert assessment.from_scene_index == receipt.earliest_affected_scene_index
    assert assessment.refined is False
    assert assessment.unknown_scope.scenes_without_registration == (1,)
    # 评估窗口（从 1 起）与库中实际失效范围（Scene 1 失效、Scene 0 保留）一致。
    assert {index for index in (0, 1) if index >= (assessment.from_scene_index or 0)} == {
        1
    }


async def test_registration_refines_real_conservative_window(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """有登记：评估是保守行为的细化（受影响集合 ⊆ 现状失效集合）。"""
    db, nid = db_session, evolution_project_id
    chapter1_old = "山" * 200 + "第一章结尾。"
    # 变更发生在章 2 开头；Scene 1 只登记消费章 2 的后半区间。
    chapter2_old = "青竹取出铜钥匙。" + "水" * 300
    await create_draft_only(db, nid, 1, "第一章", chapter1_old)
    await create_draft_only(db, nid, 2, "第二章", chapter2_old)
    scene0 = await _scene(db, nid, 0, 1)
    scene1 = await _scene(db, nid, 1, 2)
    await _prepare_projections(db, nid, scene0)
    await _prepare_projections(db, nid, scene1)

    chapter2_new = chapter2_old.replace("青竹", "白霜")
    change = compute_source_change(chapter2_old, chapter2_new)
    assert change.first_offset == 0
    registration = _record(
        nid,
        scene_index=1,
        chapter_index=2,
        ranges=(OffsetRange(start_offset=100, end_offset=300),),
    )

    await create_draft_only(db, nid, 2, "第二章", chapter2_new)
    receipt = await apply_source_invalidation(
        db, nid, chapter_index=2, change=change, content_mode="working"
    )
    # 现状（无登记可用）：保守失效 Scene 1。
    assert receipt.earliest_affected_scene_index == 1
    assert await _current_scene_indexes(db, nid) == {0}

    assessment = assess_source_impact(
        novel_id=nid,
        chapter_index=2,
        change=change,
        records=[registration],
        earliest_affected_scene_index=receipt.earliest_affected_scene_index,
        scene_indexes=[0, 1],
    )
    # 细化：登记证明 Scene 1 的消费区间与变更窗口不相交——评估的失效集合
    # （空）是现状失效集合（{1}）的子集；unknown 不存在（覆盖完整）。
    assert assessment.verdicts[0].reason is ImpactReason.offset_window_miss
    assert assessment.affected() == ()
    assert assessment.from_scene_index is None
    assert assessment.refined is True
    assert assessment.unknown_scope.conservative is False


# ---------------------------------------------------------------------------
# 回执透传投影
# ---------------------------------------------------------------------------


def _receipt(**overrides) -> InvalidationReceipt:
    payload: dict = {
        "novel_id": "novel-1",
        "chapter_index": 2,
        "source_change": compute_source_change(*_changed_at_tail()),
        "invalidated_consumers": {
            "evidence_chapter_index": {"requested_hash": "abc"},
            "story_state": {"superseded_rows": 3},
            "interaction_source_cache": {"purged_rows": 2},
            "internal_future_consumer": {"x": 1},
        },
        "unsupported_consumers": [dict(item) for item in UNSUPPORTED_CONSUMERS],
        "earliest_affected_scene_index": 1,
        "coverage_note": "保守扩大：……",
    }
    payload.update(overrides)
    return InvalidationReceipt.model_validate(payload)


def test_receipt_public_view_author_language_fields() -> None:
    view = receipt_public_view(_receipt())
    assert view["changed"] is True
    assert view["nothing_to_do"] is False
    # C0 目标形态最小键集（writing 契约 invalidation 字段的键级基准）。
    assert {"affected", "unknown_scope", "receipt_id"} <= set(view)
    assert view["unknown_scope"] is True  # 无 assessment 时 earliest 非 None → 保守
    assert view["receipt_id"]
    # 无 assessment：affected 退化为回执确定性键（辅助清理动作不进列表）。
    consumers = {item["consumer"] for item in view["affected"]}
    assert "evidence_chapter_index" in consumers
    assert "interaction_source_cache" not in consumers
    labels = {item["consumer"]: item["label"] for item in view["invalidated"]}
    assert labels["evidence_chapter_index"] == CONSUMER_LABELS["evidence_chapter_index"]
    assert labels["story_state"] == CONSUMER_LABELS["story_state"]
    # 未知内部键：不冒充翻译，回退原键并记入诊断区。
    assert labels["internal_future_consumer"] == "internal_future_consumer"
    assert view["diagnostics"]["untranslated_consumers"] == ["internal_future_consumer"]
    assert view["diagnostics"]["earliest_affected_scene_index"] == 1
    assert view["diagnostics"]["source_change"]["changed"] is True
    assert {item["consumer"] for item in view["unsupported"]} == {
        "world_knowledge",
        "map_atlas",
    }
    assert view["coverage_note"]
    # 视图必须可直接进 JSON 响应。
    json.dumps(view, ensure_ascii=False)


def test_receipt_fingerprint_is_stable_and_content_sensitive() -> None:
    first = receipt_fingerprint(_receipt())
    # 同一回执内容（重放）指纹不变。
    assert receipt_fingerprint(_receipt()) == first
    # 任何关键字段变化换指纹。
    assert receipt_fingerprint(_receipt(chapter_index=3)) != first
    assert receipt_fingerprint(_receipt(coverage_note="别的说明")) != first
    assert receipt_fingerprint(_receipt(earliest_affected_scene_index=None)) != first


def test_receipt_view_with_assessment_carries_c0_shape() -> None:
    """带 assessment 的视图：affected 含 known 判定 + unknown 保守条目，
    无关 Scene（offset_window_miss）不进列表——C0 目标形态键名级对拍。"""
    old, new = _changed_at_tail()
    change = compute_source_change(old, new)
    assessment = assess_source_impact(
        novel_id="novel-1",
        chapter_index=2,
        change=change,
        records=[
            _record("novel-1", scene_index=1),
            _record(
                "novel-1", scene_index=0, chapter_index=1, ranges=()
            ),  # 锚章 1：与变更章无关，不进 affected
        ],
        earliest_affected_scene_index=1,
        scene_indexes=[0, 1, 2],
    )
    view = receipt_public_view(
        _receipt(invalidated_consumers={"evidence_chapter_index": {}}),
        assessment=assessment,
    )
    entries = {item["scene_index"]: item for item in view["affected"]}
    # known：Scene 1 登记命中（anchored_chapter_edited）。
    assert entries[1]["basis"] == "known"
    assert entries[1]["reason"] == "anchored_chapter_edited"
    assert entries[1]["consumer"] == "story_scene_checkpoint"
    assert entries[1]["scene_id"] == "scene-1"
    # unknown：Scene 2 无登记，保守扩大条目显式标注、不隐藏。
    assert entries[2]["basis"] == "unknown"
    assert entries[2]["reason"] == "conservative_expansion_unregistered"
    # 无关 Scene 0（登记绑定章 1，不消费变更章）不在列表。
    assert 0 not in entries
    assert view["unknown_scope"] is True  # Scene 2 未登记 → 保守
    # rebuild 选项的 affected 含 known+unknown scene 条目、不含无关 Scene。
    rebuild = next(
        item
        for item in view["recompute_options"]
        if item["kind"] == "rebuild_derived_state"
    )
    assert {item["scene_index"] for item in rebuild["affected"]} == {1, 2}


def test_derive_recompute_options_classify_three_cost_tiers() -> None:
    options = derive_recompute_options(_receipt())
    # C0 目标形态：有失效时恒列三类（成本分级展示），regenerate 标注
    # 仅作者显式选择——不在编辑时自动执行。
    assert [item["kind"] for item in options] == [
        "reload_evidence",
        "rebuild_derived_state",
        "regenerate_prose",
    ]
    reload_opt = next(item for item in options if item["kind"] == "reload_evidence")
    assert "evidence_chapter_index" in reload_opt["covers"]
    regenerate = next(item for item in options if item["kind"] == "regenerate_prose")
    assert regenerate["author_choice_only"] is True
    # nothing_to_do：无失效即无选项。
    noop = _receipt(
        invalidated_consumers={},
        source_change=None,
        nothing_to_do=True,
    )
    assert derive_recompute_options(noop) == []


def test_receipt_public_view_nothing_to_do_has_no_options() -> None:
    view = receipt_public_view(
        _receipt(invalidated_consumers={}, nothing_to_do=True, source_change=None)
    )
    assert view["nothing_to_do"] is True
    assert view["recompute_options"] == []
    assert view["changed"] is False


# ---------------------------------------------------------------------------
# 重算三分类
# ---------------------------------------------------------------------------


def test_recompute_scope_effects_cover_all_scopes() -> None:
    assert set(RECOMPUTE_SCOPE_EFFECTS) == {scope.value for scope in RecomputeScope}
    for effects in RECOMPUTE_SCOPE_EFFECTS.values():
        assert effects["cost"] and effects["write_effect"]


def test_recompute_target_requires_anchor() -> None:
    with pytest.raises(ValidationError):
        RecomputeTargetRef()
    assert RecomputeTargetRef(chapter_index=2).chapter_index == 2


def test_recompute_request_validation() -> None:
    base = dict(
        novel_id="novel-1",
        operation_id="op-1",
        scope=RecomputeScope.rebuild_derived_state,
        targets=(RecomputeTargetRef(scene_index=1),),
    )
    # 预览缺省合法；执行必须确认。
    assert RecomputeRequest.model_validate(base).mode == "preview"
    with pytest.raises(ValidationError, match="confirmation"):
        RecomputeRequest.model_validate({**base, "mode": "execute"})
    assert (
        RecomputeRequest.model_validate(
            {**base, "mode": "execute", "confirmed": True}
        ).confirmed
        is True
    )
    # 重生成正文必须锚定章。
    with pytest.raises(ValidationError, match="chapter"):
        RecomputeRequest.model_validate(
            {
                **base,
                "scope": RecomputeScope.regenerate_prose,
                "targets": (RecomputeTargetRef(scene_index=1),),
                "mode": "execute",
                "confirmed": True,
            }
        )
    assert (
        RecomputeRequest.model_validate(
            {
                **base,
                "scope": RecomputeScope.regenerate_prose,
                "targets": (RecomputeTargetRef(chapter_index=2),),
                "mode": "execute",
                "confirmed": True,
            }
        ).scope
        is RecomputeScope.regenerate_prose
    )
    # 目标不可为空。
    with pytest.raises(ValidationError):
        RecomputeRequest.model_validate({**base, "targets": ()})


def test_recompute_request_hash_is_stable_and_payload_sensitive() -> None:
    base = dict(
        novel_id="novel-1",
        operation_id="op-1",
        scope=RecomputeScope.reload_evidence,
        targets=(RecomputeTargetRef(chapter_index=2),),
    )
    first = recompute_request_hash(RecomputeRequest.model_validate(base))
    # 同内容（含 mode/confirmed 差异——预览与执行视为同一操作）同指纹。
    second = recompute_request_hash(
        RecomputeRequest.model_validate({**base, "mode": "execute", "confirmed": True})
    )
    assert first == second
    # 任何实质字段变化换指纹（幂等第二键，沿 merge operation_id+request_hash 口径）。
    changed_target = recompute_request_hash(
        RecomputeRequest.model_validate(
            {**base, "targets": (RecomputeTargetRef(chapter_index=3),)}
        )
    )
    assert changed_target != first
    changed_baseline = recompute_request_hash(
        RecomputeRequest.model_validate({**base, "baseline_receipt_digest": "d" * 64})
    )
    assert changed_baseline != first
    changed_scope = recompute_request_hash(
        RecomputeRequest.model_validate(
            {**base, "scope": RecomputeScope.rebuild_derived_state}
        )
    )
    assert changed_scope != first


def test_build_recompute_preview_never_claims_domain_write() -> None:
    request = RecomputeRequest.model_validate(
        dict(
            novel_id="novel-1",
            operation_id="op-1",
            scope=RecomputeScope.rebuild_derived_state,
            targets=(RecomputeTargetRef(scene_index=1),),
        )
    )
    verdict = ConsumerVerdict(
        consumer=_record("novel-1").consumer,
        impact=ConsumerImpact.affected,
        reason=ImpactReason.anchored_chapter_edited,
        note="该消费读取变更章节的整章内容",
    )
    preview = build_recompute_preview(request, affected_consumers=[verdict])
    assert preview.domain_write_performed is False
    assert preview.cost == RECOMPUTE_SCOPE_EFFECTS[request.scope.value]["cost"]
    assert (
        preview.write_effect
        == RECOMPUTE_SCOPE_EFFECTS[request.scope.value]["write_effect"]
    )
    assert preview.request_hash == recompute_request_hash(request)
    assert list(preview.affected_consumers) == [verdict]


def test_unknown_scope_conservative_property() -> None:
    empty = UnknownScope(note="登记覆盖完整")
    assert empty.conservative is False
    # unregistered_consumers（UNSUPPORTED 列表）是缺口可见性，
    # 不参与投影窗口判定（对齐现状 unsupported_consumers 只展示的角色）。
    listed_only = UnknownScope(note="x", unregistered_consumers=("world_knowledge",))
    assert listed_only.conservative is False
    for field in (
        {"chapter_registration_missing": True},
        {"scenes_without_registration": (2,)},
        {"scene_roster_unavailable": True},
    ):
        assert UnknownScope(note="x", **field).conservative is True


# ---------------------------------------------------------------------------
# C2 登记写入端（构建 + 幂等合并）
# ---------------------------------------------------------------------------


def test_register_consumption_replaces_same_consumer_and_appends_new() -> None:
    state: dict = {}
    first = _record("novel-1", scene_index=1)
    register_consumption(state, first)
    assert read_consumption_records(state) == [first]
    # 同 (novel, consumer) 重登记（方法升级）→ 替换，不堆积历史版本。
    upgraded = first.model_copy(update={"method_version": "scene-projection-v2"})
    register_consumption(state, upgraded)
    assert read_consumption_records(state) == [upgraded]
    # 跨场景登记 → 追加。
    other = _record("novel-1", scene_index=2)
    register_consumption(state, other)
    assert read_consumption_records(state) == [upgraded, other]
    # 写入形态即 JSON 列可存形态（roundtrip 不丢）。
    assert read_consumption_records(json.loads(json.dumps(state))) == [
        upgraded,
        other,
    ]


def test_scene_checkpoint_registration_builds_binding_and_basis() -> None:
    record = scene_checkpoint_registration(
        "novel-1",
        scene_id="scene-1",
        scene_index=1,
        dimension="entities",
        chapters=[
            {
                "chapter_index": 1,
                "draft_id": "draft-1",
                "version_number": 2,
                "source_hash": "hash-1",
            },
            {"chapter_index": 2, "ranges": [(0, 100)]},
        ],
        method_version="scene-projection-v1",
        checkpoint_id="ckpt-1",
    )
    assert record.consumer.kind is ConsumerKind.story_scene_checkpoint
    assert record.novel_id == "novel-1"
    binding = record.binding
    assert binding.content_mode == "working"
    first = binding.chapter(1)
    assert first is not None and first.draft_id == "draft-1" and first.ranges == ()
    second = binding.chapter(2)
    assert (
        second is not None
        and second.ranges == (OffsetRange(start_offset=0, end_offset=100),)
        and second.draft_id is None
    )
    assert (
        record.basis is not None
        and record.basis.anchor_kind == "scene_checkpoint"
        and record.basis.ref_id == "ckpt-1"
    )


def test_anchored_registrations_prioritize_real_records() -> None:
    scenes = [
        {
            "id": "scene-1",
            "scene_index": 1,
            "chapter_ids": [2],
            "scene_chunks": [{"chapter_index": 2}],
        },
        {
            "id": "scene-9",
            "scene_index": 9,
            "chapter_ids": [3],
            "scene_chunks": [{"chapter_index": 3}],
        },
    ]
    # scene-1 的 entities 维度已有真实登记（scene_projection 接线后形态）。
    real = [_record("novel-1", scene_index=1, chapter_index=2)]
    synthesized = anchored_registrations(
        "novel-1", chapter_index=2, scenes=scenes, real_records=real
    )
    dimensions = {item.consumer.dimension for item in synthesized}
    # 真实登记的 (scene, dimension) 不合成；其余维度按整章消费合成。
    assert "entities" not in dimensions
    assert dimensions  # 其余维度补齐
    # 非锚定场景（scene-9 锚 ch3）不合成；合成来源可识别。
    assert all(item.consumer.scene_id == "scene-1" for item in synthesized)
    assert all(
        item.method_version == ANCHORED_SCENE_IMPLICIT_METHOD_VERSION
        for item in synthesized
    )
    anchored = synthesized[0].binding.chapter(2)
    assert anchored is not None and anchored.ranges == ()  # 整章消费（保守）


# ---------------------------------------------------------------------------
# C2 端到端：登记写入 → 失效 → 精确受影响列表（SQLite 合成库）
# ---------------------------------------------------------------------------


async def _working_draft_row(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    content: str,
    version_number: int = 1,
) -> None:
    """直落 working 稿行（绕过改稿钩子；登记场景须避免钩子先 supersede
    带登记的 current 行——失效由演化缝单次显式触发，沿 C0 夹具惯例）。"""
    db.add(
        WritingDraft(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(novel_id),
            chapter_index=chapter_index,
            title=f"第{chapter_index}章",
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            version_number=version_number,
            status="draft",
        )
    )
    await db.flush()


async def _register_on_current_checkpoints(
    db: AsyncSession,
    novel_id: str,
    scene: Scene,
    chapters: list[dict],
) -> None:
    """把登记写进该 Scene 全部 current checkpoint 行（B 类接线后的数据
    形态：每维度行登记该维度的消费）。"""
    rows = await db.execute(
        select(MemorySceneCheckpoint).where(
            MemorySceneCheckpoint.novel_id == uuid.UUID(novel_id),
            MemorySceneCheckpoint.scene_id == scene.id,
            MemorySceneCheckpoint.is_current.is_(True),
        )
    )
    for row in rows.scalars():
        state = dict(row.state_json or {})
        register_consumption(
            state,
            scene_checkpoint_registration(
                novel_id,
                scene_id=str(scene.id),
                scene_index=int(scene.scene_index),
                dimension=row.dimension,
                chapters=chapters,
                method_version="scene-projection-v1",
                checkpoint_id=str(row.id),
            ),
        )
        row.state_json = state
    await db.flush()


def _scene_entries_by_index(receipt: InvalidationReceipt) -> dict[int, dict]:
    return {
        item["scene_index"]: item
        for item in receipt.affected
        if item.get("scene_index") is not None
    }


async def test_registered_consumption_refines_real_invalidation_end_to_end(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """登记→失效→精确归因列表（细化端到端）。

    s1 登记消费 ch2 整章（命中）、s2 登记只消费 ch2 开头区间（与尾部
    变更不相交）：s2 与变更无关——不进受影响/重算列表（零无关重算的
    库级证明）。物理失效仍是窗口语义（story supersede 自起点起全失效、
    按集合收窄归 B 类接线）：窗口 = 最早命中 Scene 起，与现状一致。
    全部登记无关时窗口收窄到零（见下一个用例）。
    """
    db, nid = db_session, evolution_project_id
    chapter1 = "山" * 200 + "第一章结尾。"
    chapter2_old = "水" * 300 + "第二章：青竹取出铜钥匙，递给林舟。"
    chapter3 = "木" * 200 + "第三章。"
    await _working_draft_row(db, nid, 1, chapter1)
    await _working_draft_row(db, nid, 2, chapter2_old)
    await _working_draft_row(db, nid, 3, chapter3)
    scene0 = await _scene(db, nid, 0, 1)
    scene1 = await _scene(db, nid, 1, 2)
    scene2 = await _scene(db, nid, 2, 3)
    await _prepare_projections(db, nid, scene0)
    await _prepare_projections(db, nid, scene1)
    await _prepare_projections(db, nid, scene2)
    # 登记写入（接线后由 scene_projection 落；此处按其数据形态直写）：
    # s1 消费 ch1+ch2 整章；s2 消费 ch1/ch3 整章 + ch2 仅开头区间。
    await _register_on_current_checkpoints(
        db,
        nid,
        scene1,
        chapters=[
            {"chapter_index": 1},
            {"chapter_index": 2},
        ],
    )
    await _register_on_current_checkpoints(
        db,
        nid,
        scene2,
        chapters=[
            {"chapter_index": 1},
            {"chapter_index": 2, "ranges": [(0, 100)]},
            {"chapter_index": 3},
        ],
    )

    chapter2_new = chapter2_old.replace("铜钥匙", "铁哨子")
    change = compute_source_change(chapter2_old, chapter2_new)
    assert change.first_offset is not None and change.first_offset >= 300
    await _working_draft_row(db, nid, 2, chapter2_new, version_number=2)
    receipt = await apply_source_invalidation(
        db, nid, chapter_index=2, change=change, content_mode="working"
    )

    # 现状锚定事实仍在回执上（既有语义不回归）。
    assert receipt.earliest_affected_scene_index == 1
    # 物理失效窗口 = 最早命中 Scene 起（窗口语义，行为与现状一致）。
    assert await _current_scene_indexes(db, nid) == {0}
    # 精确归因列表：s1 known（整章消费命中）；s2 登记证明与变更无关，
    # 不进受影响/重算列表（零无关重算的重算清单证明）；s0 不进。
    entries = _scene_entries_by_index(receipt)
    assert set(entries) == {1}
    assert entries[1]["basis"] == "known"
    assert entries[1]["reason"] == ImpactReason.anchored_chapter_edited.value
    assert entries[1]["scene_id"] == str(scene1.id)
    # unsupported 消费者恒列（缺口可见）→ unknown_scope 保持 True。
    assert receipt.unknown_scope is True
    rebuild = next(
        item
        for item in receipt.recompute_options
        if item["kind"] == "rebuild_derived_state"
    )
    assert {item["scene_index"] for item in rebuild["affected"]} == {1}
    assert receipt.receipt_id
    # DI 视图（C3 消费形态）：scene 级条目完整、可直接 JSON。
    view = receipt_view(receipt)
    assert {item["scene_index"] for item in view["affected"] if item["scene_index"]} == {
        1
    }
    json.dumps(view, ensure_ascii=False)


async def test_all_registered_unrelated_keeps_projections_current(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """登记完备且全部证明无关 → 零投影失效（"已知依赖零无关重生成"的
    窗口收窄端到端：s1/s2 checkpoint 保持 current，重算清单不含任何场景）。"""
    db, nid = db_session, evolution_project_id
    chapter2_old = "水" * 300 + "第二章：青竹取出铜钥匙，递给林舟。"
    await _working_draft_row(db, nid, 1, "山" * 200 + "第一章结尾。")
    await _working_draft_row(db, nid, 2, chapter2_old)
    scene0 = await _scene(db, nid, 0, 1)
    scene1 = await _scene(db, nid, 1, 2)
    await _prepare_projections(db, nid, scene0)
    await _prepare_projections(db, nid, scene1)
    # s1 只消费 ch2 开头区间（变更在尾部，不相交）。
    await _register_on_current_checkpoints(
        db,
        nid,
        scene1,
        chapters=[
            {"chapter_index": 1},
            {"chapter_index": 2, "ranges": [(0, 100)]},
        ],
    )

    change = compute_source_change(chapter2_old, chapter2_old.replace("铜钥匙", "铁哨子"))
    await _working_draft_row(
        db, nid, 2, chapter2_old.replace("铜钥匙", "铁哨子"), version_number=2
    )
    receipt = await apply_source_invalidation(
        db, nid, chapter_index=2, change=change, content_mode="working"
    )

    # 登记覆盖完整且全部无关 → 零投影失效：s1 保持 current（现状会失效）。
    assert receipt.earliest_affected_scene_index == 1
    assert await _current_scene_indexes(db, nid) == {0, 1}
    assert "story_scene_projections" not in receipt.invalidated_consumers
    # 归因列表与重算清单为空（miss 不进列表）；证据索引重建照常触发。
    assert _scene_entries_by_index(receipt) == {}
    rebuild = next(
        item
        for item in receipt.recompute_options
        if item["kind"] == "rebuild_derived_state"
    )
    assert rebuild["affected"] == []
    assert "evidence_chapter_index" in receipt.invalidated_consumers
    assert "已按登记收窄" in receipt.coverage_note


async def test_registered_offset_window_hit_reason_end_to_end(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """登记区间与变更窗口相交 → ``offset_window_hit``（区别于合成的
    ``anchored_chapter_edited`` 整章判定）。"""
    db, nid = db_session, evolution_project_id
    chapter2_old = "水" * 300 + "第二章：青竹取出铜钥匙，递给林舟。"
    await _working_draft_row(db, nid, 1, "山" * 200 + "第一章结尾。")
    await _working_draft_row(db, nid, 2, chapter2_old)
    scene0 = await _scene(db, nid, 0, 1)
    scene1 = await _scene(db, nid, 1, 2)
    await _prepare_projections(db, nid, scene0)
    await _prepare_projections(db, nid, scene1)
    # s1 登记只消费 ch2 尾部区间（覆盖变更窗口）。
    await _register_on_current_checkpoints(
        db,
        nid,
        scene1,
        chapters=[
            {"chapter_index": 2, "ranges": [(280, 350)]},
        ],
    )

    change = compute_source_change(chapter2_old, chapter2_old.replace("铜钥匙", "铁哨子"))
    await _working_draft_row(
        db, nid, 2, chapter2_old.replace("铜钥匙", "铁哨子"), version_number=2
    )
    receipt = await apply_source_invalidation(
        db, nid, chapter_index=2, change=change, content_mode="working"
    )
    entries = _scene_entries_by_index(receipt)
    assert set(entries) == {1}
    assert entries[1]["reason"] == ImpactReason.offset_window_hit.value
    assert entries[1]["basis"] == "known"
    # 登记覆盖完整（s1 全维度登记）：s0 未进保守窗口、无 unknown 场景。
    assert await _current_scene_indexes(db, nid) == {0}


async def test_unregistered_scenes_keep_conservative_with_explainable_view(
    db_session: AsyncSession,
    evolution_project_id: str,
) -> None:
    """无登记（现状形态）：锚定场景 known、后续场景 unknown、行为不变。

    锚定结构合成登记保证受影响列表可解释（s1=锚定命中 known，s2=保守
    扩大 unknown），但评估窗口与现状保守扩大逐位一致（s1、s2 均失效）。
    """
    db, nid = db_session, evolution_project_id
    chapter2_old = "水" * 300 + "第二章：青竹取出铜钥匙，递给林舟。"
    await _working_draft_row(db, nid, 1, "山" * 200 + "第一章结尾。")
    await _working_draft_row(db, nid, 2, chapter2_old)
    await _working_draft_row(db, nid, 3, "木" * 200 + "第三章。")
    scene0 = await _scene(db, nid, 0, 1)
    scene1 = await _scene(db, nid, 1, 2)
    scene2 = await _scene(db, nid, 2, 3)
    await _prepare_projections(db, nid, scene0)
    await _prepare_projections(db, nid, scene1)
    await _prepare_projections(db, nid, scene2)

    change = compute_source_change(chapter2_old, chapter2_old.replace("铜钥匙", "铁哨子"))
    await _working_draft_row(
        db, nid, 2, chapter2_old.replace("铜钥匙", "铁哨子"), version_number=2
    )
    receipt = await apply_source_invalidation(
        db, nid, chapter_index=2, change=change, content_mode="working"
    )

    entries = _scene_entries_by_index(receipt)
    # s1 锚定被改章：known + 真实 scene_id；s2 保守扩大：unknown 显式。
    assert set(entries) == {1, 2}
    assert entries[1]["basis"] == "known"
    assert entries[1]["scene_id"] == str(scene1.id)
    assert entries[1]["reason"] == ImpactReason.anchored_chapter_edited.value
    assert entries[2]["basis"] == "unknown"
    assert entries[2]["reason"] == ImpactReason.conservative_expansion_unregistered.value
    assert 0 not in entries  # 无关 Scene 不进列表
    assert receipt.unknown_scope is True
    # 行为不变：保守窗口（s1 起，含 s2）全部失效、s0 保持。
    assert await _current_scene_indexes(db, nid) == {0}
    rebuild_scenes = {
        item["scene_index"]
        for option in receipt.recompute_options
        if option["kind"] == "rebuild_derived_state"
        for item in option.get("affected", [])
        if item.get("scene_index") is not None
    }
    assert rebuild_scenes == {1, 2}
    # 内嵌评估与回执增量字段同源（receipt_view 重投影一致）。
    view = receipt_view(receipt)
    assert {item["scene_index"] for item in view["affected"] if item["scene_index"]} == {
        1,
        2,
    }


# ---------------------------------------------------------------------------
# C2 DI 键（组合根注册 + 视图退化形态）
# ---------------------------------------------------------------------------


def test_invalidation_receipt_view_service_registered_and_callable() -> None:
    from core.container import get
    from core.service_keys import EVOLUTION_INVALIDATION_RECEIPT_VIEW

    view = get(EVOLUTION_INVALIDATION_RECEIPT_VIEW)(_receipt())
    # 手写回执（无内嵌评估）退化为确定性键形态，键集仍是 C0 最小集。
    assert {"affected", "unknown_scope", "receipt_id"} <= set(view)
    assert view["receipt_id"] == receipt_fingerprint(_receipt())
