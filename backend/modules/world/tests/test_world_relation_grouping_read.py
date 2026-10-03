"""世界库关系分组读模型测试（G0 契约：视角匹配方向、去重、未关联与分页）。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from modules.world.models import CoreEntity, EntityRelation
from modules.world.services.worldbuilding.world_library_service import (
    WorldLibraryService,
)
from modules.world.tests.helpers import _create_project

_service = WorldLibraryService()


async def _entity(
    db: AsyncSession,
    novel_id: str,
    entity_type: str,
    name: str,
    *,
    status: str = "canonical",
    aliases: list[dict] | None = None,
) -> CoreEntity:
    entity = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_type=entity_type,
        name=name,
        status=status,
        summary=f"{name}的概要",
        content_json={"aliases": aliases or []},
    )
    db.add(entity)
    await db.flush()
    return entity


async def _relation(
    db: AsyncSession,
    novel_id: str,
    source: CoreEntity,
    target: CoreEntity,
    relation_type: str,
    *,
    relation_kind: str = "social",
    status: str = "canonical",
) -> EntityRelation:
    relation = EntityRelation(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        source_id=source.id,
        target_id=target.id,
        relation_type=relation_type,
        relation_kind=relation_kind,
        status=status,
        strength=0.8,
    )
    db.add(relation)
    await db.flush()
    return relation


async def _prepare(db: AsyncSession) -> str:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session=db, novel_id=novel_id)
    return novel_id


# ============================================================
# list_relation_groups：四个预设的方向语义
# ============================================================


async def test_affiliation_view_counts_only_group_at_target(db_session) -> None:
    novel_id = await _prepare(db_session)
    faction = await _entity(db_session, novel_id, "faction", "塔罗会")
    org = await _entity(db_session, novel_id, "organization", "值夜者")
    member = await _entity(db_session, novel_id, "character", "克莱恩")
    leader = await _entity(db_session, novel_id, "character", "奥黛丽")
    reversed_side = await _entity(db_session, novel_id, "character", "邓恩")
    await _entity(db_session, novel_id, "item", "魔药")
    await _relation(db_session, novel_id, member, faction, "member_of")
    await _relation(db_session, novel_id, leader, org, "leader_of")
    # 反向：faction 在 source 端的 member_of 不构成 affiliation 成员。
    await _relation(db_session, novel_id, faction, reversed_side, "member_of")

    page = await _service.list_relation_groups(
        db_session, novel_id, group_view="affiliation"
    )

    items = {(item.id, item.entity_type): item.member_count for item in page.items}
    assert items == {
        (str(faction.id), "faction"): 1,
        (str(org.id), "organization"): 1,
    }
    # 邓恩没有有效归属 → 未关联；魔药不在成员类型范围内。
    assert page.unlinked_total == 1
    assert page.total == 2
    assert [view.key for view in page.views] == [
        "affiliation",
        "location",
        "possessions",
        "event",
    ]


async def test_location_view_matches_both_directions_and_member_types_open(
    db_session,
) -> None:
    novel_id = await _prepare(db_session)
    city = await _entity(db_session, novel_id, "location", "贝克兰德")
    house = await _entity(db_session, novel_id, "location", "霍尔庄园")
    sub = await _entity(db_session, novel_id, "location", "地下街区")
    person = await _entity(db_session, novel_id, "character", "克莱恩")
    item = await _entity(db_session, novel_id, "item", "怀表")
    bystander = await _entity(db_session, novel_id, "character", "路人甲")
    await _relation(
        db_session, novel_id, person, city, "located_at", relation_kind="spatial"
    )
    # contains：group_side=source → 组在 source 端。
    await _relation(db_session, novel_id, city, item, "contains", relation_kind="spatial")
    await _relation(
        db_session, novel_id, sub, city, "located_in", relation_kind="spatial"
    )
    # 反向 contains：组端落在 character 上，不是合法 location 组 → 不匹配。
    await _relation(
        db_session, novel_id, bystander, house, "contains", relation_kind="spatial"
    )
    # member_of 不是 location 视角规则。
    faction = await _entity(db_session, novel_id, "faction", "教会")
    await _relation(db_session, novel_id, person, faction, "member_of")

    page = await _service.list_relation_groups(
        db_session, novel_id, group_view="location"
    )

    counts = {item.id: item.member_count for item in page.items}
    # sub 也是 location → 同样是组对象（零成员组）。
    assert counts == {str(city.id): 3, str(house.id): 0, str(sub.id): 0}
    # member_types=None → 全类型口径：有效成员 = person/item/sub；city、
    # house 自身不是任何组的成员端，路人甲与教会（member_of 非 location
    # 规则）也都未关联。
    assert page.unlinked_total == 4


async def test_possessions_view_counts_items_and_dedupes(db_session) -> None:
    novel_id = await _prepare(db_session)
    hero = await _entity(db_session, novel_id, "character", "克莱恩")
    other_char = await _entity(db_session, novel_id, "character", "奥黛丽")
    sword = await _entity(db_session, novel_id, "item", "霜华剑")
    amulet = await _entity(db_session, novel_id, "artifact", "护符")
    lost = await _entity(db_session, novel_id, "resource", "金币")
    location = await _entity(db_session, novel_id, "location", "教堂")
    await _relation(
        db_session, novel_id, sword, hero, "belongs_to", relation_kind="state"
    )
    # 同一成员多条匹配关系（belongs_to + 携带）只计 1 个成员；携带规则的
    # 组在 source 端。
    await _relation(db_session, novel_id, hero, sword, "携带", relation_kind="spatial")
    await _relation(db_session, novel_id, hero, amulet, "携带", relation_kind="spatial")
    # belongs_to 指向 location：target 端不是 character 组 → 不算。
    await _relation(
        db_session, novel_id, lost, location, "belongs_to", relation_kind="state"
    )

    page = await _service.list_relation_groups(
        db_session, novel_id, group_view="possessions"
    )

    counts = {item.id: item.member_count for item in page.items}
    # character 都是 possessions 组对象；奥黛丽是零成员组。
    assert counts == {str(hero.id): 2, str(other_char.id): 0}
    # 未关联口径 = item/object/artifact/resource：金币未关联（关系落在了
    # 非法组端）；character 不在范围内。
    assert page.unlinked_total == 1


async def test_event_view_participation_direction(db_session) -> None:
    novel_id = await _prepare(db_session)
    event_group = await _entity(db_session, novel_id, "event", "红祭司之夜")
    p1 = await _entity(db_session, novel_id, "character", "克莱恩")
    p2 = await _entity(db_session, novel_id, "character", "奥黛丽")
    p3 = await _entity(db_session, novel_id, "character", "邓恩")
    await _entity(db_session, novel_id, "character", "路人乙")
    item = await _entity(db_session, novel_id, "item", "蜡烛")
    await _relation(
        db_session, novel_id, p1, event_group, "participates_in", relation_kind="state"
    )
    await _relation(db_session, novel_id, p2, event_group, "参与", relation_kind="state")
    # 反向：事件在 source 端参与人物，不算该人物的成员资格。
    await _relation(db_session, novel_id, event_group, p3, "参与", relation_kind="state")
    # 物品不是事件参与规则的合法成员类型。
    await _relation(
        db_session, novel_id, item, event_group, "participates_in", relation_kind="state"
    )

    page = await _service.list_relation_groups(db_session, novel_id, group_view="event")

    counts = {item.id: item.member_count for item in page.items}
    assert counts == {str(event_group.id): 2}
    # p3 与路人均未关联；item 不在 character 口径内。
    assert page.unlinked_total == 2


# ============================================================
# 去重、跨组复用、零成员组与排除口径
# ============================================================


async def test_zero_member_groups_kept_and_invalid_links_excluded(db_session) -> None:
    novel_id = await _prepare(db_session)
    faction = await _entity(db_session, novel_id, "faction", "塔罗会")
    empty_faction = await _entity(db_session, novel_id, "faction", "空壳势力")
    archived_faction = await _entity(
        db_session, novel_id, "faction", "覆灭势力", status="deprecated"
    )
    linked = await _entity(db_session, novel_id, "character", "克莱恩")
    candidate_member = await _entity(db_session, novel_id, "character", "候选者")
    deprecated_member = await _entity(db_session, novel_id, "character", "退场者")
    archived_member = await _entity(
        db_session, novel_id, "character", "归档者", status="merged"
    )
    archived_group_member = await _entity(db_session, novel_id, "character", "余党")
    await _entity(db_session, novel_id, "character", "无归属者")
    await _relation(db_session, novel_id, linked, faction, "member_of")
    await _relation(
        db_session, novel_id, candidate_member, faction, "member_of", status="candidate"
    )
    await _relation(
        db_session,
        novel_id,
        deprecated_member,
        faction,
        "member_of",
        status="deprecated",
    )
    await _relation(db_session, novel_id, archived_member, faction, "member_of")
    # 归档组端点上的关系不构成已关联。
    await _relation(
        db_session, novel_id, archived_group_member, archived_faction, "member_of"
    )

    page = await _service.list_relation_groups(
        db_session, novel_id, group_view="affiliation"
    )

    counts = {item.id: item.member_count for item in page.items}
    # 零成员组保留；归档组不出现。
    assert counts == {str(faction.id): 1, str(empty_faction.id): 0}
    assert page.total == 2
    # 候选关系 / deprecated 关系 / 归档组端点都不构成已关联；归档成员本身
    # 不是 active 对象，不进入未关联统计。
    assert page.unlinked_total == 4


async def test_same_member_in_multiple_groups_and_relation_dedupe(db_session) -> None:
    novel_id = await _prepare(db_session)
    f1 = await _entity(db_session, novel_id, "faction", "光明教会")
    f2 = await _entity(db_session, novel_id, "faction", "黑暗教会")
    shared = await _entity(db_session, novel_id, "character", "双面人")
    only_f1 = await _entity(db_session, novel_id, "character", "信徒")
    await _relation(db_session, novel_id, shared, f1, "member_of")
    await _relation(db_session, novel_id, shared, f1, "leader_of")
    await _relation(db_session, novel_id, shared, f2, "member_of")
    await _relation(db_session, novel_id, only_f1, f1, "member_of")

    page = await _service.list_relation_groups(
        db_session, novel_id, group_view="affiliation"
    )

    counts = {item.id: item.member_count for item in page.items}
    # member_count 是对象数不是关系数：f1 两名成员（3 条关系），f2 一名。
    assert counts == {str(f1.id): 2, str(f2.id): 1}
    assert page.unlinked_total == 0
    # 排序：member_count 降序。
    assert page.items[0].id == str(f1.id)


# ============================================================
# custom 视角与参数校验
# ============================================================


async def test_custom_view_group_type_relation_and_side(db_session) -> None:
    novel_id = await _prepare(db_session)
    tower = await _entity(db_session, novel_id, "location", "黑塔")
    guard = await _entity(db_session, novel_id, "character", "守塔人")
    other = await _entity(db_session, novel_id, "character", "访客")
    await _relation(
        db_session, novel_id, tower, guard, "guards", relation_kind="intentional"
    )
    await _relation(
        db_session, novel_id, other, tower, "located_at", relation_kind="spatial"
    )

    page = await _service.list_relation_groups(
        db_session,
        novel_id,
        group_view="custom",
        group_type="location",
        member_type="character",
        relation_type="guards",
        group_side="source",
    )

    assert page.total == 1
    assert page.items[0].id == str(tower.id)
    assert page.items[0].member_count == 1
    # 位于关系不是 custom 视角规则，访客未关联。
    assert page.unlinked_total == 1
    custom_views = [view for view in page.views if view.custom]
    assert len(custom_views) == 1
    custom = custom_views[0]
    assert custom.key == "custom"
    assert custom.group_types == ["location"]
    assert custom.member_types == ["character"]
    assert [option.relation_type for option in custom.match_relations] == ["guards"]
    assert custom.match_relations[0].group_side == "source"
    assert custom.default_relation.relation_type == "guards"
    assert len(page.views) == 5


@pytest.mark.parametrize(
    "overrides",
    [
        {"group_type": None, "relation_type": "guards", "group_side": "source"},
        {"group_type": "location", "relation_type": None, "group_side": "source"},
        {"group_type": "location", "relation_type": "guards", "group_side": None},
        {"group_type": "location", "relation_type": "guards", "group_side": "middle"},
    ],
)
async def test_custom_view_invalid_configuration_rejected(
    db_session, overrides: dict
) -> None:
    novel_id = await _prepare(db_session)
    with pytest.raises(ValidationError):
        await _service.list_relation_groups(
            db_session,
            novel_id,
            group_view="custom",
            group_type=overrides.get("group_type"),
            relation_type=overrides.get("relation_type"),
            group_side=overrides.get("group_side"),
        )


async def test_unknown_group_view_rejected(db_session) -> None:
    novel_id = await _prepare(db_session)
    with pytest.raises(ValidationError):
        await _service.list_relation_groups(
            db_session, novel_id, group_view="nonexistent"
        )


# ============================================================
# 跨 novel 隔离
# ============================================================


async def test_relation_groups_isolated_per_novel(db_session) -> None:
    novel_a = await _prepare(db_session)
    novel_b = await _prepare(db_session)
    faction_a = await _entity(db_session, novel_a, "faction", "A 势力")
    faction_b = await _entity(db_session, novel_b, "faction", "B 势力")
    member_a = await _entity(db_session, novel_a, "character", "A 成员")
    member_b = await _entity(db_session, novel_b, "character", "B 成员")
    await _relation(db_session, novel_a, member_a, faction_a, "member_of")
    await _relation(db_session, novel_b, member_b, faction_b, "member_of")

    page_a = await _service.list_relation_groups(
        db_session, novel_a, group_view="affiliation"
    )
    page_b = await _service.list_relation_groups(
        db_session, novel_b, group_view="affiliation"
    )

    assert [item.id for item in page_a.items] == [str(faction_a.id)]
    assert [item.id for item in page_b.items] == [str(faction_b.id)]
    assert page_a.unlinked_total == 0
    assert page_b.unlinked_total == 0


# ============================================================
# 分页与排序稳定性
# ============================================================


async def test_relation_groups_pagination_over_fifty(db_session) -> None:
    novel_id = await _prepare(db_session)
    for index in range(55):
        faction = await _entity(db_session, novel_id, "faction", f"势力{index:02d}")
        if index < 3:
            member = await _entity(db_session, novel_id, "character", f"成员{index:02d}")
            await _relation(db_session, novel_id, member, faction, "member_of")

    first = await _service.list_relation_groups(
        db_session, novel_id, group_view="affiliation", skip=0, limit=50
    )
    second = await _service.list_relation_groups(
        db_session, novel_id, group_view="affiliation", skip=50, limit=50
    )

    assert first.total == 55
    assert len(first.items) == 50
    assert second.total == 55
    assert len(second.items) == 5
    assert {item.id for item in first.items}.isdisjoint(
        {item.id for item in second.items}
    )
    # member_count 降序、name 升序：前三个是带成员的组。
    assert [item.member_count for item in first.items[:3]] == [1, 1, 1]
    assert [item.name for item in first.items[:3]] == ["势力00", "势力01", "势力02"]
    assert first.skip == 0
    assert first.limit == 50
    assert second.skip == 50


async def test_relation_groups_q_matches_name_and_alias(db_session) -> None:
    novel_id = await _prepare(db_session)
    named = await _entity(db_session, novel_id, "faction", "光明教会")
    aliased = await _entity(
        db_session,
        novel_id,
        "faction",
        "值夜者小队",
        aliases=[{"alias": "黑夜眷者", "status": "active"}],
    )
    unrelated = await _entity(db_session, novel_id, "faction", "风暴之主")

    by_name = await _service.list_relation_groups(
        db_session, novel_id, group_view="affiliation", q="光明"
    )
    by_alias = await _service.list_relation_groups(
        db_session, novel_id, group_view="affiliation", q="黑夜眷者"
    )

    assert [item.id for item in by_name.items] == [str(named.id)]
    assert by_name.total == 1
    assert [item.id for item in by_alias.items] == [str(aliased.id)]
    assert by_alias.total == 1
    assert unrelated.id not in {item.id for item in by_alias.items}


# ============================================================
# list_library 分组模式
# ============================================================


async def _affiliation_fixture(db_session) -> tuple:
    novel_id = await _prepare(db_session)
    faction = await _entity(db_session, novel_id, "faction", "塔罗会")
    klein = await _entity(db_session, novel_id, "character", "克莱恩")
    audrey = await _entity(db_session, novel_id, "character", "奥黛丽")
    dunn = await _entity(db_session, novel_id, "character", "邓恩")
    member_rel = await _relation(db_session, novel_id, klein, faction, "member_of")
    leader_rel = await _relation(db_session, novel_id, klein, faction, "leader_of")
    audrey_rel = await _relation(db_session, novel_id, audrey, faction, "member_of")
    # 候选关系：不构成成员、不出现在 relation_refs。
    await _relation(db_session, novel_id, dunn, faction, "member_of", status="candidate")
    return novel_id, faction, klein, audrey, dunn, member_rel, leader_rel, audrey_rel


async def test_list_library_group_mode_assembles_relation_refs(db_session) -> None:
    (
        novel_id,
        faction,
        klein,
        audrey,
        dunn,
        member_rel,
        leader_rel,
        audrey_rel,
    ) = await _affiliation_fixture(db_session)

    page = await _service.list_library(
        db_session,
        novel_id,
        group_view="affiliation",
        group_id=str(faction.id),
        sort="title",
    )

    assert page.total == 2
    by_id = {item.id: item for item in page.items}
    assert set(by_id) == {str(klein.id), str(audrey.id)}
    klein_item = by_id[str(klein.id)]
    audrey_item = by_id[str(audrey.id)]
    # 克莱恩两条匹配关系全部装配，指纹为 64 位。
    klein_refs = {ref.relation.id for ref in klein_item.relation_refs}
    assert klein_refs == {str(member_rel.id), str(leader_rel.id)}
    for ref in klein_item.relation_refs:
        assert len(ref.execution_fingerprint) == 64
        assert ref.relation.status == "canonical"
        assert ref.relation.source_name == "克莱恩"
        assert ref.relation.target_name == "塔罗会"
    assert {ref.relation.id for ref in audrey_item.relation_refs} == {str(audrey_rel.id)}
    # 候选关系不出现；邓恩不是成员。
    assert str(dunn.id) not in by_id


async def test_list_library_group_mode_ignores_directory_filters(db_session) -> None:
    (
        novel_id,
        faction,
        klein,
        audrey,
        _dunn,
        _member_rel,
        _leader_rel,
        _audrey_rel,
    ) = await _affiliation_fixture(db_session)

    # kind/topic/favorite/unclassified 被忽略：强制 entity 成员语义。
    page = await _service.list_library(
        db_session,
        novel_id,
        group_view="affiliation",
        group_id=str(faction.id),
        kind="page",
        favorite=True,
        unclassified=True,
        topic_id=None,
        sort="title",
    )

    assert page.total == 2
    assert {item.id for item in page.items} == {str(klein.id), str(audrey.id)}


async def test_list_library_group_mode_item_type_intersected(db_session) -> None:
    novel_id = await _prepare(db_session)
    hero = await _entity(db_session, novel_id, "character", "克莱恩")
    sword = await _entity(db_session, novel_id, "item", "霜华剑")
    amulet = await _entity(db_session, novel_id, "artifact", "护符")
    await _relation(
        db_session, novel_id, sword, hero, "belongs_to", relation_kind="state"
    )
    await _relation(db_session, novel_id, hero, amulet, "携带", relation_kind="spatial")

    character_page = await _service.list_library(
        db_session,
        novel_id,
        group_view="possessions",
        group_id=str(hero.id),
        item_type="item",
        sort="title",
    )
    mismatch_page = await _service.list_library(
        db_session,
        novel_id,
        group_view="possessions",
        group_id=str(hero.id),
        item_type="location",
        sort="title",
    )
    full_page = await _service.list_library(
        db_session,
        novel_id,
        group_view="possessions",
        group_id=str(hero.id),
        sort="title",
    )

    # item_type 与 member_types 取交集：交集为空 → 空结果（固定行为）。
    assert character_page.total == 1
    assert [item.id for item in character_page.items] == [str(sword.id)]
    assert mismatch_page.total == 0
    assert mismatch_page.items == []
    assert full_page.total == 2
    assert {item.id for item in full_page.items} == {str(sword.id), str(amulet.id)}


async def test_list_library_group_mode_validates_group(db_session) -> None:
    (
        novel_id,
        faction,
        _klein,
        _audrey,
        _dunn,
        _member_rel,
        _leader_rel,
        _audrey_rel,
    ) = await _affiliation_fixture(db_session)
    character = await _entity(db_session, novel_id, "character", "非组对象")
    other_novel = await _prepare(db_session)
    other_faction = await _entity(db_session, other_novel, "faction", "他乡势力")

    # entity_type 不在视角 group_types。
    with pytest.raises(NotFoundError):
        await _service.list_library(
            db_session, novel_id, group_view="affiliation", group_id=str(character.id)
        )
    # 跨 novel 的组对象不可见。
    with pytest.raises(NotFoundError):
        await _service.list_library(
            db_session,
            novel_id,
            group_view="affiliation",
            group_id=str(other_faction.id),
        )
    # 不存在。
    with pytest.raises(NotFoundError):
        await _service.list_library(
            db_session,
            novel_id,
            group_view="affiliation",
            group_id=uuid.uuid4().hex,
        )
    # group_id 与 group_unlinked 互斥。
    with pytest.raises(ValidationError):
        await _service.list_library(
            db_session,
            novel_id,
            group_view="affiliation",
            group_id=str(faction.id),
            group_unlinked=True,
        )


async def test_list_library_unlinked_mode_returns_scope_objects(db_session) -> None:
    (
        novel_id,
        faction,
        klein,
        audrey,
        dunn,
        _member_rel,
        _leader_rel,
        _audrey_rel,
    ) = await _affiliation_fixture(db_session)
    orphan = await _entity(db_session, novel_id, "character", "无归属者")
    stray_item = await _entity(db_session, novel_id, "item", "路边剑")

    page = await _service.list_library(
        db_session,
        novel_id,
        group_view="affiliation",
        group_unlinked=True,
        sort="title",
    )
    searched = await _service.list_library(
        db_session,
        novel_id,
        group_view="affiliation",
        group_unlinked=True,
        q="无归属",
        sort="title",
    )

    # dunn 只有候选关系 → 未关联；item 不在 character 口径。
    assert page.total == 2
    assert {item.id for item in page.items} == {str(dunn.id), str(orphan.id)}
    assert all(not item.relation_refs for item in page.items)
    assert searched.total == 1
    assert [item.id for item in searched.items] == [str(orphan.id)]
    assert stray_item.id not in {item.id for item in page.items}


async def test_list_library_group_mode_pagination_over_fifty(db_session) -> None:
    novel_id = await _prepare(db_session)
    faction = await _entity(db_session, novel_id, "faction", "大势力")
    for index in range(60):
        member = await _entity(db_session, novel_id, "character", f"成员{index:02d}")
        await _relation(db_session, novel_id, member, faction, "member_of")

    first = await _service.list_library(
        db_session,
        novel_id,
        group_view="affiliation",
        group_id=str(faction.id),
        skip=0,
        limit=50,
        sort="title",
    )
    second = await _service.list_library(
        db_session,
        novel_id,
        group_view="affiliation",
        group_id=str(faction.id),
        skip=50,
        limit=50,
        sort="title",
    )

    assert first.total == 60
    assert len(first.items) == 50
    assert second.total == 60
    assert len(second.items) == 10
    assert {item.id for item in first.items}.isdisjoint(
        {item.id for item in second.items}
    )
    assert len(first.items[0].relation_refs) == 1


# ============================================================
# 查询次数：relation_refs 装配不随成员数线性增长
# ============================================================


class _SelectCounter:
    def __init__(self, sync_engine) -> None:
        self.count = 0
        self._sync_engine = sync_engine
        event.listen(sync_engine, "before_cursor_execute", self._record)

    def _record(self, _conn, cursor, statement, _params, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            self.count += 1

    def close(self) -> None:
        event.remove(self._sync_engine, "before_cursor_execute", self._record)


async def test_group_mode_select_count_stays_flat_with_page_size(db_session) -> None:
    novel_id = await _prepare(db_session)
    faction = await _entity(db_session, novel_id, "faction", "大势力")
    for index in range(30):
        member = await _entity(db_session, novel_id, "character", f"成员{index:02d}")
        await _relation(db_session, novel_id, member, faction, "member_of")

    counter = _SelectCounter(db_session.sync_session.get_bind().engine)
    try:
        small_page = await _service.list_library(
            db_session,
            novel_id,
            group_view="affiliation",
            group_id=str(faction.id),
            limit=5,
            sort="title",
        )
        small_count = counter.count
        assert small_page.total == 30
        assert len(small_page.items) == 5
        assert all(item.relation_refs for item in small_page.items)

        counter.count = 0
        big_page = await _service.list_library(
            db_session,
            novel_id,
            group_view="affiliation",
            group_id=str(faction.id),
            limit=50,
            sort="title",
        )
        big_count = counter.count
        assert len(big_page.items) == 30
        assert all(item.relation_refs for item in big_page.items)
    finally:
        counter.close()

    # SELECT 语句数不随页内成员数线性增长（组校验 + total + items + refs）。
    assert small_count <= 5
    assert big_count <= 5
    assert big_count <= small_count + 1


# ============================================================
# 非分组请求保持原行为
# ============================================================


async def test_list_library_without_group_view_keeps_default_behavior(db_session) -> None:
    novel_id = await _prepare(db_session)
    faction = await _entity(db_session, novel_id, "faction", "塔罗会")
    klein = await _entity(db_session, novel_id, "character", "克莱恩")
    await _relation(db_session, novel_id, klein, faction, "member_of")

    page = await _service.list_library(
        db_session, novel_id, kind="entity", q="克莱恩", sort="title"
    )
    entity_only = await _service.list_library(db_session, novel_id, kind="entity")
    all_items = await _service.list_library(db_session, novel_id)

    assert page.total == 1
    assert page.items[0].id == str(klein.id)
    assert page.items[0].relation_refs == []
    assert entity_only.total == 2
    assert all(entity.relation_refs == [] for entity in all_items.items)
    assert all_items.total == 2


# ============================================================
# G1 API 集成：真实路由注册后的 HTTP 链路
# ============================================================


async def _api_create_project(client) -> str:
    response = await client.post("/api/projects", json={"title": "关系分组 API 集成"})
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def _api_create_entity(
    client, novel_id: str, *, name: str, entity_type: str
) -> str:
    response = await client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"novel_id": novel_id, "entity_type": entity_type, "name": name},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_relation_groups_route_returns_views_items_and_unlinked(
    async_client,
) -> None:
    novel_id = await _api_create_project(async_client)
    faction = await _api_create_entity(
        async_client, novel_id, name=" API 集成商会", entity_type="faction"
    )
    _member = await _api_create_entity(
        async_client, novel_id, name="API 集成成员", entity_type="character"
    )
    response = await async_client.get(
        "/api/world/library/relation-groups",
        params={"novel_id": novel_id, "group_view": "affiliation"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert [view["key"] for view in data["views"]] == [
        "affiliation", "location", "possessions", "event",
    ]
    assert data["items"][0]["id"] == faction
    assert data["items"][0]["member_count"] == 0
    assert data["unlinked_total"] == 1  # 成员尚未加入

    invalid = await async_client.get(
        "/api/world/library/relation-groups",
        params={"novel_id": novel_id, "group_view": "bogus"},
    )
    assert invalid.status_code == 422
    assert "group_view" in invalid.json()["detail"]


@pytest.mark.asyncio
async def test_membership_batch_route_add_and_remove_roundtrip(
    async_client,
) -> None:
    novel_id = await _api_create_project(async_client)
    faction = await _api_create_entity(
        async_client, novel_id, name="批量商会", entity_type="faction"
    )
    member = await _api_create_entity(
        async_client, novel_id, name="批量成员", entity_type="character"
    )

    add = await async_client.post(
        "/api/world/relations/membership-batch",
        params={"novel_id": novel_id},
        json={
            "novel_id": novel_id,
            "action": "add",
            "group_view": "affiliation",
            "group_id": faction,
            "member_ids": [member],
            "confirmed": True,
        },
    )
    assert add.status_code == 200, add.text
    assert add.json()["added_count"] == 1
    relation_id = add.json()["affected_relation_ids"][0]

    listed = await async_client.get(
        "/api/world/library",
        params={
            "novel_id": novel_id,
            "group_view": "affiliation",
            "group_id": faction,
        },
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert [item["id"] for item in items] == [member]
    refs = items[0]["relation_refs"]
    assert len(refs) == 1
    assert refs[0]["relation"]["relation_type"] == "member_of"
    assert len(refs[0]["execution_fingerprint"]) == 64

    stale = await async_client.post(
        "/api/world/relations/membership-batch",
        params={"novel_id": novel_id},
        json={
            "novel_id": novel_id,
            "action": "remove",
            "group_view": "affiliation",
            "group_id": faction,
            "member_ids": [member],
            "confirmed": True,
            "relation_refs": [
                {"id": relation_id, "expected_execution_fingerprint": "f" * 64}
            ],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "stale_execution"

    remove = await async_client.post(
        "/api/world/relations/membership-batch",
        params={"novel_id": novel_id},
        json={
            "novel_id": novel_id,
            "action": "remove",
            "group_view": "affiliation",
            "group_id": faction,
            "member_ids": [member],
            "confirmed": True,
            "relation_refs": [
                {
                    "id": relation_id,
                    "expected_execution_fingerprint": refs[0]["execution_fingerprint"],
                }
            ],
        },
    )
    assert remove.status_code == 200, remove.text
    assert remove.json()["removed_count"] == 1

    after = await async_client.get(
        "/api/world/library/relation-groups",
        params={"novel_id": novel_id, "group_view": "affiliation"},
    )
    assert after.json()["items"][0]["member_count"] == 0
