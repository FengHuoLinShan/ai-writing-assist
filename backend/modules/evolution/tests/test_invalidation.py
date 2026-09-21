"""E05 失效传播测试（V4 T08/T09）。

- T08：同长度正文修改（位置在 4000 字后）必须被物理差异检出，触发证据
  索引换源重建，受影响 Scene 派生投影不再显示有效。
- T09：修改前文使受影响历史/知识派生投影失效（保守扩大到后续 Scene，
  前序不受牵连）；调换场景使事件序号对齐并从最早移动 Scene 起失效。
- 失效不删历史：作者确认与已提交回执保留。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.indexing.models import RagIndexState
from modules.evolution.invalidation import (
    apply_scene_reorder_invalidation,
    apply_source_invalidation,
    compute_source_change,
)
from modules.story.continuity.contracts import ConfirmedContinuityEventIngest
from modules.story.continuity.models import (
    MemoryEvent,
    MemorySceneCheckpoint,
    MemorySceneSnapshot,
)
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene
from modules.writing.facade import create_draft_only

NOVEL_CHAPTER_TEXT = "舟" * 100


def _make_text(total: int, tail: str) -> str:
    return "山" * (total - len(tail)) + tail


# ---------------------------------------------------------------------------
# 物理差异（T08 前半）
# ---------------------------------------------------------------------------


def test_same_length_edit_after_offset_4000_is_detected() -> None:
    old = _make_text(6000, "青竹取出铜钥匙，递给林舟。")
    new = old.replace("铜钥匙", "铁哨子")  # 同字数替换，位置在 4000 字后
    assert len(old) == len(new)

    change = compute_source_change(old, new)
    assert change.changed is True
    assert change.same_length is True
    assert change.first_offset is not None and change.first_offset >= 4000
    assert change.last_offset is not None and change.last_offset > change.first_offset


def test_identical_text_reports_no_change() -> None:
    change = compute_source_change(NOVEL_CHAPTER_TEXT, NOVEL_CHAPTER_TEXT)
    assert change.changed is False
    assert change.first_offset is None


def test_length_change_covers_tail_conservatively() -> None:
    old = "林舟进城。" + "路" * 10
    new = "林舟进城了。" + "路" * 10
    change = compute_source_change(old, new)
    assert change.changed is True
    assert change.same_length is False
    assert change.first_offset == 4
    assert change.last_offset == max(len(old), len(new))


def test_none_and_empty_are_changes() -> None:
    assert compute_source_change(None, "").changed is False
    assert compute_source_change("", "舟").changed is True


# ---------------------------------------------------------------------------
# T08：同长度修改 → 索引换源 + 派生投影失效
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


async def _current_checkpoints(
    db: AsyncSession, novel_id: str, scene_id: uuid.UUID
) -> list[MemorySceneCheckpoint]:
    return list(
        (
            await db.execute(
                select(MemorySceneCheckpoint).where(
                    MemorySceneCheckpoint.novel_id == uuid.UUID(novel_id),
                    MemorySceneCheckpoint.scene_id == scene_id,
                    MemorySceneCheckpoint.is_current.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )


async def _index_state(
    db: AsyncSession, novel_id: str, chapter_index: int
) -> RagIndexState | None:
    return (
        await db.execute(
            select(RagIndexState).where(
                RagIndexState.novel_id == uuid.UUID(novel_id),
                RagIndexState.chapter_index == chapter_index,
                RagIndexState.content_mode == "working",
            )
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_t08_same_length_edit_invalidates_index_and_projections(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    db, nid = db_session, test_project_id
    old_text = _make_text(6000, "青竹取出铜钥匙，递给林舟。")
    await create_draft_only(db, nid, 1, "第一章", old_text)
    scene = await _scene(db, nid, 0, 1)
    await _prepare_projections(db, nid, scene)
    assert await _current_checkpoints(db, nid, scene.id) != []

    same_length_edit = old_text.replace("铜钥匙", "铁哨子")
    change = compute_source_change(old_text, same_length_edit)
    assert change.first_offset is not None and change.first_offset >= 4000

    first_state = await _index_state(db, nid, 1)
    await create_draft_only(db, nid, 1, "第一章", same_length_edit)
    receipt = await apply_source_invalidation(
        db, nid, chapter_index=1, change=change, content_mode="working"
    )

    # 索引换源：请求 hash 不再是旧内容，旧结果不能冒充有效。
    state = await _index_state(db, nid, 1)
    assert state is not None
    if first_state is not None:
        assert state.requested_hash != first_state.requested_hash or (
            state.generation != first_state.generation
        )
    assert (
        receipt.invalidated_consumers["evidence_chapter_index"]["requested_hash"]
        == state.requested_hash
    )

    # 派生投影软失效：checkpoint 不再 current，历史行仍在（不删历史）。
    assert await _current_checkpoints(db, nid, scene.id) == []
    superseded = list(
        (
            await db.execute(
                select(MemorySceneCheckpoint).where(
                    MemorySceneCheckpoint.novel_id == uuid.UUID(nid),
                    MemorySceneCheckpoint.scene_id == scene.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert superseded != []

    # 未接线消费者显式列出，不冒充全量失效。
    assert {item["consumer"] for item in receipt.unsupported_consumers} == {
        "world_knowledge",
        "map_atlas",
        "assistant_suggestions",
    }
    assert receipt.coverage_note


@pytest.mark.asyncio
async def test_unchanged_source_is_noop(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    db, nid = db_session, test_project_id
    text = _make_text(100, "舟")
    await create_draft_only(db, nid, 1, "第一章", text)
    scene = await _scene(db, nid, 0, 1)
    await _prepare_projections(db, nid, scene)

    receipt = await apply_source_invalidation(
        db,
        nid,
        chapter_index=1,
        change=compute_source_change(text, text),
        content_mode="working",
    )
    assert receipt.nothing_to_do is True
    assert receipt.invalidated_consumers == {}
    assert await _current_checkpoints(db, nid, scene.id) != []


# ---------------------------------------------------------------------------
# T09：修改前文 / 调换场景
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t09_editing_earlier_chapter_invalidates_downstream_only(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """改第 2 章：锚定它的 Scene 2 起失效，Scene 0/1 的投影保持有效。"""
    db, nid = db_session, test_project_id
    await create_draft_only(db, nid, 1, "第一章", _make_text(200, "舟"))
    await create_draft_only(db, nid, 2, "第二章", _make_text(200, "帆"))
    await create_draft_only(db, nid, 3, "第三章", _make_text(200, "钟"))
    scene0 = await _scene(db, nid, 0, 1)
    scene1 = await _scene(db, nid, 1, 1)
    scene2 = await _scene(db, nid, 2, 2)
    scene3 = await _scene(db, nid, 3, 3)
    for scene in (scene0, scene1, scene2, scene3):
        await _prepare_projections(db, nid, scene)

    old_text = _make_text(200, "帆" * 10)
    edited = old_text.replace("帆" * 5, "雾" * 5, 1)
    await create_draft_only(db, nid, 2, "第二章", edited)
    receipt = await apply_source_invalidation(
        db,
        nid,
        chapter_index=2,
        change=compute_source_change(old_text, edited),
        content_mode="working",
    )

    assert receipt.earliest_affected_scene_index == 2
    assert await _current_checkpoints(db, nid, scene0.id) != []
    assert await _current_checkpoints(db, nid, scene1.id) != []
    assert await _current_checkpoints(db, nid, scene2.id) == []
    assert await _current_checkpoints(db, nid, scene3.id) == []
    current_snapshots = list(
        (
            await db.execute(
                select(MemorySceneSnapshot).where(
                    MemorySceneSnapshot.novel_id == uuid.UUID(nid),
                    MemorySceneSnapshot.is_current.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    anchored = [i for i in current_snapshots if i.scene_index is not None]
    assert all(item.scene_index <= 1 for item in anchored)


@pytest.mark.asyncio
async def test_t09_scene_reorder_aligns_events_and_invalidates_from_earliest(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """调换 Scene 1/2：事件序号对齐、从最早移动 Scene 起投影失效、
    作者确认事件保留。"""
    db, nid = db_session, test_project_id
    scene1 = await _scene(db, nid, 1, 1)
    scene2 = await _scene(db, nid, 2, 2)
    scene3 = await _scene(db, nid, 3, 3)
    await MemoryService().record_scene_events(
        db,
        nid,
        scene_id=str(scene1.id),
        scene_index=1,
        chapter_index=1,
        events=[{"dimension": "entities", "snapshot_after": {"summary": "s1"}}],
        producer_family="deep_import",
    )
    await MemoryService().confirm_scene_continuity_event(
        db,
        nid,
        scene_id=str(scene2.id),
        scene_index=2,
        chapter_index=2,
        event=ConfirmedContinuityEventIngest(
            dimension="entities",
            category="profile",
            field_path="青竹.status",
            old_value=None,
            new_value="持有铜钥匙",
            idempotency_key="confirm-reorder",
            evidence_summary="作者核对",
        ),
    )
    for scene in (scene1, scene2, scene3):
        await _prepare_projections(db, nid, scene)

    # 权威顺序调换 Scene 1 ↔ Scene 2。
    receipt = await apply_scene_reorder_invalidation(
        db,
        nid,
        scene_positions={
            str(scene1.id): 2,
            str(scene2.id): 1,
            str(scene3.id): 3,
        },
    )

    assert receipt.nothing_to_do is False
    assert receipt.earliest_affected_scene_index == 1
    # 事件序号已按新权威顺序对齐。
    events = list(
        (
            await db.execute(
                select(MemoryEvent)
                .where(MemoryEvent.novel_id == uuid.UUID(nid))
                .order_by(MemoryEvent.scene_index, MemoryEvent.scene_sequence)
            )
        )
        .scalars()
        .all()
    )
    by_scene = {(row.scene_id, row.scene_index) for row in events}
    assert (scene2.id, 1) in by_scene
    assert (scene1.id, 2) in by_scene
    # 作者确认保留（失效不删历史）。
    author_rows = [row for row in events if row.source == "author_confirmation"]
    assert len(author_rows) == 1
    # 从最早移动 Scene 起投影失效；未移动的 Scene 3 之前没有更早锚点可比，
    # 保守扩大同样覆盖（历史依赖前缀）。
    assert await _current_checkpoints(db, nid, scene1.id) == []
    assert await _current_checkpoints(db, nid, scene2.id) == []
