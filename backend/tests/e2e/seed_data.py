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


# geo / outline / review 模块已移除，相关种子数据不再维护


# ---- 组合函数 ------------------------------------------------------------

async def create_base_scene(session: AsyncSession) -> dict[str, Any]:
    """
    创建基础场景数据：项目 + 世界对象 + 关系。

    geo/outline/review/character/timeline 模块已移除，不创建相关数据。
    """
    meta = await create_project(session)
    pid = meta["project_uuid"]

    entities = await create_world_entities(session, pid)
    eids = entities["entity_ids"]

    await create_relationships(session, pid, eids)
    await session.flush()

    return {
        "project_id": meta["project_id"],
        "project_uuid": pid,
        "entity_ids": eids,
    }


async def create_full_scene(session: AsyncSession) -> dict[str, Any]:
    """
    创建全场景数据：同 base scene。
    outline 模块已移除，不再创建剧情线/篇章纲/章节卡。
    """
    return await create_base_scene(session)
