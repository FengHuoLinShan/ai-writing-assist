"""
诡秘之主 第一部 — E2E 测试种子数据

提供分层的工厂函数，按顺序创建测试数据并返回各级 ID 的字典。
每个函数接受一个 AsyncSession，使用 ORM 模型创建记录。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# 确保 EntityRelation 等模型的外键表被注册到 SQLAlchemy metadata
import modules.imports.models  # noqa: F401

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


# ---- Scene 卡 -----------------------------------------------------------

SCENE_DATA = [
    {
        "scene_index": 0,
        "title": "第一章： valueless 的占卜",
        "goal": "引入克莱恩的日常生活与廷根市值夜者",
        "must_not_happen": "克莱恩不得在本幕知晓源堡真相",
        "pov_character_name": "克莱恩·莫雷蒂",
    },
    {
        "scene_index": 1,
        "title": "第二章：黑荆棘安保公司",
        "goal": "克莱恩加入值夜者，接触非凡世界",
    },
    {
        "scene_index": 2,
        "title": "第三章：序列途径",
        "goal": "克莱恩了解占卜家序列，埋下成长伏笔",
    },
]


async def create_scenes(
    session: AsyncSession,
    project_id: uuid.UUID,
    entity_ids: dict[str, str],
) -> dict[str, Any]:
    """创建 3 个 Scene 卡（第 1-3 章），返回 scene_index → ID 的字典。"""
    from modules.outline.models import Scene

    result: list[str] = []
    for data in SCENE_DATA:
        scene = Scene(
            id=uuid.uuid4(),
            novel_id=project_id,
            scene_index=data["scene_index"],
            title=data.get("title"),
            goal=data.get("goal"),
            must_not_happen=data.get("must_not_happen"),
            pov_character_id=entity_ids.get(data["pov_character_name"])
            if data.get("pov_character_name")
            else None,
            narrative_tag="draft",
            source="manual",
            status="canonical",
        )
        session.add(scene)
        result.append(str(scene.id))

    await session.flush()
    return {"scene_ids": result}


# ---- 人物知识边界 -------------------------------------------------------

CHARACTER_KNOWLEDGE_DATA = [
    {
        "character_name": "克莱恩·莫雷蒂",
        "target_name": "源堡",
        "target_type": "entity",
        "knowledge_level": "unknown",
    },
    {
        "character_name": "克莱恩·莫雷蒂",
        "target_name": "罗塞尔日记",
        "target_type": "entity",
        "knowledge_level": "restricted",
        "known_content": "罗塞尔大帝留下的神秘日记，文字古怪",
    },
    {
        "character_name": "克莱恩·莫雷蒂",
        "target_name": "秘修会",
        "target_type": "entity",
        "knowledge_level": "misunderstood",
        "misconception": "秘修会是一个普通的考古学会",
    },
]


async def create_character_knowledge(
    session: AsyncSession,
    project_id: uuid.UUID,
    entity_ids: dict[str, str],
) -> dict[str, Any]:
    """创建克莱恩的人物档案与知识边界记录。"""
    from modules.world.models import Character, CharacterKnowledge

    klein_entity_id = uuid.UUID(entity_ids["克莱恩·莫雷蒂"])
    character = Character(
        entity_id=klein_entity_id,
        novel_id=project_id,
        name="克莱恩·莫雷蒂",
        role="protagonist",
    )
    session.add(character)
    await session.flush()

    for data in CHARACTER_KNOWLEDGE_DATA:
        knowledge = CharacterKnowledge(
            id=uuid.uuid4(),
            novel_id=project_id,
            character_id=klein_entity_id,
            target_type=data["target_type"],
            target_id=uuid.UUID(entity_ids[data["target_name"]]),
            knowledge_level=data["knowledge_level"],
            known_content=data.get("known_content"),
            misconception=data.get("misconception"),
            status="canonical",
        )
        session.add(knowledge)

    await session.flush()
    return {"character_id": str(klein_entity_id)}


# ---- 伏笔计划 -----------------------------------------------------------

FORESHADOWING_PLAN_DATA = [
    {
        "name": "源堡伏笔",
        "surface_meaning": "灰雾之上的神秘空间",
        "planned_seed_chapter": 1,
        "planned_payoff_scene": 5,
        "status": "seeded",
    },
    {
        "name": "罗塞尔日记伏笔",
        "surface_meaning": "大帝留下的神秘日记",
        "planned_seed_chapter": 1,
        "planned_payoff_scene": 3,
        "status": "seeded",
    },
]


async def create_foreshadowing_plans(
    session: AsyncSession,
    project_id: uuid.UUID,
    entity_ids: dict[str, str],
) -> dict[str, Any]:
    """创建 2 条 ForeshadowingPlan 记录。"""
    from modules.outline.models import ForeshadowingPlan

    result: list[str] = []
    for data in FORESHADOWING_PLAN_DATA:
        plan = ForeshadowingPlan(
            id=uuid.uuid4(),
            novel_id=project_id,
            name=data["name"],
            surface_meaning=data["surface_meaning"],
            planned_seed_chapter=data["planned_seed_chapter"],
            planned_payoff_scene=data["planned_payoff_scene"],
            status=data["status"],
        )
        session.add(plan)
        result.append(str(plan.id))

    await session.flush()
    return {"foreshadowing_plan_ids": result}


# ---- 正文草稿 -----------------------------------------------------------


async def create_writing_drafts(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    """为第 1-3 章创建真实的《诡秘之主 第一部》正文草稿。"""
    from modules.writing.models import WritingDraft

    sample_path = Path(__file__).with_name("samples") / "lotm_chapters_1_2_3.txt"
    if not sample_path.exists():
        raise FileNotFoundError(f"找不到章节样本: {sample_path}")

    raw = sample_path.read_text(encoding="utf-8")
    chapters = [part.strip() for part in raw.split("\n\n---\n\n") if part.strip()]

    result: list[str] = []
    for chapter_index, content in enumerate(chapters, start=1):
        # 提取标题：第一行
        lines = content.splitlines()
        title = lines[0].strip() if lines else f"第{chapter_index}章"
        draft = WritingDraft(
            id=uuid.uuid4(),
            novel_id=project_id,
            chapter_index=chapter_index,
            title=title,
            content=content,
            version_number=1,
            status="canonical",
        )
        session.add(draft)
        result.append(str(draft.id))

    await session.flush()
    return {"writing_draft_ids": result}


# ---- 关系 ---------------------------------------------------------------

RELATIONSHIP_DATA = [
    {
        "source": "克莱恩·莫雷蒂",
        "target": "值夜者",
        "type": "member_of",
        "kind": "social",
    },
    {
        "source": "克莱恩·莫雷蒂",
        "target": "邓恩·史密斯",
        "type": "subordinate_of",
        "kind": "social",
    },
    {
        "source": "克莱恩·莫雷蒂",
        "target": "罗塞尔日记",
        "type": "related_to",
        "kind": "state",
    },
    {
        "source": "罗塞尔·古斯塔夫",
        "target": "罗塞尔日记",
        "type": "created_by",
        "kind": "causal",
    },
    {"source": "秘修会", "target": "值夜者", "type": "opposes", "kind": "intentional"},
    {"source": "源堡", "target": "克莱恩·莫雷蒂", "type": "related_to", "kind": "state"},
    {
        "source": "占卜家序列",
        "target": "克莱恩·莫雷蒂",
        "type": "related_to",
        "kind": "state",
    },
]


async def create_relationships(
    session: AsyncSession,
    project_id: uuid.UUID,
    entity_ids: dict[str, str],
) -> None:
    """创建世界对象之间的关系。"""
    from modules.world.models import EntityRelation

    for data in RELATIONSHIP_DATA:
        rel = EntityRelation(
            id=uuid.uuid4(),
            novel_id=project_id,
            source_id=entity_ids[data["source"]],
            target_id=entity_ids[data["target"]],
            relation_type=data["type"],
            relation_kind=data["kind"],
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
    创建全场景数据：项目 + 世界对象 + 关系 + Scene 卡 + 人物知识 + 伏笔计划 +
    真实章节正文。
    """
    result = await create_base_scene(session)
    pid = result["project_uuid"]
    eids = result["entity_ids"]

    scenes = await create_scenes(session, pid, eids)
    await create_character_knowledge(session, pid, eids)
    await create_foreshadowing_plans(session, pid, eids)
    drafts = await create_writing_drafts(session, pid)
    await session.flush()

    return {
        **result,
        **scenes,
        **drafts,
    }
