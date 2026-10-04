"""世界修订备注服务测试（路线图阶段 0 · G0）。

覆盖：三种目标类型、跨作品 404、地图候选 409、超长 422、
空串删除、重复写入幂等、空白剥离。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.models import (
    CoreEntity,
    EntityRevision,
    WorldBiblePage,
    WorldBiblePageRevision,
)
from modules.world.services.revision_notes import (
    load_revision_notes,
    set_revision_note,
)
from tests.utils import _create_project


async def _make_entity_revision(
    db_session: AsyncSession, novel_id: str
) -> EntityRevision:
    entity = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_type="character",
        name="测试角色",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()

    revision = EntityRevision(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_id=entity.id,
        snapshot={"entity_type": "character", "name": "测试角色"},
        revision_reason="manual_update",
    )
    db_session.add(revision)
    await db_session.flush()
    return revision


async def _make_page_revision(
    db_session: AsyncSession, novel_id: str
) -> WorldBiblePageRevision:
    page = WorldBiblePage(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        page_type="lore",
        page_key=f"page-{uuid.uuid4().hex[:8]}",
        title="测试页面",
    )
    db_session.add(page)
    await db_session.flush()

    revision = WorldBiblePageRevision(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        page_id=page.id,
        version_number=1,
        snapshot_json={"title": "测试页面"},
        revision_digest="digest",
        revision_reason="manual_publish",
    )
    db_session.add(revision)
    await db_session.flush()
    return revision


async def _make_map_revision(
    db_session: AsyncSession, novel_id: str, *, status: str
) -> MapAtlasRevision:
    node = MapAtlasNode(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        semantic_key=f"world-{uuid.uuid4().hex[:8]}",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()

    revision = MapAtlasRevision(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        node_id=node.id,
        status=status,
        document={},
        geometry_hash="hash",
        problems=[],
    )
    db_session.add(revision)
    await db_session.flush()
    return revision


@pytest_asyncio.fixture
async def seeded_ids(db_session: AsyncSession) -> dict[str, str]:
    """一个作品 + 三种目标修订各一条。"""
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    entity_rev = await _make_entity_revision(db_session, novel_id)
    page_rev = await _make_page_revision(db_session, novel_id)
    map_rev = await _make_map_revision(db_session, novel_id, status="saved")
    return {
        "novel_id": novel_id,
        "entity": str(entity_rev.id),
        "page": str(page_rev.id),
        "map": str(map_rev.id),
    }


@pytest.mark.asyncio
async def test_set_and_load_note_for_entity_page_map(
    db_session: AsyncSession, seeded_ids: dict[str, str]
) -> None:
    """三种目标类型都能写入并批量读取备注。"""
    novel_id = seeded_ids["novel_id"]
    for kind in ("entity", "page", "map"):
        response = await set_revision_note(
            db_session, novel_id, kind, seeded_ids[kind], f"{kind} 的备注"
        )
        assert response.note == f"{kind} 的备注"
        assert response.target_kind == kind

    notes = {
        kind: await load_revision_notes(db_session, novel_id, kind, [seeded_ids[kind]])
        for kind in ("entity", "page", "map")
    }
    for kind in ("entity", "page", "map"):
        revision_id = uuid.UUID(hex=seeded_ids[kind])
        assert notes[kind][revision_id] == f"{kind} 的备注"


@pytest.mark.asyncio
async def test_cross_novel_revision_returns_404(
    db_session: AsyncSession, seeded_ids: dict[str, str]
) -> None:
    """目标修订不属于这部作品时返回 404。"""
    other_novel_id = uuid.uuid4().hex
    await _create_project(db_session, other_novel_id)

    for kind in ("entity", "page", "map"):
        with pytest.raises(NotFoundError):
            await set_revision_note(
                db_session, other_novel_id, kind, seeded_ids[kind], "越权备注"
            )

    with pytest.raises(NotFoundError):
        await set_revision_note(
            db_session, other_novel_id, "entity", str(uuid.uuid4()), "不存在的修订"
        )


@pytest.mark.asyncio
async def test_map_candidate_revision_rejected(
    db_session: AsyncSession, seeded_ids: dict[str, str]
) -> None:
    """地图候选版本不能写备注，返回 409。"""
    novel_id = seeded_ids["novel_id"]
    candidate = await _make_map_revision(db_session, novel_id, status="candidate")

    with pytest.raises(ConflictError):
        await set_revision_note(
            db_session, novel_id, "map", str(candidate.id), "候选备注"
        )


@pytest.mark.asyncio
async def test_note_too_long_returns_422(
    db_session: AsyncSession, seeded_ids: dict[str, str]
) -> None:
    """超过 500 字的备注返回 422。"""
    with pytest.raises(ValidationError) as exc_info:
        await set_revision_note(
            db_session,
            seeded_ids["novel_id"],
            "entity",
            seeded_ids["entity"],
            "长" * 501,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_empty_note_deletes(
    db_session: AsyncSession, seeded_ids: dict[str, str]
) -> None:
    """空串删除备注；删除后读取不到，再次删除仍然成功（幂等）。"""
    novel_id = seeded_ids["novel_id"]
    revision_id = seeded_ids["entity"]

    await set_revision_note(db_session, novel_id, "entity", revision_id, "先写一条")
    response = await set_revision_note(db_session, novel_id, "entity", revision_id, "   ")
    assert response.note is None

    notes = await load_revision_notes(db_session, novel_id, "entity", [revision_id])
    assert notes == {}

    response = await set_revision_note(db_session, novel_id, "entity", revision_id, "")
    assert response.note is None


@pytest.mark.asyncio
async def test_repeat_write_is_idempotent(
    db_session: AsyncSession, seeded_ids: dict[str, str]
) -> None:
    """重复写入同样内容是幂等的：结果一致且仍只有一条记录。"""
    novel_id = seeded_ids["novel_id"]
    revision_id = seeded_ids["entity"]

    first = await set_revision_note(
        db_session, novel_id, "entity", revision_id, "同样内容"
    )
    second = await set_revision_note(
        db_session, novel_id, "entity", revision_id, "同样内容"
    )
    assert second.note == first.note == "同样内容"

    notes = await load_revision_notes(db_session, novel_id, "entity", [revision_id])
    assert list(notes.values()) == ["同样内容"]

    third = await set_revision_note(
        db_session, novel_id, "entity", revision_id, "改成别的"
    )
    assert third.note == "改成别的"
    notes = await load_revision_notes(db_session, novel_id, "entity", [revision_id])
    assert list(notes.values()) == ["改成别的"]


@pytest.mark.asyncio
async def test_note_is_stripped(
    db_session: AsyncSession, seeded_ids: dict[str, str]
) -> None:
    """备注写入前去掉首尾空白。"""
    response = await set_revision_note(
        db_session,
        seeded_ids["novel_id"],
        "page",
        seeded_ids["page"],
        "  前后都有空白  ",
    )
    assert response.note == "前后都有空白"


@pytest.mark.asyncio
async def test_load_notes_empty_ids(db_session: AsyncSession) -> None:
    """空 ID 列表直接返回空映射，不发起查询。"""
    notes = await load_revision_notes(db_session, uuid.uuid4().hex, "entity", [])
    assert notes == {}
