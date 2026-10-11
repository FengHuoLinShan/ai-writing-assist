"""M4 契约 §3/§6：checkpoint 来源基线登记与视图读时新鲜度验收。

A04：同长度替换/Scene 重排绕过失效钩子时，状态视图不再静默供给旧投影；
正流程（失效→懒重建）恢复 ok。manual/confirmed 作者行与基线缺失语义按契约。
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.models import MemorySceneCheckpoint
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import SceneStateViewService
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene
from modules.writing.models import WritingDraft

pytestmark = pytest.mark.asyncio

_DRIFT_MARK = "来源基线已变化"
_MISSING_MARK = "缺少来源基线登记"


async def _scene(
    db: AsyncSession, novel_id: str, scene_index: int, chapter: int
) -> Scene:
    item = Scene(
        novel_id=uuid.UUID(novel_id),
        scene_index=scene_index,
        title=f"Scene {scene_index}",
        chapter_ids=[chapter],
        scene_chunks=[{"chapter_index": chapter}],
        status="draft",
    )
    db.add(item)
    await db.flush()
    return item


async def _draft(db: AsyncSession, novel_id: str, chapter: int, content: str) -> None:
    db.add(
        WritingDraft(
            novel_id=uuid.UUID(novel_id),
            chapter_index=chapter,
            content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            version_number=1,
            status="draft",
        )
    )
    await db.flush()


async def _basis_scene(db: AsyncSession, test_project_id: str) -> tuple[Scene, str]:
    """一个带事件与 working 稿的 Scene；ensure 后全部维度 ok。"""
    scene = await _scene(db, test_project_id, 0, 1)
    await _draft(db, test_project_id, 1, "甲在灯塔下把铜钥匙交给乙。")
    key_id, jia, yi = (str(uuid.uuid4()) for _ in range(3))
    await MemoryService().record_scene_events(
        db,
        test_project_id,
        scene_id=str(scene.id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key_id,
                "snapshot_after": {"name": "铜钥匙", "custody_owner": jia},
            },
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": key_id,
                "snapshot_after": {"custody_holder": yi},
            },
        ],
    )
    await SceneMemoryProjectionService().ensure_scene(db, test_project_id, str(scene.id))
    return scene, key_id


async def _author_view(db: AsyncSession, novel_id: str, scene_id: str):
    return await SceneStateViewService().get_view(
        db, novel_id=novel_id, scene_id=scene_id, viewpoint={"kind": "author"}
    )


def _dim(view, dimension: str):
    return next(item for item in view.dimensions if item.dimension == dimension)


async def _current_row(
    db: AsyncSession, novel_id: str, scene_id: str, dimension: str
) -> MemorySceneCheckpoint:
    return (
        await db.execute(
            select(MemorySceneCheckpoint).where(
                MemorySceneCheckpoint.novel_id == uuid.UUID(novel_id),
                MemorySceneCheckpoint.scene_id == uuid.UUID(scene_id),
                MemorySceneCheckpoint.dimension == dimension,
                MemorySceneCheckpoint.is_current.is_(True),
            )
        )
    ).scalar_one()


async def test_same_length_replacement_without_hooks_degrades_view(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene, _key = await _basis_scene(db_session, test_project_id)
    before = await _author_view(db_session, test_project_id, str(scene.id))
    assert _dim(before, "entities").status == "ok"

    # 绕过仓库钩子：同长度替换正文，只改 ORM 行（模拟直改库/历史数据路径）
    draft = (
        await db_session.execute(
            select(WritingDraft).where(
                WritingDraft.novel_id == uuid.UUID(test_project_id),
                WritingDraft.chapter_index == 1,
            )
        )
    ).scalar_one()
    old = draft.content or ""
    draft.content = old[:-1] + ("乙" if old[-1] != "乙" else "甲")
    draft.content_hash = hashlib.sha256((draft.content or "").encode("utf-8")).hexdigest()
    await db_session.flush()

    after = await _author_view(db_session, test_project_id, str(scene.id))
    entities = _dim(after, "entities")
    assert entities.status == "degraded"
    assert _DRIFT_MARK in (entities.gap_reason or "")
    # 事实仍按原投影呈现（保留历史），但缺口显式，不再静默 ok


async def test_scene_reorder_without_hooks_degrades_view(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene, _key = await _basis_scene(db_session, test_project_id)
    before = await _author_view(db_session, test_project_id, str(scene.id))
    assert _dim(before, "entities").status == "ok"

    # 绕过重排钩子：新 Scene 插到 index 0，原 Scene 挪到 index 1
    scene.scene_index = 1
    db_session.add(
        Scene(
            novel_id=uuid.UUID(test_project_id),
            scene_index=0,
            title="Scene 0",
            chapter_ids=[1],
            scene_chunks=[{"chapter_index": 1}],
            status="draft",
        )
    )
    await db_session.flush()

    after = await _author_view(db_session, test_project_id, str(scene.id))
    assert _dim(after, "entities").status == "degraded"
    assert _DRIFT_MARK in (_dim(after, "entities").gap_reason or "")


async def test_invalidation_then_rebuild_restores_freshness(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene, _key = await _basis_scene(db_session, test_project_id)
    draft = (
        await db_session.execute(
            select(WritingDraft).where(
                WritingDraft.novel_id == uuid.UUID(test_project_id),
                WritingDraft.chapter_index == 1,
            )
        )
    ).scalar_one()
    draft.content = (draft.content or "") + "（补写）"
    draft.content_hash = hashlib.sha256((draft.content or "").encode("utf-8")).hexdigest()
    await db_session.flush()
    drifted = await _author_view(db_session, test_project_id, str(scene.id))
    assert _dim(drifted, "entities").status == "degraded"

    # 正流程：失效传播（apply_source_invalidation 的 story 侧入口）→ 懒重建
    from modules.story.facade import invalidate_derived_state

    await invalidate_derived_state(
        db_session,
        test_project_id,
        from_scene_index=0,
        from_chapter=1,
    )
    await SceneMemoryProjectionService().ensure_scene(
        db_session, test_project_id, str(scene.id)
    )
    rebuilt = await _author_view(db_session, test_project_id, str(scene.id))
    assert all(_DRIFT_MARK not in (item.gap_reason or "") for item in rebuilt.dimensions)
    row = await _current_row(db_session, test_project_id, str(scene.id), "entities")
    assert row.basis_json is not None and row.basis_json.get("manuscript")


async def test_missing_basis_registration_degrades(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene, _key = await _basis_scene(db_session, test_project_id)
    row = await _current_row(db_session, test_project_id, str(scene.id), "entities")
    row.basis_json = None
    await db_session.flush()

    view = await _author_view(db_session, test_project_id, str(scene.id))
    entities = _dim(view, "entities")
    assert entities.status == "degraded"
    assert _MISSING_MARK in (entities.gap_reason or "")
    await SceneMemoryProjectionService().ensure_scene(
        db_session, test_project_id, str(scene.id)
    )
    assert row.basis_json is not None
    assert (
        _dim(
            await _author_view(db_session, test_project_id, str(scene.id)), "entities"
        ).status
        == "ok"
    )


async def test_author_rows_exempt_from_basis_degradation(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene, _key = await _basis_scene(db_session, test_project_id)
    draft = (
        await db_session.execute(
            select(WritingDraft).where(
                WritingDraft.novel_id == uuid.UUID(test_project_id),
                WritingDraft.chapter_index == 1,
            )
        )
    ).scalar_one()
    draft.content = (draft.content or "") + "（修订）"
    draft.content_hash = hashlib.sha256((draft.content or "").encode("utf-8")).hexdigest()
    locations_row = await _current_row(
        db_session, test_project_id, str(scene.id), "locations"
    )
    locations_row.confirmed = True
    await db_session.flush()

    view = await _author_view(db_session, test_project_id, str(scene.id))
    assert _dim(view, "entities").status == "degraded"
    # 作者确认行不因环境漂移降级
    assert _dim(view, "locations").status == "ok"
    assert _dim(view, "locations").gap_reason is None


async def test_unsupported_dependencies_are_explicit(
    db_session: AsyncSession, test_project_id: str
) -> None:
    scene, _key = await _basis_scene(db_session, test_project_id)
    view = await _author_view(db_session, test_project_id, str(scene.id))
    # 世界正典修订/地图册不自动失效本视图（观察层语义），必须显式列出
    assert set(view.unsupported_dependencies) >= {"world_canon_revision", "map_atlas"}
