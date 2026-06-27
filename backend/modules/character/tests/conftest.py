"""Character 模块测试配置 — 使用根 conftest 的 db_session"""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.character.repositories import (
    CharacterKnowledgeRepository,
    CharacterRepository,
)
from modules.character.schemas import CharacterCreate, CharacterKnowledgeCreate


@pytest_asyncio.fixture
async def sample_novel_id() -> str:
    """测试用小说项目 ID"""
    return str(uuid.uuid4())


@pytest_asyncio.fixture
async def sample_character_id(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> str:
    """创建测试人物并返回 ID"""
    repo = CharacterRepository()
    data = CharacterCreate(
        novel_id=sample_novel_id,
        name="林月",
        role="protagonist",
        appearance="黑发碧眸，身高170cm",
        personality="冷静果断，外冷内热",
        desire="寻找失散的家人",
        fear="再次失去重要的人",
        secret="拥有预知未来的能力",
        weakness="过于信任熟人",
        current_goal="调查城市异变",
        current_state="正在前往旧城区",
        current_emotion="警惕",
        stance="中立善良",
        voice_style="简洁有力，不轻易表露情绪",
        behavior_rules=[
            {"rule": "不主动透露自己的真实身份", "context": "与陌生人交谈时"},
            {"rule": "优先保护同伴", "context": "遇到危险时"},
        ],
        relationship_summary="与陈锋是搭档关系，与暗影组织敌对",
    )
    character = await repo.create(db_session, data)
    return str(character.id)


@pytest_asyncio.fixture
async def sample_target_entity_id() -> str:
    """测试用目标实体 ID"""
    return str(uuid.uuid4())


@pytest_asyncio.fixture
async def sample_knowledge_id(
    db_session: AsyncSession,
    sample_novel_id: str,
    sample_character_id: str,
    sample_target_entity_id: str,
) -> str:
    """创建测试用知识记录并返回 ID"""
    repo = CharacterKnowledgeRepository()
    data = CharacterKnowledgeCreate(
        novel_id=sample_novel_id,
        character_id=sample_character_id,
        target_type="entity",
        target_id=sample_target_entity_id,
        knowledge_level="partial",
        known_content="暗影组织是一个活跃在城市地下的神秘势力",
        misconception=None,
        source_chapter_index=1,
    )
    knowledge = await repo.create(db_session, data)
    return str(knowledge.id)
