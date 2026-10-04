"""PUT /api/world/revision-notes 路由测试（路线图阶段 0 · P2）。

服务层语义（跨作品 404 / 地图候选 409 / 超长 422 / 空串删除 / 幂等）
已在 test_revision_notes.py 覆盖；本文件只走 API 层各验证一次。
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.models import (
    CoreEntity,
    EntityRevision,
    WorldBiblePage,
    WorldBiblePageRevision,
    WorldRevisionNote,
)
from tests.utils import _create_project


async def _make_entity_revision(
    db_session: AsyncSession, novel_id: str
) -> EntityRevision:
    entity = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_type="character",
        name="路由角色",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()

    revision = EntityRevision(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_id=entity.id,
        snapshot={"entity_type": "character", "name": "路由角色"},
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
        title="路由页面",
        status="published",
    )
    db_session.add(page)
    await db_session.flush()

    revision = WorldBiblePageRevision(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        page_id=page.id,
        version_number=1,
        snapshot_json={"title": "路由页面"},
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


async def _count_notes(db_session: AsyncSession, novel_id: str) -> int:
    rows = (
        (
            await db_session.execute(
                select(WorldRevisionNote).where(
                    WorldRevisionNote.novel_id == uuid.UUID(hex=novel_id)
                )
            )
        )
        .scalars()
        .all()
    )
    return len(rows)


@pytest_asyncio.fixture
async def seeded_ids(db_session: AsyncSession) -> dict[str, str]:
    """一个作品 + 三种目标修订各一条（地图为已保存版本）。"""
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


async def _put_note(
    async_client: AsyncClient,
    novel_id: str,
    target_kind: str,
    revision_id: str,
    note: str,
) -> tuple[int, dict]:
    resp = await async_client.put(
        f"/api/world/revision-notes?novel_id={novel_id}",
        json={"target_kind": target_kind, "revision_id": revision_id, "note": note},
    )
    body = resp.json() if resp.content else {}
    return resp.status_code, body


async def test_put_note_for_entity_page_map(
    async_client: AsyncClient, seeded_ids: dict[str, str]
) -> None:
    """三种目标类型经 PUT 路由都能写备注并返回 RevisionNoteResponse。"""
    novel_id = seeded_ids["novel_id"]
    for kind in ("entity", "page", "map"):
        status_code, body = await _put_note(
            async_client, novel_id, kind, seeded_ids[kind], f"{kind} 的备注"
        )
        assert status_code == 200
        assert body["target_kind"] == kind
        assert body["revision_id"] == seeded_ids[kind]
        assert body["note"] == f"{kind} 的备注"
        assert body["updated_at"]


async def test_cross_novel_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    seeded_ids: dict[str, str],
) -> None:
    """目标修订不属于当前作品时 404（作品本身存在，404 来自归属校验）。"""
    other_novel_id = uuid.uuid4().hex
    await _create_project(db_session, other_novel_id)

    status_code, _ = await _put_note(
        async_client, other_novel_id, "entity", seeded_ids["entity"], "越权备注"
    )
    assert status_code == 404


async def test_map_candidate_returns_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    seeded_ids: dict[str, str],
) -> None:
    """地图候选版本写备注返回 409。"""
    novel_id = seeded_ids["novel_id"]
    candidate = await _make_map_revision(db_session, novel_id, status="candidate")

    status_code, _ = await _put_note(
        async_client, novel_id, "map", str(candidate.id), "候选备注"
    )
    assert status_code == 409


async def test_too_long_note_returns_422(
    async_client: AsyncClient, seeded_ids: dict[str, str]
) -> None:
    """超过 500 字的备注被请求 schema 拒绝（422）。"""
    status_code, _ = await _put_note(
        async_client,
        seeded_ids["novel_id"],
        "entity",
        seeded_ids["entity"],
        "长" * 501,
    )
    assert status_code == 422


async def test_empty_note_deletes(
    async_client: AsyncClient, db_session: AsyncSession, seeded_ids: dict[str, str]
) -> None:
    """空串删除备注；再查数据库已无该行。"""
    novel_id = seeded_ids["novel_id"]
    revision_id = seeded_ids["page"]

    status_code, body = await _put_note(
        async_client, novel_id, "page", revision_id, "先写一条"
    )
    assert status_code == 200
    assert body["note"] == "先写一条"
    assert await _count_notes(db_session, novel_id) == 1

    status_code, body = await _put_note(async_client, novel_id, "page", revision_id, "")
    assert status_code == 200
    assert body["note"] is None
    assert await _count_notes(db_session, novel_id) == 0


async def test_repeat_write_is_idempotent(
    async_client: AsyncClient, db_session: AsyncSession, seeded_ids: dict[str, str]
) -> None:
    """重复写入同样内容幂等：两次 200 且库里只有一条。"""
    novel_id = seeded_ids["novel_id"]
    revision_id = seeded_ids["entity"]

    first_status, first_body = await _put_note(
        async_client, novel_id, "entity", revision_id, "同样内容"
    )
    second_status, second_body = await _put_note(
        async_client, novel_id, "entity", revision_id, "同样内容"
    )
    assert first_status == second_status == 200
    assert second_body["note"] == first_body["note"] == "同样内容"
    assert await _count_notes(db_session, novel_id) == 1
