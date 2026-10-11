"""M5 契约 §2/§3：试改的结构化字段级比较与状态影响有限列表。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.collaboration.state_impact import trial_state_impact
from modules.collaboration.tests.test_workspaces import setup_trial
from modules.collaboration.workspaces import field_changes


def test_field_changes_lists_dict_fields_with_ops() -> None:
    before = {"title": "开场", "content": "她接受了旧敌的帮助。", "note": "旧"}
    after = {
        "title": "开场",
        "content": "她接受了旧敌的帮助。她仍保留了退路。",
        "extra": 1,
    }
    changes = field_changes(before, after)
    assert changes == [
        {
            "field": "content",
            "op": "changed",
            "before": "她接受了旧敌的帮助。",
            "after": "她接受了旧敌的帮助。她仍保留了退路。",
        },
        {"field": "extra", "op": "added", "before": None, "after": 1},
        {"field": "note", "op": "removed", "before": "旧", "after": None},
    ]


def test_field_changes_returns_none_for_non_dict() -> None:
    assert field_changes("文本", "文本2") is None
    assert field_changes(["a"], ["b"]) is None
    assert field_changes({}, {}) == []


@pytest.mark.asyncio
async def test_world_kind_impact_is_explicit_not_checked(db_session) -> None:
    impact = await trial_state_impact(
        db_session,
        "novel-1",
        kind="world_bible_draft",
        resource_id=str(uuid.uuid4()),
        chapter_index=None,
    )
    assert impact["affected"] == []
    assert any("世界正典" in note for note in impact["notes"])
    assert any("无法确定性锚定" in item for item in impact["not_checked"])


@pytest.mark.asyncio
async def test_scene_kind_anchors_all_dimensions_with_stub(db_session) -> None:
    scene_id = str(uuid.uuid4())

    async def fake_checkpoints(db, novel_id, sid):  # noqa: ANN001, ANN202
        return SimpleNamespace(
            items=[
                SimpleNamespace(dimension="entities", status="ready"),
                SimpleNamespace(dimension="knowledge", status="missing"),
            ]
        )

    impact = await trial_state_impact(
        db_session,
        "novel-1",
        kind="scene",
        resource_id=scene_id,
        chapter_index=None,
        get_scene_checkpoints=fake_checkpoints,
    )
    assert {(item["dimension"], item["status"]) for item in impact["affected"]} == {
        ("entities", "ready"),
    }
    assert all(item["scene_id"] == scene_id for item in impact["affected"])


@pytest.mark.asyncio
async def test_workspace_view_includes_field_changes_and_impact(
    db_session: AsyncSession, test_project_id: str, monkeypatch
) -> None:
    db, nid = db_session, test_project_id
    case, view, drafts, _revision = await setup_trial(db, nid, monkeypatch)

    from modules.collaboration import workspaces as ws

    data = await ws.workspace_view(db, nid, view["id"])
    change = next(
        item for item in data["changes"] if item["resource"]["kind"] == "writing_draft"
    )
    fields = change["field_changes"]
    assert fields == [
        {
            "field": "content",
            "op": "changed",
            "before": drafts[0].content,
            "after": drafts[0].content + "她仍保留了退路。",
        }
    ]
    impact = change["state_impact"]
    # 该 fixture 无 Scene：影响面显式「未锚定」，不冒充无影响
    assert impact["affected"] == []
    assert any("未锚定" in item or "尚未建立" in item for item in impact["not_checked"])


@pytest.mark.asyncio
async def test_writing_patch_anchors_scene_state(
    db_session: AsyncSession, test_project_id: str, monkeypatch
) -> None:
    db, nid = db_session, test_project_id
    case, view, drafts, _revision = await setup_trial(db, nid, monkeypatch)

    # 第 1 章锚定一个 Scene，并建立最小 checkpoint
    from modules.story.continuity.scene_projection import SceneMemoryProjectionService
    from modules.story.continuity.services import MemoryService
    from modules.story.outline_state.models import Scene

    scene = Scene(
        novel_id=uuid.UUID(nid),
        scene_index=0,
        title="开场 Scene",
        chapter_ids=["1"],
        scene_chunks=[{"chapter_index": 1}],
        status="draft",
    )
    db.add(scene)
    await db.flush()
    entity_id = str(uuid.uuid4())
    await MemoryService().record_scene_events(
        db,
        nid,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": entity_id,
                "snapshot_after": {"name": "铜钥匙"},
            }
        ],
    )
    await SceneMemoryProjectionService().ensure_scene(db, nid, str(scene.id))

    from modules.collaboration import workspaces as ws

    data = await ws.workspace_view(db, nid, view["id"])
    change = next(
        item for item in data["changes"] if item["resource"]["kind"] == "writing_draft"
    )
    impact = change["state_impact"]
    entities_hits = [
        item
        for item in impact["affected"]
        if item["scene_id"] == str(scene.id) and item["dimension"] == "entities"
    ]
    # 真正章节契约能锚定，但没有直接正文refs的旧记录不能声称事实受影响。
    assert entities_hits == []
    assert any("已锚定 1 个场景" in item for item in impact["notes"])
    assert any("未登记对这份正文" in item for item in impact["not_checked"])
