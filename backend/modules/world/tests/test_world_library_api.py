"""World library unified list, topic directory and workspace API tests."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models.core import CoreEntity
from modules.world.models.worldbuilding import WorldBiblePage, WorldBiblePageDraft
from modules.world.tests.helpers import publish_bible_draft


async def _create_project(client: AsyncClient, title: str) -> str:
    response = await client.post("/api/projects", json={"title": title})
    assert response.status_code == 200 or response.status_code == 201, response.text
    return response.json()["id"]


async def _create_entity(
    client: AsyncClient,
    novel_id: str,
    *,
    name: str,
    entity_type: str = "location",
    summary: str | None = None,
    status: str = "canonical",
) -> str:
    payload = {
        "novel_id": novel_id,
        "entity_type": entity_type,
        "name": name,
        "status": status,
    }
    if summary is not None:
        payload["summary"] = summary
    response = await client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_free_draft(
    client: AsyncClient,
    novel_id: str,
    *,
    title: str,
    page_type: str = "background",
    free_text: str | None = None,
) -> str:
    payload = {"novel_id": novel_id, "title": title, "page_type": page_type}
    if free_text is not None:
        payload["free_text"] = free_text
    response = await client.post("/api/world/bible/drafts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_topic(
    client: AsyncClient,
    novel_id: str,
    name: str,
    *,
    parent_id: str | None = None,
) -> str:
    payload = {"novel_id": novel_id, "name": name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    response = await client.post("/api/world/library/topics", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _publish(
    client: AsyncClient,
    novel_id: str,
    draft_id: str,
) -> str:
    response = await publish_bible_draft(client, novel_id, draft_id)
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _list_library(
    client: AsyncClient,
    novel_id: str,
    **params,
) -> dict:
    response = await client.get(
        "/api/world/library",
        params={"novel_id": novel_id, **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ============================================================
# Unified list: pagination, merge dedup, filters
# ============================================================


@pytest.mark.asyncio
async def test_library_pagination_covers_all_items(async_client: AsyncClient) -> None:
    novel_id = await _create_project(async_client, "资料分页")
    for index in range(55):
        await _create_entity(
            async_client,
            novel_id,
            name=f"地点{index:02d}",
            summary=f"第 {index} 个地点的概要",
        )

    first = await _list_library(async_client, novel_id, limit=50)
    assert first["total"] == 55
    assert len(first["items"]) == 50
    second = await _list_library(async_client, novel_id, limit=50, skip=50)
    assert len(second["items"]) == 5
    first_ids = {(item["kind"], item["id"]) for item in first["items"]}
    second_ids = {(item["kind"], item["id"]) for item in second["items"]}
    assert first_ids.isdisjoint(second_ids)
    assert len(first_ids | second_ids) == 55


@pytest.mark.asyncio
async def test_library_browse_integrity_at_scale(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """验收：1,000 项混合资料逐页浏览无重复遗漏（ORM 批量播种，避免千次 API 调用）。"""
    novel_id = await _create_project(async_client, "千项资料浏览")
    nid = uuid.UUID(novel_id)
    entities = [
        CoreEntity(
            novel_id=nid,
            entity_type="location",
            name=f"规模地点{idx:03d}",
            status="canonical",
            summary=f"第 {idx} 个地点的概要",
        )
        for idx in range(400)
    ]
    pages = [
        WorldBiblePage(
            novel_id=nid,
            page_type="background",
            page_key=f"scale-page-{idx:03d}",
            title=f"规模页面{idx:03d}",
            status="canonical",
            free_text=f"规模页面 {idx} 的正文。",
        )
        for idx in range(400)
    ]
    drafts = [
        WorldBiblePageDraft(
            novel_id=nid,
            title=f"规模工作稿{idx:03d}",
            page_type="background",
            free_text=f"规模工作稿 {idx} 的正文。",
        )
        for idx in range(200)
    ]
    db_session.add_all([*entities, *pages, *drafts])
    await db_session.commit()

    seen: set[tuple[str, str]] = set()
    skip = 0
    while skip < 1000:
        payload = await _list_library(async_client, novel_id, limit=50, skip=skip)
        assert payload["total"] == 1000
        for item in payload["items"]:
            key = (item["kind"], item["id"])
            assert key not in seen, f"分页出现重复：skip={skip} {key}"
            seen.add(key)
        assert len(payload["items"]) == 50, f"skip={skip} 返回 {len(payload['items'])} 项"
        skip += 50
    assert len(seen) == 1000


@pytest.mark.asyncio
async def test_library_merges_page_and_draft_into_one_item(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "合并工作稿")
    draft_id = await _create_free_draft(
        async_client,
        novel_id,
        title="北境贸易",
        free_text="北境的贸易规则概述。",
    )
    page_id = await _publish(async_client, novel_id, draft_id)
    working_draft = await _create_free_draft(
        async_client,
        novel_id,
        title="未关联页面的工作稿",
        page_type="background",
    )
    # 为已发布页面创建第二份工作稿（page-linked）
    response = await async_client.post(
        "/api/world/bible/drafts",
        json={"novel_id": novel_id, "page_id": page_id},
    )
    assert response.status_code == 201, response.text
    page_draft_id = response.json()["id"]

    library = await _list_library(async_client, novel_id)
    page_items = [item for item in library["items"] if item["id"] == page_id]
    assert len(page_items) == 1
    item = page_items[0]
    assert item["kind"] == "page"
    assert item["working"] is True
    assert item["draft_id"] == page_draft_id
    draft_items = [
        item
        for item in library["items"]
        if item["kind"] == "draft" and item["id"] == working_draft
    ]
    assert len(draft_items) == 1
    assert draft_items[0]["working"] is True
    assert library["total"] == 2


@pytest.mark.asyncio
async def test_library_search_kind_type_state_filters(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "筛选")
    entity_id = await _create_entity(
        async_client,
        novel_id,
        name="洛阳",
        entity_type="location",
        summary="古都洛阳",
    )
    await _create_entity(
        async_client,
        novel_id,
        name="天机阁",
        entity_type="organization",
        summary="江湖势力",
    )
    archived_id = await _create_entity(
        async_client,
        novel_id,
        name="废弃设定",
        entity_type="item",
        summary="已弃用",
        status="deprecated",
    )
    draft_id = await _create_free_draft(async_client, novel_id, title="北境气候")

    default_list = await _list_library(async_client, novel_id)
    assert default_list["total"] == 3  # 归档实体默认不显示
    assert all(item["id"] != archived_id for item in default_list["items"])

    searched = await _list_library(async_client, novel_id, q="洛阳")
    assert searched["total"] == 1
    assert searched["items"][0]["id"] == entity_id

    by_type = await _list_library(async_client, novel_id, item_type="organization")
    assert by_type["total"] == 1
    assert by_type["items"][0]["title"] == "天机阁"

    by_kind = await _list_library(async_client, novel_id, kind="entity")
    assert by_kind["total"] == 2

    working = await _list_library(async_client, novel_id, state="working")
    assert working["total"] == 1
    assert working["items"][0]["kind"] == "draft"
    assert working["items"][0]["id"] == draft_id

    archived = await _list_library(async_client, novel_id, state="archived")
    assert archived["total"] == 1
    assert archived["items"][0]["id"] == archived_id


@pytest.mark.asyncio
async def test_library_sort_options(async_client: AsyncClient) -> None:
    novel_id = await _create_project(async_client, "排序")
    await _create_entity(async_client, novel_id, name="Cedar")
    await _create_entity(async_client, novel_id, name="Alpha")
    await _create_entity(async_client, novel_id, name="Birch")

    by_title = await _list_library(async_client, novel_id, sort="title")
    titles = [item["title"] for item in by_title["items"]]
    assert titles == ["Alpha", "Birch", "Cedar"]


# ============================================================
# Topic directory
# ============================================================


@pytest.mark.asyncio
async def test_topic_tree_nesting_rename_reorder_archive(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "主题目录")
    geo_id = await _create_topic(async_client, novel_id, "地理")
    power_id = await _create_topic(async_client, novel_id, "势力格局")
    north_id = await _create_topic(async_client, novel_id, "北境", parent_id=geo_id)

    tree = (
        await async_client.get(
            "/api/world/library/topics",
            params={"novel_id": novel_id},
        )
    ).json()["topics"]
    assert [node["name"] for node in tree] == ["地理", "势力格局"]
    geo_node = tree[0]
    assert geo_node["children"][0]["id"] == north_id
    assert geo_node["member_count"] == 0

    renamed = await async_client.patch(
        f"/api/world/library/topics/{north_id}",
        params={"novel_id": novel_id},
        json={"novel_id": novel_id, "name": "北境与东境"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "北境与东境"

    new_geo = await _create_topic(async_client, novel_id, "新地理")
    reordered = await async_client.post(
        "/api/world/library/topics/reorder",
        json={
            "novel_id": novel_id,
            "parent_id": None,
            "ordered_ids": [new_geo, geo_id, power_id],
        },
    )
    assert reordered.status_code == 200
    tree = (
        await async_client.get(
            "/api/world/library/topics",
            params={"novel_id": novel_id},
        )
    ).json()["topics"]
    assert [node["name"] for node in tree] == ["新地理", "地理", "势力格局"]

    archived = await async_client.post(
        f"/api/world/library/topics/{geo_id}/archive",
        json={"novel_id": novel_id, "archived": True},
    )
    assert archived.status_code == 200
    tree = (
        await async_client.get(
            "/api/world/library/topics",
            params={"novel_id": novel_id},
        )
    ).json()["topics"]
    # 归档主题从默认目录隐藏，但其子主题与资料保持可见（提升为根级）
    assert [node["name"] for node in tree] == ["北境与东境", "新地理", "势力格局"]
    full_tree = (
        await async_client.get(
            "/api/world/library/topics",
            params={"novel_id": novel_id, "include_archived": True},
        )
    ).json()["topics"]
    geo_node = next(node for node in full_tree if node["id"] == geo_id)
    assert geo_node["status"] == "archived"
    assert geo_node["children"][0]["status"] == "active"


@pytest.mark.asyncio
async def test_topic_move_rejects_cycles(async_client: AsyncClient) -> None:
    novel_id = await _create_project(async_client, "主题防环")
    root_id = await _create_topic(async_client, novel_id, "根")
    child_id = await _create_topic(async_client, novel_id, "子", parent_id=root_id)

    self_move = await async_client.post(
        f"/api/world/library/topics/{root_id}/move",
        json={"novel_id": novel_id, "parent_id": root_id},
    )
    assert self_move.status_code == 400
    assert self_move.json()["error"] == "topic_cycle"

    cycle_move = await async_client.post(
        f"/api/world/library/topics/{root_id}/move",
        json={"novel_id": novel_id, "parent_id": child_id},
    )
    assert cycle_move.status_code == 400
    assert cycle_move.json()["error"] == "topic_cycle"

    valid_move = await async_client.post(
        f"/api/world/library/topics/{child_id}/move",
        json={"novel_id": novel_id, "parent_id": None},
    )
    assert valid_move.status_code == 200
    assert valid_move.json()["parent_id"] is None


@pytest.mark.asyncio
async def test_topic_member_multi_reference_and_filter(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "多主题引用")
    entity_id = await _create_entity(async_client, novel_id, name="北境军镇")
    geo_id = await _create_topic(async_client, novel_id, "地理")
    war_id = await _create_topic(async_client, novel_id, "战争线")
    north_id = await _create_topic(async_client, novel_id, "北境", parent_id=geo_id)

    for topic_id in (north_id, war_id):
        added = await async_client.post(
            f"/api/world/library/topics/{topic_id}/members",
            json={
                "novel_id": novel_id,
                "target_kind": "entity",
                "target_id": entity_id,
            },
        )
        assert added.status_code == 201
        assert added.json()["added"] is True

    # 幂等：重复添加不报错也不重复
    repeat = await async_client.post(
        f"/api/world/library/topics/{war_id}/members",
        json={
            "novel_id": novel_id,
            "target_kind": "entity",
            "target_id": entity_id,
        },
    )
    assert repeat.status_code == 201
    assert repeat.json()["added"] is False

    memberships = (
        await async_client.get(
            "/api/world/library/memberships",
            params={
                "novel_id": novel_id,
                "target_kind": "entity",
                "target_id": entity_id,
            },
        )
    ).json()["topic_ids"]
    assert set(memberships) == {north_id, war_id}

    # 子主题成员计入父主题子树过滤
    subtree = await _list_library(async_client, novel_id, topic_id=geo_id)
    assert subtree["total"] == 1
    assert subtree["items"][0]["id"] == entity_id
    exact = await _list_library(
        async_client, novel_id, topic_id=geo_id, topic_scope="topic"
    )
    assert exact["total"] == 0

    removed = await async_client.delete(
        f"/api/world/library/topics/{war_id}/members/entity/{entity_id}",
        params={"novel_id": novel_id},
    )
    assert removed.status_code == 200
    assert removed.json()["removed"] is True

    tree = (
        await async_client.get(
            "/api/world/library/topics",
            params={"novel_id": novel_id},
        )
    ).json()["topics"]
    war_node = next(node for node in tree if node["id"] == war_id)
    geo_node = next(node for node in tree if node["id"] == geo_id)
    north_child = next(child for child in geo_node["children"] if child["id"] == north_id)
    assert war_node["member_count"] == 0
    assert north_child["member_count"] == 1


@pytest.mark.asyncio
async def test_topic_operations_isolated_by_novel(async_client: AsyncClient) -> None:
    novel_a = await _create_project(async_client, "项目A")
    novel_b = await _create_project(async_client, "项目B")
    topic_a = await _create_topic(async_client, novel_a, "A的主题")
    entity_b = await _create_entity(async_client, novel_b, name="B的资料")

    tree_b = (
        await async_client.get(
            "/api/world/library/topics",
            params={"novel_id": novel_b},
        )
    ).json()["topics"]
    assert tree_b == []

    cross = await async_client.post(
        f"/api/world/library/topics/{topic_a}/members",
        json={
            "novel_id": novel_b,
            "target_kind": "entity",
            "target_id": entity_b,
        },
    )
    assert cross.status_code == 404

    cross_patch = await async_client.patch(
        f"/api/world/library/topics/{topic_a}",
        params={"novel_id": novel_b},
        json={"novel_id": novel_b, "name": "越权改名"},
    )
    assert cross_patch.status_code == 404


# ============================================================
# Author workspace
# ============================================================


@pytest.mark.asyncio
async def test_workspace_recents_favorites_and_overview(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "工作区")
    first_id = await _create_entity(async_client, novel_id, name="常用设定")
    second_id = await _create_entity(async_client, novel_id, name="备用设定")
    unclassified_id = await _create_entity(async_client, novel_id, name="未归类设定")
    topic_id = await _create_topic(async_client, novel_id, "已归类主题")
    await async_client.post(
        f"/api/world/library/topics/{topic_id}/members",
        json={
            "novel_id": novel_id,
            "target_kind": "entity",
            "target_id": first_id,
        },
    )

    unclassified_list = await _list_library(async_client, novel_id, unclassified=True)
    unclassified_ids = {item["id"] for item in unclassified_list["items"]}
    assert unclassified_list["total"] == 2
    assert unclassified_ids == {second_id, unclassified_id}

    recorded = await async_client.post(
        "/api/world/library/recents",
        json={
            "novel_id": novel_id,
            "target_kind": "entity",
            "target_id": first_id,
        },
    )
    assert recorded.status_code == 204

    favorited = await async_client.post(
        "/api/world/library/favorites",
        json={
            "novel_id": novel_id,
            "target_kind": "entity",
            "target_id": second_id,
        },
    )
    assert favorited.status_code == 200
    assert favorited.json()["favorited"] is True

    favorite_filtered = await _list_library(async_client, novel_id, favorite=True)
    assert favorite_filtered["total"] == 1
    assert favorite_filtered["items"][0]["is_favorite"] is True

    recent_sorted = await _list_library(async_client, novel_id, sort="recent")
    assert recent_sorted["items"][0]["id"] == first_id
    assert recent_sorted["items"][1]["id"] != first_id

    overview = (
        await async_client.get(
            "/api/world/library/overview",
            params={"novel_id": novel_id},
        )
    ).json()
    assert overview["totals"]["all"] == 3
    assert overview["totals"]["unclassified"] == 2
    assert overview["totals"]["entity"] == 3
    assert overview["totals"]["favorites"] == 1
    assert overview["recent_items"][0]["id"] == first_id
    assert [item["id"] for item in overview["favorite_items"]] == [second_id]
    assert {facet["type"] for facet in overview["type_facets"]} == {"location"}
    assert all(item["working"] is False for item in overview["working_items"])

    unfavored = await async_client.delete(
        "/api/world/library/favorites",
        params={
            "novel_id": novel_id,
            "target_kind": "entity",
            "target_id": second_id,
        },
    )
    assert unfavored.status_code == 200
    assert unfavored.json()["favorited"] is False
    favorite_filtered = await _list_library(async_client, novel_id, favorite=True)
    assert favorite_filtered["total"] == 0

    # 未归类资料通过过滤始终可找到
    found = await _list_library(async_client, novel_id, q="未归类")
    assert found["total"] == 1
    assert found["items"][0]["id"] == unclassified_id


@pytest.mark.asyncio
async def test_view_prefs_roundtrip(async_client: AsyncClient) -> None:
    novel_id = await _create_project(async_client, "视图偏好")
    empty = (
        await async_client.get(
            "/api/world/library/view-prefs",
            params={"novel_id": novel_id},
        )
    ).json()
    assert empty["view_prefs"] == {}

    updated = await async_client.put(
        "/api/world/library/view-prefs",
        json={"novel_id": novel_id, "view_prefs": {"layout": "list", "sort": "title"}},
    )
    assert updated.status_code == 200
    assert updated.json()["view_prefs"]["layout"] == "list"

    reloaded = (
        await async_client.get(
            "/api/world/library/view-prefs",
            params={"novel_id": novel_id},
        )
    ).json()
    assert reloaded["view_prefs"] == {"layout": "list", "sort": "title"}


# ============================================================
# Draft publish conversion
# ============================================================


@pytest.mark.asyncio
async def test_publish_converts_draft_workspace_refs_to_page(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "发布转换")
    draft_id = await _create_free_draft(async_client, novel_id, title="南疆药典")
    topic_id = await _create_topic(async_client, novel_id, "医术")
    added = await async_client.post(
        f"/api/world/library/topics/{topic_id}/members",
        json={
            "novel_id": novel_id,
            "target_kind": "draft",
            "target_id": draft_id,
        },
    )
    assert added.status_code == 201
    await async_client.post(
        "/api/world/library/favorites",
        json={
            "novel_id": novel_id,
            "target_kind": "draft",
            "target_id": draft_id,
        },
    )
    await async_client.post(
        "/api/world/library/recents",
        json={
            "novel_id": novel_id,
            "target_kind": "draft",
            "target_id": draft_id,
        },
    )

    page_id = await _publish(async_client, novel_id, draft_id)

    memberships = (
        await async_client.get(
            "/api/world/library/memberships",
            params={
                "novel_id": novel_id,
                "target_kind": "page",
                "target_id": page_id,
            },
        )
    ).json()["topic_ids"]
    assert memberships == [topic_id]

    tree = (
        await async_client.get(
            "/api/world/library/topics",
            params={"novel_id": novel_id},
        )
    ).json()["topics"]
    assert tree[0]["member_count"] == 1

    favorite_filtered = await _list_library(async_client, novel_id, favorite=True)
    assert favorite_filtered["total"] == 1
    assert favorite_filtered["items"][0]["id"] == page_id

    recent_sorted = await _list_library(async_client, novel_id, sort="recent")
    assert recent_sorted["items"][0]["id"] == page_id
