"""E03b 分区替换契约：稳定事件键、家族隔离与作者保护共存（V4 T06）。

对应 plans/01-EVOLUTION.md §2.2：允许替换的仅是同一 producer family 的
派生产物；事件身份来自语义指纹（event_key），输出重排不重建事实。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.contracts import ConfirmedContinuityEventIngest
from modules.story.continuity.models import MemoryEvent
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene


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


def _delta(summary: str, source: str = "deep_import") -> dict:
    return {
        "dimension": "entities",
        "event_type": "manual_correction",
        "snapshot_after": {"summary": summary},
        "source": source,
    }


async def _events(
    db: AsyncSession, novel_id: str, scene_id: uuid.UUID
) -> list[MemoryEvent]:
    return list(
        (
            await db.execute(
                select(MemoryEvent)
                .where(
                    MemoryEvent.novel_id == uuid.UUID(novel_id),
                    MemoryEvent.scene_id == scene_id,
                )
                .order_by(MemoryEvent.scene_sequence)
            )
        )
        .scalars()
        .all()
    )


async def _record(
    db: AsyncSession,
    novel_id: str,
    scene: Scene,
    events: list[dict],
    *,
    family: str | None = None,
) -> None:
    await MemoryService().record_scene_events(
        db,
        novel_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=events,
        producer_family=family,
    )


@pytest.mark.asyncio
async def test_reordered_rerun_updates_rows_in_place(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """T06：输出重排/重跑不重建事实——同语义按键原地更新，行 ID 稳定。"""
    scene = await _scene(db_session, test_project_id)
    await _record(
        db_session,
        test_project_id,
        scene,
        [_delta("观察甲"), _delta("观察乙")],
        family="deep_import",
    )
    first = await _events(db_session, test_project_id, scene.id)
    assert [row.snapshot_after["summary"] for row in first] == ["观察甲", "观察乙"]

    await _record(
        db_session,
        test_project_id,
        scene,
        [_delta("观察乙"), _delta("观察甲")],
        family="deep_import",
    )
    second = await _events(db_session, test_project_id, scene.id)

    assert {row.id for row in second} == {row.id for row in first}
    assert len(second) == 2
    by_summary = {row.snapshot_after["summary"]: row for row in second}
    first_by_summary = {row.snapshot_after["summary"]: row for row in first}
    for summary, row in by_summary.items():
        original = first_by_summary[summary]
        assert row.id == original.id
        assert row.scene_sequence == original.scene_sequence


@pytest.mark.asyncio
async def test_family_scoped_rerun_keeps_other_producer_families(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """deep_import 空重跑只清自己的派生带；其他家族与作者确认保留。"""
    scene = await _scene(db_session, test_project_id)
    await _record(
        db_session,
        test_project_id,
        scene,
        [_delta("导入观察", "deep_import"), _delta("本地抽取", "ai_extraction")],
    )
    await MemoryService().confirm_scene_continuity_event(
        db_session,
        test_project_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        event=ConfirmedContinuityEventIngest(
            dimension="entities",
            category="profile",
            field_path="林舟.status",
            old_value=None,
            new_value="持有铜钥匙",
            idempotency_key="confirm-1",
            evidence_summary="作者核对",
        ),
    )

    await _record(
        db_session, test_project_id, scene, [], family="deep_import"
    )

    events = await _events(db_session, test_project_id, scene.id)
    assert [(row.source, row.snapshot_after.get("summary")) for row in events] == [
        ("ai_extraction", "本地抽取"),
        ("author_confirmation", None),
    ]


@pytest.mark.asyncio
async def test_changed_content_replaces_only_affected_rows(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """内容变化的断言换键重建，未变化的行保持稳定。"""
    scene = await _scene(db_session, test_project_id)
    await _record(
        db_session,
        test_project_id,
        scene,
        [_delta("观察甲"), _delta("观察乙")],
        family="deep_import",
    )
    first = {
        row.snapshot_after["summary"]: row.id
        for row in await _events(db_session, test_project_id, scene.id)
    }

    await _record(
        db_session,
        test_project_id,
        scene,
        [_delta("观察甲"), _delta("观察乙（修订）")],
        family="deep_import",
    )
    second = {
        row.snapshot_after["summary"]: row.id
        for row in await _events(db_session, test_project_id, scene.id)
    }

    assert second["观察甲"] == first["观察甲"]
    assert "观察乙" not in second
    assert second["观察乙（修订）"] != first["观察乙"]
    assert len(second) == 2


@pytest.mark.asyncio
async def test_family_none_replaces_all_derived_but_author(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """不指定家族（legacy 行为面）：替换全部派生行，作者确认仍保留。"""
    scene = await _scene(db_session, test_project_id)
    await _record(
        db_session,
        test_project_id,
        scene,
        [_delta("导入观察", "deep_import"), _delta("本地抽取", "ai_extraction")],
    )
    await _record(db_session, test_project_id, scene, [_delta("新观察")])

    events = await _events(db_session, test_project_id, scene.id)
    assert [
        (row.source, row.snapshot_after.get("summary")) for row in events
    ] == [("deep_import", "新观察")]
