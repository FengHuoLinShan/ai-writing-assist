"""世界改动记录时间线测试（路线图阶段 0 · P2）。

覆盖 §8 的 test_world_change_history.py 要求：三类混排；同一时间戳排序稳定；
游标翻页不重不漏；按类型筛选；作品之间隔离；地图只取已保存行
（有 confirmation_id 的排除）；带上备注；已移除对象标注；坏游标 422；
查询次数恒定（事件计数断言）。末尾补路由层的 HTTP 契约用例。
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.models import (
    CoreEntity,
    EntityRevision,
    WorldBiblePage,
    WorldBiblePageRevision,
    WorldRevisionNote,
)
from modules.world.services.revision_history_service import WorldChangeHistoryService
from tests.utils import _create_project

_service = WorldChangeHistoryService()

_BASE_TS = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


def _ts(seconds: int) -> datetime:
    return _BASE_TS + timedelta(seconds=seconds)


async def _seed_entity_revision(
    db_session: AsyncSession,
    novel_id: str,
    *,
    created_at: datetime,
    name: str = "实体甲",
    entity_status: str = "canonical",
    reason: str = "manual_update",
    writing_chapter_index: int | None = None,
    change_summary: dict | None = None,
    dangling: bool = False,
) -> EntityRevision:
    """创建实体与其修订；``dangling=True`` 时不建实体行，模拟物理删除后的孤立修订。"""
    entity_id = uuid.uuid4()
    if not dangling:
        db_session.add(
            CoreEntity(
                id=entity_id,
                novel_id=uuid.UUID(hex=novel_id),
                entity_type="character",
                name=name,
                status=entity_status,
            )
        )
    revision = EntityRevision(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_id=entity_id,
        snapshot={"entity_type": "character", "name": name},
        revision_reason=reason,
        created_at=created_at,
        writing_chapter_index=writing_chapter_index,
        change_summary=change_summary,
    )
    db_session.add(revision)
    await db_session.flush()
    return revision


async def _seed_page_revision(
    db_session: AsyncSession,
    novel_id: str,
    *,
    created_at: datetime,
    title: str = "页面甲",
    page_status: str = "published",
    reason: str = "manual_publish",
    version_number: int = 1,
) -> WorldBiblePageRevision:
    page = WorldBiblePage(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        page_type="lore",
        page_key=f"page-{uuid.uuid4().hex[:8]}",
        title=title,
        status=page_status,
    )
    db_session.add(page)
    await db_session.flush()

    revision = WorldBiblePageRevision(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        page_id=page.id,
        version_number=version_number,
        snapshot_json={"title": title},
        revision_digest=f"digest-{uuid.uuid4().hex[:12]}",
        revision_reason=reason,
        created_at=created_at,
    )
    db_session.add(revision)
    await db_session.flush()
    return revision


async def _seed_map_revision(
    db_session: AsyncSession,
    novel_id: str,
    *,
    created_at: datetime,
    node_title: str = "世界地图",
    status: str = "saved",
    confirmation_id: uuid.UUID | None = None,
) -> MapAtlasRevision:
    node = MapAtlasNode(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        semantic_key=f"world-{uuid.uuid4().hex[:8]}",
        title=node_title,
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
        geometry_hash=f"hash-{uuid.uuid4().hex[:12]}",
        problems=[],
        confirmation_id=confirmation_id,
        created_at=created_at,
    )
    db_session.add(revision)
    await db_session.flush()
    return revision


def _make_select_counter(bucket: list[str]):
    def _record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            bucket.append(statement)

    return _record


# ============================================================
# 服务层
# ============================================================


async def test_three_kinds_merged_in_desc_order(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    """三类混排按时间倒序，字段按类型正确解析。"""
    novel_id = project_novel_id
    entity_rev = await _seed_entity_revision(
        db_session,
        novel_id,
        created_at=_ts(1),
        name="实体甲",
        writing_chapter_index=7,
        change_summary={
            "fields": ["name", "summary"],
            "restored_from_revision_id": None,
        },
    )
    page_rev = await _seed_page_revision(
        db_session, novel_id, created_at=_ts(2), title="页面甲"
    )
    map_rev = await _seed_map_revision(db_session, novel_id, created_at=_ts(3))

    response = await _service.list(db_session, novel_id=novel_id)

    assert [item.kind for item in response.items] == ["map", "page", "entity"]
    assert [item.revision_id for item in response.items] == [
        str(map_rev.id),
        str(page_rev.id),
        str(entity_rev.id),
    ]
    map_item, page_item, entity_item = response.items
    assert map_item.target_title == "世界地图"
    assert map_item.reason is None
    assert map_item.version_number is None
    assert page_item.target_title == "页面甲"
    assert page_item.version_number == 1
    assert page_item.reason == "manual_publish"
    assert entity_item.target_title == "实体甲"
    assert entity_item.reason == "manual_update"
    assert entity_item.writing_chapter_index == 7
    assert entity_item.changed_fields == ["name", "summary"]
    assert entity_item.target_state == "active"
    assert response.next_cursor is None
    for item in response.items:
        assert item.created_at.tzinfo is not None


async def test_same_timestamp_order_is_stable(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    """同一时间戳：先按 kind 倒序，同 kind 再按 id 倒序，结果确定。"""
    novel_id = project_novel_id
    ts = _ts(10)
    entity_rev = await _seed_entity_revision(db_session, novel_id, created_at=ts)
    page_rev = await _seed_page_revision(db_session, novel_id, created_at=ts)
    map_rev = await _seed_map_revision(db_session, novel_id, created_at=ts)

    response = await _service.list(db_session, novel_id=novel_id)
    assert [item.revision_id for item in response.items] == [
        str(page_rev.id),
        str(map_rev.id),
        str(entity_rev.id),
    ]

    first = await _seed_entity_revision(db_session, novel_id, created_at=ts)
    second = await _seed_entity_revision(db_session, novel_id, created_at=ts)
    expected = sorted(
        [first, second, entity_rev],
        key=lambda rev: rev.id.hex,
        reverse=True,
    )
    entity_only = await _service.list(db_session, novel_id=novel_id, kinds=["entity"])
    assert [item.revision_id for item in entity_only.items] == [
        str(rev.id) for rev in expected
    ]


async def test_cursor_pagination_no_overlap_no_gap(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    """游标翻页按 (created_at, kind, id) 倒序不重不漏。"""
    novel_id = project_novel_id
    revisions: list[str] = []
    for index in range(7):
        if index % 3 == 0:
            rev = await _seed_entity_revision(db_session, novel_id, created_at=_ts(index))
        elif index % 3 == 1:
            rev = await _seed_page_revision(db_session, novel_id, created_at=_ts(index))
        else:
            rev = await _seed_map_revision(db_session, novel_id, created_at=_ts(index))
        revisions.append(str(rev.id))

    expected = list(reversed(revisions))

    collected: list[str] = []
    cursor = None
    pages = 0
    while True:
        response = await _service.list(
            db_session, novel_id=novel_id, limit=3, cursor=cursor
        )
        collected.extend(item.revision_id for item in response.items)
        pages += 1
        if response.next_cursor is None:
            break
        cursor = response.next_cursor
        assert pages <= 5

    assert collected == expected
    assert len(collected) == len(set(collected))
    assert pages == 3


async def test_filter_by_kind_and_invalid_kind(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    """kinds 筛选生效；非法取值 422。"""
    novel_id = project_novel_id
    await _seed_entity_revision(db_session, novel_id, created_at=_ts(1))
    await _seed_page_revision(db_session, novel_id, created_at=_ts(2))
    await _seed_map_revision(db_session, novel_id, created_at=_ts(3))

    only_map = await _service.list(db_session, novel_id=novel_id, kinds=["map"])
    assert [item.kind for item in only_map.items] == ["map"]

    entity_page = await _service.list(
        db_session, novel_id=novel_id, kinds=["entity", "page"]
    )
    assert [item.kind for item in entity_page.items] == ["page", "entity"]

    with pytest.raises(ValidationError) as exc_info:
        await _service.list(db_session, novel_id=novel_id, kinds=["banana"])
    assert exc_info.value.status_code == 422


async def test_novel_isolation(
    db_session: AsyncSession, two_projects: tuple[str, str]
) -> None:
    """时间线只包含当前作品自己的修订。"""
    novel_a, novel_b = two_projects
    entity_rev = await _seed_entity_revision(db_session, novel_a, created_at=_ts(1))
    await _seed_page_revision(db_session, novel_b, created_at=_ts(2))
    await _seed_map_revision(db_session, novel_b, created_at=_ts(3))

    response_a = await _service.list(db_session, novel_id=novel_a)
    assert [item.revision_id for item in response_a.items] == [str(entity_rev.id)]

    response_b = await _service.list(db_session, novel_id=novel_b)
    assert {item.kind for item in response_b.items} == {"page", "map"}


async def test_map_only_saved_rows_without_confirmation(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    """地图只取 saved 且无 confirmation_id 的行。"""
    novel_id = project_novel_id
    saved = await _seed_map_revision(db_session, novel_id, created_at=_ts(1))
    await _seed_map_revision(db_session, novel_id, created_at=_ts(2), status="candidate")
    await _seed_map_revision(
        db_session, novel_id, created_at=_ts(3), confirmation_id=uuid.uuid4()
    )
    await _seed_map_revision(db_session, novel_id, created_at=_ts(4), status="rejected")

    response = await _service.list(db_session, novel_id=novel_id, kinds=["map"])
    assert [item.revision_id for item in response.items] == [str(saved.id)]


async def test_change_notes_attached(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    """备注经 LEFT JOIN 带出，无备注的条目为空。"""
    novel_id = project_novel_id
    entity_rev = await _seed_entity_revision(db_session, novel_id, created_at=_ts(1))
    page_rev = await _seed_page_revision(db_session, novel_id, created_at=_ts(2))
    map_rev = await _seed_map_revision(db_session, novel_id, created_at=_ts(3))
    db_session.add(
        WorldRevisionNote(
            novel_id=uuid.UUID(hex=novel_id),
            target_kind="entity",
            revision_id=entity_rev.id,
            note="实体备注",
        )
    )
    db_session.add(
        WorldRevisionNote(
            novel_id=uuid.UUID(hex=novel_id),
            target_kind="map",
            revision_id=map_rev.id,
            note="地图备注",
        )
    )
    await db_session.flush()

    response = await _service.list(db_session, novel_id=novel_id)
    by_kind = {item.kind: item for item in response.items}
    assert by_kind["entity"].change_note == "实体备注"
    assert by_kind["map"].change_note == "地图备注"
    assert by_kind["page"].change_note is None
    assert str(page_rev.id) in {item.revision_id for item in response.items}


async def test_removed_entity_marked_and_still_named(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    """已移除（历史态）实体标注 removed 且仍给出名称；孤立修订从快照取名称。"""
    novel_id = project_novel_id
    removed = await _seed_entity_revision(
        db_session,
        novel_id,
        created_at=_ts(1),
        name="旧门派",
        entity_status="deprecated",
    )
    dangling = await _seed_entity_revision(
        db_session, novel_id, created_at=_ts(2), name="幽灵对象", dangling=True
    )
    active = await _seed_entity_revision(
        db_session, novel_id, created_at=_ts(3), name="现役对象"
    )

    response = await _service.list(db_session, novel_id=novel_id)
    by_id = {item.revision_id: item for item in response.items}
    assert by_id[str(removed.id)].target_state == "removed"
    assert by_id[str(removed.id)].target_title == "旧门派"
    assert by_id[str(dangling.id)].target_state == "removed"
    assert by_id[str(dangling.id)].target_title == "幽灵对象"
    assert by_id[str(active.id)].target_state == "active"


async def test_bad_cursor_returns_422(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    """坏游标（非 base64 / 非 JSON / 缺键 / kind 非法）一律 422。"""
    novel_id = project_novel_id
    await _seed_entity_revision(db_session, novel_id, created_at=_ts(1))

    payload = json.dumps(
        {
            "created_at": _ts(1).isoformat(),
            "id": str(uuid.uuid4()),
            "kind": "banana",
        }
    )
    invalid_kind_cursor = base64.urlsafe_b64encode(payload.encode()).decode("ascii")
    bad_cursors = [
        "!!!not-base64!!!",
        base64.urlsafe_b64encode(b"not json").decode("ascii"),
        base64.urlsafe_b64encode(json.dumps({"foo": 1}).encode()).decode("ascii"),
        invalid_kind_cursor,
    ]
    for cursor in bad_cursors:
        with pytest.raises(ValidationError) as exc_info:
            await _service.list(db_session, novel_id=novel_id, cursor=cursor)
        assert exc_info.value.status_code == 422


async def test_limit_bounds(db_session: AsyncSession, project_novel_id: str) -> None:
    """limit 范围 1–50；越界 422。"""
    novel_id = project_novel_id
    for limit in (0, 51):
        with pytest.raises(ValidationError) as exc_info:
            await _service.list(db_session, novel_id=novel_id, limit=limit)
        assert exc_info.value.status_code == 422

    single = await _service.list(db_session, novel_id=novel_id, limit=1)
    assert single.items == []
    full = await _service.list(db_session, novel_id=novel_id, limit=50)
    assert full.items == []


async def test_query_count_is_constant(
    db_session: AsyncSession, project_novel_id: str
) -> None:
    """单次 list 固定一条 SELECT，不随条目数增长（无逐条查询）。"""
    novel_id = project_novel_id
    await _seed_entity_revision(db_session, novel_id, created_at=_ts(1))
    await _seed_page_revision(db_session, novel_id, created_at=_ts(2))

    select_count: list[str] = []
    listener = _make_select_counter(select_count)
    sync_connection = db_session.bind.sync_connection
    event.listen(sync_connection, "before_cursor_execute", listener)
    try:
        await _service.list(db_session, novel_id=novel_id)
        first_call = len(select_count)
        select_count.clear()

        for index in range(3, 11):
            await _seed_entity_revision(db_session, novel_id, created_at=_ts(index))

        await _service.list(db_session, novel_id=novel_id)
        second_call = len(select_count)
    finally:
        event.remove(sync_connection, "before_cursor_execute", listener)

    assert first_call == second_call == 1


# ============================================================
# 路由层（HTTP 契约）
# ============================================================


@pytest_asyncio.fixture
async def seeded_novel(db_session: AsyncSession) -> dict[str, str]:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    entity_rev = await _seed_entity_revision(
        db_session, novel_id, created_at=_ts(1), name="路由实体"
    )
    page_rev = await _seed_page_revision(
        db_session, novel_id, created_at=_ts(2), title="路由页面"
    )
    map_rev = await _seed_map_revision(db_session, novel_id, created_at=_ts(3))
    return {
        "novel_id": novel_id,
        "entity": str(entity_rev.id),
        "page": str(page_rev.id),
        "map": str(map_rev.id),
    }


async def test_change_history_route_merges_and_paginates(
    async_client: AsyncClient, seeded_novel: dict[str, str]
) -> None:
    """GET /change-history：三类混排、可重复 kinds、游标翻页。"""
    novel_id = seeded_novel["novel_id"]
    resp = await async_client.get(f"/api/world/change-history?novel_id={novel_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert [item["kind"] for item in body["items"]] == ["map", "page", "entity"]
    assert "total" not in body

    filtered = await async_client.get(
        f"/api/world/change-history?novel_id={novel_id}&kinds=map&kinds=entity"
    )
    assert filtered.status_code == 200
    assert [item["kind"] for item in filtered.json()["items"]] == ["map", "entity"]

    paged = await async_client.get(
        f"/api/world/change-history?novel_id={novel_id}&limit=2"
    )
    assert paged.status_code == 200
    first_page = paged.json()
    assert [item["kind"] for item in first_page["items"]] == ["map", "page"]
    assert first_page["next_cursor"]

    second_page_resp = await async_client.get(
        f"/api/world/change-history?novel_id={novel_id}&limit=2"
        f"&cursor={first_page['next_cursor']}"
    )
    assert second_page_resp.status_code == 200
    second_page = second_page_resp.json()
    assert [item["kind"] for item in second_page["items"]] == ["entity"]
    assert second_page["next_cursor"] is None


async def test_change_history_route_rejects_bad_params(
    async_client: AsyncClient, seeded_novel: dict[str, str]
) -> None:
    """非法 kinds / 坏游标 / 越界 limit 都返回 422。"""
    novel_id = seeded_novel["novel_id"]
    bad_kind = await async_client.get(
        f"/api/world/change-history?novel_id={novel_id}&kinds=banana"
    )
    assert bad_kind.status_code == 422

    bad_cursor = await async_client.get(
        f"/api/world/change-history?novel_id={novel_id}&cursor=zzz-bad"
    )
    assert bad_cursor.status_code == 422

    for limit in ("0", "51"):
        bad_limit = await async_client.get(
            f"/api/world/change-history?novel_id={novel_id}&limit={limit}"
        )
        assert bad_limit.status_code == 422


async def test_change_history_route_novel_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
    seeded_novel: dict[str, str],
) -> None:
    """不存在的项目 404；另一部空作品返回空列表而不是别人的记录。"""
    missing = await async_client.get(
        f"/api/world/change-history?novel_id={uuid.uuid4().hex}"
    )
    assert missing.status_code == 404

    other_novel_id = uuid.uuid4().hex
    await _create_project(db_session, other_novel_id)
    empty = await async_client.get(f"/api/world/change-history?novel_id={other_novel_id}")
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "next_cursor": None}
