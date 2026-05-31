"""
诡秘之主 第一部 — E2E 测试种子数据

提供分层的工厂函数，按顺序创建测试数据并返回各级 ID 的字典。
每个函数接受一个 AsyncSession，使用 ORM 模型创建记录。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# ---- 项目 ---------------------------------------------------------------

LOTM_PROJECT_DATA = {
    "title": "诡秘之主 第一部",
    "genre": "西方奇幻",
    "tone": "维多利亚风格、黑暗、悬疑",
    "language": "zh",
    "target_length": "novel",
    "current_stage": "writing",
}


async def create_project(session: AsyncSession) -> dict[str, Any]:
    """创建 诡秘之主 项目，返回包含 project_id 的字典。"""
    from modules.project.models import Project

    pid = uuid.uuid4()
    p = Project(
        id=pid,
        title=LOTM_PROJECT_DATA["title"],
        genre=LOTM_PROJECT_DATA["genre"],
        tone=LOTM_PROJECT_DATA["tone"],
        language=LOTM_PROJECT_DATA["language"],
        target_length=LOTM_PROJECT_DATA["target_length"],
        current_stage=LOTM_PROJECT_DATA["current_stage"],
    )
    session.add(p)
    await session.flush()
    return {"project_id": str(pid), "project_uuid": pid}


# ---- 世界对象 -----------------------------------------------------------

WORLD_ENTITY_DATA = [
    {
        "name": "克莱恩·莫雷蒂",
        "entity_type": "character",
        "importance_level": "core",
        "importance": 0.95,
        "public_info": "主角，历史系毕业生，值夜者成员",
        "hidden_truth": "来自另一个世界的穿越者，灵魂附身于克莱恩·莫雷蒂",
        "summary": "本书主角，廷根市值夜者成员",
    },
    {
        "name": "罗塞尔·古斯塔夫",
        "entity_type": "character",
        "importance_level": "important",
        "importance": 0.85,
        "public_info": "前任大帝，已逝，留下了神秘的日记",
        "hidden_truth": "也是穿越者，用中文书写日记，曾探索序列0的秘密",
        "summary": "鲁恩王国传奇大帝，疑似穿越者",
    },
    {
        "name": "廷根市",
        "entity_type": "location",
        "importance_level": "important",
        "importance": 0.80,
        "public_info": "鲁恩王国的一座城市，主角居住和工作的地方",
        "summary": "故事主要发生地之一",
    },
    {
        "name": "贝克兰德",
        "entity_type": "location",
        "importance_level": "normal",
        "importance": 0.60,
        "summary": "鲁恩王国首都",
    },
    {
        "name": "值夜者",
        "entity_type": "faction",
        "importance_level": "important",
        "importance": 0.80,
        "public_info": "鲁恩王国的官方非凡者组织",
        "hidden_truth": "负责处理普通人无法理解的超凡事件",
        "summary": "克莱恩所属的非凡者组织",
    },
    {
        "name": "塔罗会",
        "entity_type": "faction",
        "importance_level": "normal",
        "importance": 0.75,
        "summary": "秘密组织，以塔罗牌为代号",
    },
    {
        "name": "秘修会",
        "entity_type": "faction",
        "importance_level": "normal",
        "importance": 0.70,
        "public_info": "隐秘的非凡者组织",
        "hidden_truth": "正在寻找古老遗迹，涉及序列0的秘密",
        "summary": "危险的隐秘非凡者组织",
    },
    {
        "name": "占卜家序列",
        "entity_type": "power_system",
        "importance_level": "important",
        "importance": 0.85,
        "summary": "克莱恩所属的序列途径",
    },
    {
        "name": "源堡",
        "entity_type": "secret",
        "importance_level": "core",
        "importance": 0.90,
        "public_info": "灰雾之上的神秘空间",
        "hidden_truth": "源堡是诡秘之主的唯一性所在，与克莱恩的穿越密切相关",
        "summary": "灰雾之上的神秘空间",
    },
    {
        "name": "罗塞尔日记",
        "entity_type": "item",
        "importance_level": "important",
        "importance": 0.80,
        "public_info": "罗塞尔大帝留下的神秘日记",
        "hidden_truth": "用中文书写，包含序列途径的秘密",
        "summary": "关键物品，隐藏着重要信息",
    },
    {
        "name": "邓恩·史密斯",
        "entity_type": "character",
        "importance_level": "normal",
        "importance": 0.60,
        "public_info": "廷根市值夜者小队队长",
        "summary": "克莱恩的上司",
    },
]


async def create_world_entities(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    """创建 10 个核心世界对象，返回对象名→ID 的字典。"""
    from modules.world.models import WorldEntity

    result = {}
    for data in WORLD_ENTITY_DATA:
        eid = uuid.uuid4()
        entity = WorldEntity(
            id=eid,
            novel_id=project_id,
            entity_type=data["entity_type"],
            name=data["name"],
            importance=data["importance"],
            importance_level=data["importance_level"],
            public_info=data.get("public_info"),
            hidden_truth=data.get("hidden_truth"),
            summary=data.get("summary"),
            status="canonical",
        )
        session.add(entity)
        # 名称 → ID 映射
        result[data["name"]] = str(eid)

    await session.flush()
    return {"entity_ids": result}


# ---- 人物 ---------------------------------------------------------------

CHARACTER_DATA = [
    {
        "name": "克莱恩·莫雷蒂",
        "role": "protagonist",
        "personality": "谨慎、聪明、有责任感",
        "current_goal": "晋升序列途径、保护家人",
        "current_state": "值夜者初级成员",
        "current_emotion": "警惕而好奇",
    },
    {
        "name": "伦纳德·米切尔",
        "role": "supporting",
        "personality": "浪漫主义诗人，热情洋溢",
        "current_goal": "完成值夜者任务",
    },
    {
        "name": "邓恩·史密斯",
        "role": "supporting",
        "personality": "稳重、负责的值夜者队长",
        "current_goal": "维护廷根市安全",
    },
    {
        "name": "阿兹克·艾格斯",
        "role": "mentor",
        "personality": "神秘、友善",
    },
    {
        "name": "莎伦",
        "role": "supporting",
        "personality": "优雅、神秘的女演员",
    },
]


async def create_characters(
    session: AsyncSession,
    project_id: uuid.UUID,
    entity_ids: dict[str, str],
) -> dict[str, Any]:
    """创建 5 个人物，返回名称→ID 字典。"""
    from modules.character.models import Character

    result = {}
    for data in CHARACTER_DATA:
        cid = uuid.uuid4()
        char = Character(
            id=cid,
            novel_id=project_id,
            name=data["name"],
            role=data["role"],
            personality=data.get("personality"),
            current_goal=data.get("current_goal"),
            current_state=data.get("current_state"),
            current_emotion=data.get("current_emotion"),
            world_entity_id=uuid.UUID(hex=entity_ids.get(data["name"], ""))
            if data["name"] in entity_ids
            else None,
            status="canonical",
        )
        session.add(char)
        result[data["name"]] = str(cid)

    await session.flush()
    return {"character_ids": result}


# ---- 关系 ---------------------------------------------------------------

RELATIONSHIP_DATA = [
    {"source": "克莱恩·莫雷蒂", "target": "值夜者", "type": "member_of"},
    {"source": "克莱恩·莫雷蒂", "target": "邓恩·史密斯", "type": "subordinate_of"},
    {"source": "克莱恩·莫雷蒂", "target": "罗塞尔日记", "type": "related_to"},
    {"source": "罗塞尔·古斯塔夫", "target": "罗塞尔日记", "type": "created_by"},
    {"source": "秘修会", "target": "值夜者", "type": "opposes"},
    {"source": "源堡", "target": "克莱恩·莫雷蒂", "type": "related_to"},
    {"source": "占卜家序列", "target": "克莱恩·莫雷蒂", "type": "related_to"},
]


async def create_relationships(
    session: AsyncSession,
    project_id: uuid.UUID,
    entity_ids: dict[str, str],
) -> None:
    """创建世界对象之间的关系。"""
    from modules.world.models import Relationship

    for data in RELATIONSHIP_DATA:
        rel = Relationship(
            id=uuid.uuid4(),
            novel_id=project_id,
            source_type="world_entity",
            source_id=entity_ids[data["source"]],
            target_type="world_entity",
            target_id=entity_ids[data["target"]],
            relation_type=data["type"],
            status="canonical",
        )
        session.add(rel)

    await session.flush()


# ---- 地理 ---------------------------------------------------------------

LOCATION_TREE = {
    "鲁恩王国": {
        "level": "country",
        "children": {
            "廷根市": {
                "level": "city",
                "children": {
                    "廷根市教堂": {"level": "building", "children": {}},
                    "莫雷蒂家": {"level": "building", "children": {}},
                },
            },
            "贝克兰德": {"level": "city", "children": {}},
        },
    },
}


async def create_locations(
    session: AsyncSession,
    project_id: uuid.UUID,
    entity_ids: dict[str, str],
) -> dict[str, Any]:
    """创建地理层级（含世界对象关联），返回地点名→ID 字典。

    如果 location 名称不在 entity_ids 中，自动创建对应的 WorldEntity。
    """
    from modules.geo.models import GeoLocation
    from modules.world.models import WorldEntity

    result = {}

    async def _ensure_entity(name: str) -> uuid.UUID:
        """确保 location 有对应的 WorldEntity，返回其 ID"""
        if name in entity_ids:
            return uuid.UUID(hex=entity_ids[name])
        eid = uuid.uuid4()
        session.add(WorldEntity(
            id=eid,
            novel_id=project_id,
            entity_type="location",
            name=name,
            status="canonical",
        ))
        entity_ids[name] = str(eid)
        await session.flush()  # 立即 flush 确保 FK 可引用
        return eid

    async def _create_tree(
        name: str,
        node: dict,
        parent_id: uuid.UUID | None,
    ) -> uuid.UUID:
        lid = uuid.uuid4()
        we_id = await _ensure_entity(name)

        loc = GeoLocation(
            id=lid,
            novel_id=project_id,
            world_entity_id=we_id,
            location_level=node["level"],
            parent_location_id=parent_id,
            status="canonical",
        )
        session.add(loc)
        result[name] = str(lid)

        for child_name, child_node in node["children"].items():
            await _create_tree(child_name, child_node, lid)

        return lid

    for root_name, root_node in LOCATION_TREE.items():
        await _create_tree(root_name, root_node, None)

    await session.flush()
    return {"location_ids": result}


# ---- 剧情线 -------------------------------------------------------------

THREAD_DATA = [
    {
        "name": "克莱恩的晋升之路",
        "thread_type": "main",
        "summary": "克莱恩从值夜者初级成员逐步晋升的历程",
        "start_chapter": 1,
    },
    {
        "name": "值夜者调查事件",
        "thread_type": "secondary",
        "summary": "值夜者处理的非凡事件调查",
        "start_chapter": 1,
    },
]


async def create_threads(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    """创建两条剧情线。"""
    from modules.outline.models import PlotThread

    result = {}
    for data in THREAD_DATA:
        tid = uuid.uuid4()
        t = PlotThread(
            id=tid,
            novel_id=project_id,
            name=data["name"],
            thread_type=data["thread_type"],
            summary=data.get("summary"),
            start_chapter=data.get("start_chapter"),
            status="draft",
        )
        session.add(t)
        result[data["name"]] = str(tid)

    await session.flush()
    return {"thread_ids": result}


# ---- 篇章纲 -------------------------------------------------------------

ARC_DATA = {
    "title": "廷根篇",
    "arc_index": 1,
    "start_chapter": 1,
    "end_chapter": 30,
    "arc_goal": "建立世界基础，引入克莱恩的穿越者身份和值夜者主线",
    "core_conflict": "克莱恩在普通生活和非凡世界之间的平衡",
}


async def create_arc(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    """创建一个篇章纲。"""
    from modules.outline.models import OutlineArc

    aid = uuid.uuid4()
    arc = OutlineArc(
        id=aid,
        novel_id=project_id,
        title=ARC_DATA["title"],
        arc_index=ARC_DATA["arc_index"],
        start_chapter=ARC_DATA["start_chapter"],
        end_chapter=ARC_DATA["end_chapter"],
        arc_goal=ARC_DATA["arc_goal"],
        core_conflict=ARC_DATA["core_conflict"],
        status="draft",
    )
    session.add(arc)
    await session.flush()
    return {"arc_id": str(aid)}


# ---- 章节卡 -------------------------------------------------------------

CHAPTER_CARD_DATA = [
    {
        "chapter_index": 1,
        "chapter_goal": "引入主角和背景设定",
        "main_conflict": "主角对穿越身份的适应和对新世界的认知",
    },
    {
        "chapter_index": 2,
        "chapter_goal": "展示值夜者的工作任务",
        "main_conflict": "处理非凡事件，发现秘修会的线索",
    },
    {
        "chapter_index": 3,
        "chapter_goal": "主角进一步了解非凡世界的规则",
        "main_conflict": "面临第一个真正的抉择",
    },
]


async def create_chapter_cards(
    session: AsyncSession,
    project_id: uuid.UUID,
    arc_id: str,
) -> dict[str, Any]:
    """创建 3 张章节卡。"""
    from modules.outline.models import ChapterCard

    result = {}
    for data in CHAPTER_CARD_DATA:
        cid = uuid.uuid4()
        card = ChapterCard(
            id=cid,
            novel_id=project_id,
            chapter_index=data["chapter_index"],
            chapter_goal=data["chapter_goal"],
            main_conflict=data["main_conflict"],
            arc_id=uuid.UUID(hex=arc_id),
            status="draft",
        )
        session.add(card)
        result[data["chapter_index"]] = str(cid)

    await session.flush()
    return {"chapter_card_ids": result}


# ---- 组合函数 ------------------------------------------------------------

async def create_base_scene(session: AsyncSession) -> dict[str, Any]:
    """
    创建基础场景数据：项目 + 世界对象 + 人物 + 关系 + 地理。

    返回所有对象 ID 的嵌套字典。
    """
    meta = await create_project(session)
    pid = meta["project_uuid"]

    entities = await create_world_entities(session, pid)
    eids = entities["entity_ids"]

    chars = await create_characters(session, pid, eids)
    cids = chars["character_ids"]

    await create_relationships(session, pid, eids)
    await session.flush()  # 确保所有 WorldEntity 已写入，Geo FK 依赖

    locs = await create_locations(session, pid, eids)
    lids = locs["location_ids"]

    return {
        "project_id": meta["project_id"],
        "project_uuid": pid,
        "entity_ids": eids,
        "character_ids": cids,
        "location_ids": lids,
    }


async def create_full_scene(session: AsyncSession) -> dict[str, Any]:
    """
    创建全场景数据：基础 + 剧情线 + 篇章纲 + 章节卡。

    返回所有对象 ID 的嵌套字典。
    """
    meta = await create_base_scene(session)
    pid = meta["project_uuid"]

    threads = await create_threads(session, pid)
    arcs = await create_arc(session, pid)
    cards = await create_chapter_cards(session, pid, arcs["arc_id"])

    return {
        **meta,
        **threads,
        **arcs,
        **cards,
    }
